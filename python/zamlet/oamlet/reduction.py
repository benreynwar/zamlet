"""Vector reduction via tree reduction.

Emits a sequence of existing kinstrs to perform vector reductions.
Supports single-width integer, single-width float, widening integer,
and widening float reductions (excluding ordered float reductions).

For lmul > 1, the reduction proceeds in two phases:
1. Reduce lmul vlines down to 1 vline using in-place binary tree on temp registers.
2. Cross-jamlet tree reduction on the remaining single vline.
"""

import math

from zamlet import addresses
from zamlet.kamlet import kinstructions
from zamlet.kamlet.kinstructions import VRedOp, VArithOp, VCmpOp, VUnaryOp


_VREDOP_TO_ARITHOP = {
    VRedOp.SUM: VArithOp.ADD,
    VRedOp.AND: VArithOp.AND,
    VRedOp.OR: VArithOp.OR,
    VRedOp.XOR: VArithOp.XOR,
    VRedOp.MAX: VArithOp.MAX,
    VRedOp.MAXU: VArithOp.MAXU,
    VRedOp.MIN: VArithOp.MIN,
    VRedOp.MINU: VArithOp.MINU,
    VRedOp.FSUM: VArithOp.FADD,
    VRedOp.FMAX: VArithOp.FMAX,
    VRedOp.FMIN: VArithOp.FMIN,
    VRedOp.WSUMU: VArithOp.ADD,
    VRedOp.WSUM: VArithOp.ADD,
    VRedOp.FWSUM: VArithOp.FADD,
}

_WIDENING_OPS = {VRedOp.WSUMU, VRedOp.WSUM, VRedOp.FWSUM}


def _identity(op, ew):
    """Return the identity value for a reduction op at the given element width."""
    if op in (VRedOp.SUM, VRedOp.OR, VRedOp.XOR, VRedOp.MAXU,
              VRedOp.WSUMU, VRedOp.WSUM):
        return 0
    elif op == VRedOp.AND:
        return (1 << ew) - 1
    elif op == VRedOp.MIN:
        return (1 << (ew - 1)) - 1
    elif op == VRedOp.MAX:
        return -(1 << (ew - 1))
    elif op == VRedOp.MINU:
        return (1 << ew) - 1
    elif op in (VRedOp.FSUM, VRedOp.FWSUM):
        return 0  # +0.0
    elif op == VRedOp.FMIN:
        if ew == 16:
            return 0x7C00
        elif ew == 32:
            return 0x7F800000
        elif ew == 64:
            return 0x7FF0000000000000
        else:
            raise ValueError(f"Unsupported float ew={ew}")
    elif op == VRedOp.FMAX:
        if ew == 16:
            return 0xFC00
        elif ew == 32:
            return 0xFF800000
        elif ew == 64:
            return 0xFFF0000000000000
        else:
            raise ValueError(f"Unsupported float ew={ew}")
    else:
        raise ValueError(f"Unknown reduction op: {op}")


async def _emit_lmul_setup(lamlet, op, src_vector, mask_reg, n_elements,
                           src_ew, accum_ew, word_order,
                           elements_in_vline, lmul, temp_regs, parent_span_id):
    """Copy vs2 into lmul temp registers with identity fill for inactive elements.

    For widening ops, extends from src_ew to accum_ew.
    Returns the list of temp registers holding the vline data.
    """
    identity = _identity(op, accum_ew)
    widening = src_ew != accum_ew
    vline_regs = temp_regs[:lmul]

    for vline_i in range(lmul):
        vline_start = vline_i * elements_in_vline
        vline_end = min(vline_start + elements_in_vline, n_elements)
        active_in_vline = max(0, vline_end - vline_start)

        # Broadcast identity into this temp register
        instr_ident = await lamlet.get_instr_ident()
        await lamlet.add_to_instruction_buffer(
            kinstructions.VBroadcastOp(
                dst=vline_regs[vline_i], scalar=identity,
                n_elements=elements_in_vline,
                element_width=accum_ew, word_order=word_order,
                instr_ident=instr_ident,
                vta=lamlet.vta, vma=lamlet.vma,
            ), parent_span_id)

        if active_in_vline > 0:
            src_vline_reg = src_vector + vline_i

            if widening:
                # Extend src vline, then masked copy over identity
                # Use the last temp reg as scratch for widening
                scratch = temp_regs[-1] if vline_i < lmul - 1 else temp_regs[-2]
                widen_op = VUnaryOp.ZEXT if op == VRedOp.WSUMU else VUnaryOp.SEXT
                instr_ident = await lamlet.get_instr_ident()
                await lamlet.add_to_instruction_buffer(
                    kinstructions.VUnaryOvOp(
                        op=widen_op, dst=scratch, src=src_vline_reg,
                        n_elements=active_in_vline, dst_ew=accum_ew,
                        src_ew=src_ew, word_order=word_order,
                        mask_reg=mask_reg, instr_ident=instr_ident,
                        vta=lamlet.vta, vma=lamlet.vma,
                    ), parent_span_id)
                src_for_copy = scratch
            else:
                src_for_copy = src_vline_reg

            # Masked copy active elements over identity
            scalar_zero = (0).to_bytes(
                accum_ew // 8, byteorder='little', signed=False)
            instr_ident = await lamlet.get_instr_ident()
            await lamlet.add_to_instruction_buffer(
                kinstructions.VArithVxOp(
                    op=VArithOp.ADD, dst=vline_regs[vline_i],
                    scalar_bytes=scalar_zero, src2=src_for_copy,
                    mask_reg=mask_reg, n_elements=active_in_vline,
                    element_width=accum_ew, word_order=word_order,
                    instr_ident=instr_ident,
                    vta=lamlet.vta, vma=lamlet.vma,
                ), parent_span_id)

    return vline_regs


async def _emit_lmul_tree(lamlet, combine_op, accum_ew, word_order,
                          elements_in_vline, vline_regs, parent_span_id):
    """Reduce lmul vline registers down to 1 via in-place binary tree.

    After this, vline_regs[0] holds the reduced single vline.
    """
    n = len(vline_regs)
    if n == 1:
        return

    # Binary tree: combine pairs, halving each round
    active = list(vline_regs)
    while len(active) > 1:
        next_active = []
        for i in range(0, len(active), 2):
            if i + 1 < len(active):
                instr_ident = await lamlet.get_instr_ident()
                await lamlet.add_to_instruction_buffer(
                    kinstructions.VArithVvOp(
                        op=combine_op, dst=active[i], src1=active[i],
                        src2=active[i + 1], mask_reg=None,
                        n_elements=elements_in_vline,
                        element_width=accum_ew, word_order=word_order,
                        instr_ident=instr_ident,
                        vta=lamlet.vta, vma=lamlet.vma,
                    ), parent_span_id)
            next_active.append(active[i])
        active = next_active


async def _emit_cross_jamlet_tree(lamlet, combine_op, accum_ew, word_order,
                                  elements_in_vline, src_reg,
                                  temp_id, temp_idx, temp_mask, data_regs,
                                  parent_span_id):
    """Cross-jamlet tree reduction on a single vline.

    Reduces elements_in_vline elements down to element 0 using gather + combine.
    Returns the data_reg index holding the final result.
    """
    accum_ordering = addresses.Ordering(word_order, accum_ew)

    # VidOp: temp_id = [0, 1, 2, ...]
    instr_ident = await lamlet.get_instr_ident()
    await lamlet.add_to_instruction_buffer(
        kinstructions.VidOp(
            dst=temp_id, n_elements=elements_in_vline,
            element_width=accum_ew, word_order=word_order,
            mask_reg=None, instr_ident=instr_ident,
            vta=lamlet.vta, vma=lamlet.vma,
        ), parent_span_id)

    # Copy src_reg into data_regs[0] if they differ
    if src_reg != data_regs[0]:
        scalar_zero = (0).to_bytes(
            accum_ew // 8, byteorder='little', signed=False)
        instr_ident = await lamlet.get_instr_ident()
        await lamlet.add_to_instruction_buffer(
            kinstructions.VArithVxOp(
                op=VArithOp.ADD, dst=data_regs[0],
                scalar_bytes=scalar_zero, src2=src_reg,
                mask_reg=None, n_elements=elements_in_vline,
                element_width=accum_ew, word_order=word_order,
                instr_ident=instr_ident,
                vta=lamlet.vta, vma=lamlet.vma,
            ), parent_span_id)

    n_rounds = max(1, math.ceil(math.log2(elements_in_vline)))
    stride = 1
    src_idx = 0

    for _ in range(n_rounds):
        dst_idx = (src_idx + 1) % 4

        # VArithVxOp AND: temp_idx = temp_id & (2*stride - 1)
        and_mask = (2 * stride - 1).to_bytes(
            accum_ew // 8, byteorder='little', signed=False)
        instr_ident = await lamlet.get_instr_ident()
        await lamlet.add_to_instruction_buffer(
            kinstructions.VArithVxOp(
                op=VArithOp.AND, dst=temp_idx,
                scalar_bytes=and_mask, src2=temp_id,
                mask_reg=None, n_elements=elements_in_vline,
                element_width=accum_ew, word_order=word_order,
                instr_ident=instr_ident,
                vta=lamlet.vta, vma=lamlet.vma,
            ), parent_span_id)

        # VCmpViOp EQ 0: temp_mask = (temp_idx == 0)
        instr_ident = await lamlet.get_instr_ident()
        await lamlet.add_to_instruction_buffer(
            kinstructions.VCmpViOp(
                op=VCmpOp.EQ, dst=temp_mask, src=temp_idx,
                simm5=0, n_elements=elements_in_vline,
                element_width=accum_ew, ordering=accum_ordering,
                instr_ident=instr_ident,
            ), parent_span_id)

        # VArithVxOp ADD: temp_idx = temp_id + stride
        stride_bytes = stride.to_bytes(
            accum_ew // 8, byteorder='little', signed=False)
        instr_ident = await lamlet.get_instr_ident()
        await lamlet.add_to_instruction_buffer(
            kinstructions.VArithVxOp(
                op=VArithOp.ADD, dst=temp_idx,
                scalar_bytes=stride_bytes, src2=temp_id,
                mask_reg=None, n_elements=elements_in_vline,
                element_width=accum_ew, word_order=word_order,
                instr_ident=instr_ident,
                vta=lamlet.vta, vma=lamlet.vma,
            ), parent_span_id)

        # vrgather (masked): dst_reg = src_reg[temp_idx] where temp_mask
        await lamlet.vrgather(
            vd=data_regs[dst_idx], vs2=data_regs[src_idx], vs1=temp_idx,
            start_index=0, n_elements=elements_in_vline,
            index_ew=accum_ew, data_ew=accum_ew,
            word_order=word_order, vlmax=elements_in_vline,
            mask_reg=temp_mask, parent_span_id=parent_span_id)

        # VArithVvOp combine: dst_reg = src_reg <op> dst_reg, masked
        instr_ident = await lamlet.get_instr_ident()
        await lamlet.add_to_instruction_buffer(
            kinstructions.VArithVvOp(
                op=combine_op, dst=data_regs[dst_idx],
                src1=data_regs[src_idx], src2=data_regs[dst_idx],
                mask_reg=temp_mask, n_elements=elements_in_vline,
                element_width=accum_ew, word_order=word_order,
                instr_ident=instr_ident,
                vta=lamlet.vta, vma=lamlet.vma,
            ), parent_span_id)

        stride *= 2
        src_idx = dst_idx

    return src_idx


async def handle_vreduction_instr(lamlet, op, dst, src_vector, src_scalar_reg,
                                  mask_reg, n_elements, src_ew, accum_ew,
                                  word_order, vlmax, parent_span_id):
    """Handle vector reduction instruction via tree reduction."""
    combine_op = _VREDOP_TO_ARITHOP[op]
    lmul = lamlet.lmul
    elements_in_vline = lamlet.params.vline_bytes * 8 // accum_ew

    await lamlet.await_vreg_write_pending(src_vector, lamlet.emul_for_eew(src_ew))
    if mask_reg is not None:
        await lamlet.await_vreg_write_pending(mask_reg, 1)

    if lmul > 1:
        # Phase 1: Copy vs2 into lmul temp registers with identity/mask handling
        all_temps = lamlet.alloc_temp_regs(8)
        accum_ordering = addresses.Ordering(word_order, accum_ew)
        mask_ordering = addresses.Ordering(word_order, 1)
        for reg in all_temps:
            await lamlet.await_vreg_write_pending(reg, 1)
            lamlet.vrf_ordering[reg] = accum_ordering

        vline_regs = await _emit_lmul_setup(
            lamlet, op, src_vector, mask_reg, n_elements,
            src_ew, accum_ew, word_order,
            elements_in_vline, lmul, all_temps, parent_span_id)

        # Phase 2: Reduce lmul vlines to 1 in-place
        await _emit_lmul_tree(
            lamlet, combine_op, accum_ew, word_order,
            elements_in_vline, vline_regs, parent_span_id)

        # Result is in all_temps[0]. Reuse remaining temps for phase 3 to avoid
        # freeing and re-allocating (which could assign the same register number
        # to temp_id, causing VidOp to overwrite the reduction result).
        reduced_reg = all_temps[0]
        remaining = all_temps[1:]
        assert len(remaining) >= 7, f"Need 7 temps for cross-jamlet, have {len(remaining)}"
        temp_id, temp_idx, temp_mask = remaining[0], remaining[1], remaining[2]
        data_regs = remaining[3:7]
        await lamlet.await_vreg_write_pending(temp_mask, 1)
        lamlet.vrf_ordering[temp_mask] = mask_ordering

        # Phase 3: Cross-jamlet tree on the single vline
        src_idx = await _emit_cross_jamlet_tree(
            lamlet, combine_op, accum_ew, word_order,
            elements_in_vline, reduced_reg,
            temp_id, temp_idx, temp_mask, data_regs,
            parent_span_id)
        temp_regs = all_temps
    else:
        # lmul=1: allocate 7 temps and do setup + cross-jamlet tree directly
        temp_regs = lamlet.alloc_temp_regs(7)
        temp_id, temp_idx, temp_mask = temp_regs[0], temp_regs[1], temp_regs[2]
        data_regs = temp_regs[3:7]

        accum_ordering = addresses.Ordering(word_order, accum_ew)
        mask_ordering = addresses.Ordering(word_order, 1)
        for reg in [temp_id, temp_idx] + list(data_regs):
            await lamlet.await_vreg_write_pending(reg, 1)
            lamlet.vrf_ordering[reg] = accum_ordering
        await lamlet.await_vreg_write_pending(temp_mask, 1)
        lamlet.vrf_ordering[temp_mask] = mask_ordering

        # Setup: broadcast identity into data_regs[0], masked copy vs2 over it
        identity = _identity(op, accum_ew)
        instr_ident = await lamlet.get_instr_ident()
        await lamlet.add_to_instruction_buffer(
            kinstructions.VBroadcastOp(
                dst=data_regs[0], scalar=identity,
                n_elements=elements_in_vline,
                element_width=accum_ew, word_order=word_order,
                instr_ident=instr_ident,
                vta=lamlet.vta, vma=lamlet.vma,
            ), parent_span_id)

        widening = src_ew != accum_ew
        if widening:
            widen_op = VUnaryOp.ZEXT if op == VRedOp.WSUMU else VUnaryOp.SEXT
            instr_ident = await lamlet.get_instr_ident()
            await lamlet.add_to_instruction_buffer(
                kinstructions.VUnaryOvOp(
                    op=widen_op, dst=data_regs[1], src=src_vector,
                    n_elements=n_elements, dst_ew=accum_ew, src_ew=src_ew,
                    word_order=word_order, mask_reg=mask_reg,
                    instr_ident=instr_ident,
                    vta=lamlet.vta, vma=lamlet.vma,
                ), parent_span_id)
            src_for_copy = data_regs[1]
        else:
            src_for_copy = src_vector

        scalar_zero = (0).to_bytes(
            accum_ew // 8, byteorder='little', signed=False)
        instr_ident = await lamlet.get_instr_ident()
        await lamlet.add_to_instruction_buffer(
            kinstructions.VArithVxOp(
                op=VArithOp.ADD, dst=data_regs[0],
                scalar_bytes=scalar_zero, src2=src_for_copy,
                mask_reg=mask_reg, n_elements=n_elements,
                element_width=accum_ew, word_order=word_order,
                instr_ident=instr_ident,
                vta=lamlet.vta, vma=lamlet.vma,
            ), parent_span_id)

        # Cross-jamlet tree
        src_idx = await _emit_cross_jamlet_tree(
            lamlet, combine_op, accum_ew, word_order,
            elements_in_vline, data_regs[0],
            temp_id, temp_idx, temp_mask, data_regs,
            parent_span_id)

    # Finalize: vd[0] = last_result[0] <op> vs1[0], or just last_result[0] when
    # src_scalar_reg is None (caller has no vs1 accumulator — e.g. vcpop.m).
    instr_ident = await lamlet.get_instr_ident()
    if src_scalar_reg is None:
        scalar_zero = (0).to_bytes(
            accum_ew // 8, byteorder='little', signed=False)
        await lamlet.add_to_instruction_buffer(
            kinstructions.VArithVxOp(
                op=VArithOp.ADD, dst=dst,
                scalar_bytes=scalar_zero, src2=data_regs[src_idx],
                mask_reg=None, n_elements=1,
                element_width=accum_ew, word_order=word_order,
                instr_ident=instr_ident,
                vta=lamlet.vta, vma=lamlet.vma,
            ), parent_span_id)
    else:
        await lamlet.add_to_instruction_buffer(
            kinstructions.VArithVvOp(
                op=combine_op, dst=dst, src1=data_regs[src_idx],
                src2=src_scalar_reg, mask_reg=None, n_elements=1,
                element_width=accum_ew, word_order=word_order,
                instr_ident=instr_ident,
                vta=lamlet.vta, vma=lamlet.vma,
            ), parent_span_id)

    await lamlet.free_temp_regs(temp_regs, parent_span_id)
