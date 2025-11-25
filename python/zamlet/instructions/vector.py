"""Vector extension instructions.

Reference: riscv-isa-manual/src/v-st-ext.adoc
"""

import logging
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from zamlet.kamlet import kinstructions
from zamlet import addresses
from zamlet.addresses import Ordering, WordOrder
from zamlet.register_names import reg_name, freg_name

logger = logging.getLogger(__name__)


@dataclass
class Vsetvli:
    """VSETVLI - Vector Set Vector Length Immediate.

    Sets vector length and vector type based on AVL (application vector length)
    from rs1 and immediate-encoded VTYPE.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    rd: int
    rs1: int
    vtypei: int

    def __str__(self):
        vlmul = (self.vtypei >> 0) & 0x7
        vsew = (self.vtypei >> 3) & 0x7
        vta = (self.vtypei >> 6) & 0x1
        vma = (self.vtypei >> 7) & 0x1

        lmul_strs = ['m1', 'm2', 'm4', 'm8', 'mf8', 'mf4', 'mf2', 'reserved']
        sew_strs = ['e8', 'e16', 'e32', 'e64', 'e128', 'e256', 'e512', 'e1024']

        lmul_str = lmul_strs[vlmul]
        sew_str = sew_strs[vsew]
        ta_str = 'ta' if vta else 'tu'
        ma_str = 'ma' if vma else 'mu'

        return f'vsetvli\t{reg_name(self.rd)},{reg_name(self.rs1)},{sew_str},{lmul_str},{ta_str},{ma_str}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        avl = int.from_bytes(rs1_bytes, byteorder='little', signed=False)

        s.vtype = self.vtypei

        vlmul = (self.vtypei >> 0) & 0x7
        vsew = (self.vtypei >> 3) & 0x7
        vta = (self.vtypei >> 6) & 0x1
        vma = (self.vtypei >> 7) & 0x1

        if vlmul <= 3:
            lmul = 1 << vlmul
        else:
            lmul = 1 / (1 << (8 - vlmul))

        sew = 8 << vsew

        vlen_bits = s.params.maxvl_bytes * 8
        vlmax = int((vlen_bits / sew) * lmul)
        logger.info(f'sew is {sew} and lmul is {lmul} vlmax is {vlmax} to avl is {avl}')

        # When both rd and rs1 are x0, keep existing vl (only update vtype).
        # Per RISC-V V spec section "AVL encoding":
        # "When rs1=x0 and rd=x0, the instructions operate as if the current
        # vector length in vl is used as the AVL"
        # Reference: riscv-isa-manual/src/v-st-ext.adoc
        if self.rd == 0 and self.rs1 == 0:
            pass  # vl stays unchanged
        elif avl <= vlmax:
            s.vl = avl
        else:
            s.vl = vlmax

        vl_bytes = s.vl.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, vl_bytes)
        logger.info(f'Set vl to {s.vl}')
        s.pc += 4


@dataclass
class VleV:
    """VLE.V - Vector Load Elements (generic for all element widths).

    Unit-stride load of elements from memory into a vector register.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    rs1: int
    vm: int
    element_width: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vle{self.element_width}.v\tv{self.vd},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'state.State'):
        logger.debug(f'{s.clock.cycle}: waiting for ready regs')
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg=None
        else:
            mask_reg=0
        logger.debug(f'{s.clock.cycle}: do load')
        logger.warning(f'{s.clock.cycle}: VLE{self.element_width}.V: vd=v{self.vd}, addr=0x{addr:x}, vl={s.vl}, masked={not self.vm}, mask_reg={mask_reg}')
    #async def vload(self, vd: int, addr: int, ordering: addresses.Ordering,
    #                n_elements: int, mask_reg: int, start_index: int):
        ordering = addresses.Ordering(s.word_order, self.element_width)
        await s.vload(self.vd, addr, ordering, s.vl, mask_reg, s.vstart)
        logger.debug(f'{s.clock.cycle}: kicked off load')
        s.pc += 4
        logger.debug(f'Loaded vector into vd={self.vd}')


@dataclass
class VseV:
    """VSE.V - Vector Store Elements (generic for all element widths).

    Unit-stride store of elements from vector register to memory.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vs3: int
    rs1: int
    vm: int
    element_width: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vse{self.element_width}.v\tv{self.vs3},({reg_name(self.rs1)}){vm_str}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        addr = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0
        logger.warning(f'{s.clock.cycle}: VSE{self.element_width}.V: vs3=v{self.vs3}, addr=0x{addr:x}, vl={s.vl}, masked={not self.vm}, mask_reg={mask_reg}')
        ordering = addresses.Ordering(s.word_order, self.element_width)
        await s.vstore(self.vs3, addr, ordering, s.vl, mask_reg, s.vstart)
        s.pc += 4
        logger.debug(f'Stored vector from vs3={self.vs3}')


@dataclass
class VArithVxFloat:
    """Generic vector-scalar floating-point arithmetic instruction.

    Used for vfmacc.vf, etc.
    """
    vd: int
    rs1: int
    vs2: int
    vm: int
    op: kinstructions.VArithOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vf{self.op.value}.vf\tv{self.vd},{freg_name(self.rs1)},v{self.vs2}{vm_str}'

    async def update_state(self, s: 'state.State'):
        logger.debug(f'{s.clock.cycle}: VArithVxFloat waiting for regs')
        await s.scalar.wait_all_regs_ready(None, None, [], [self.rs1])
        logger.debug(f'{s.clock.cycle}: VArithVxFloat got regs')

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = addresses.WordOrder.STANDARD
        assert s.vrf_ordering[self.vd].ew == element_width
        assert s.vrf_ordering[self.vs2].ew == element_width

        scalar_bytes = s.scalar.read_freg(self.rs1)

        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

        logger.debug(f'VF{self.op.value.upper()}.VF: vd=v{self.vd}, rs1={freg_name(self.rs1)}, vs2=v{self.vs2}, vl={s.vl}, ew={element_width}')

        kinstr = kinstructions.VArithVxOp(
            op=self.op,
            dst=self.vd,
            scalar_bytes=scalar_bytes,
            src2=self.vs2,
            mask_reg=mask_reg,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
            is_float=True,
        )
        await s.add_to_instruction_buffer(kinstr)
        s.pc += 4


@dataclass
class VmsleVi:
    """VMSLE.VI - Vector Mask Set Less Than or Equal Immediate.

    vd.mask[i] = (vs2[i] <= simm5) ? 1 : 0

    Note: vmslt.vi is a pseudoinstruction that maps to vmsle.vi with imm-1.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vs2: int
    simm5: int
    vm: int

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        return f'vmsle.vi\tv{self.vd},v{self.vs2},{self.simm5}{vm_str}'

    async def update_state(self, s: 'state.State'):
        logger.warning(f'{s.clock.cycle}: VMSLE.VI at PC={hex(s.pc)}: vd=v{self.vd}, vs2=v{self.vs2}, simm5={self.simm5}, vl={s.vl}')

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        # Calculate number of source registers needed
        vline_bytes = s.params.word_bytes * s.params.j_in_l
        elements_in_src_vline = vline_bytes * 8 // element_width
        n_src_vlines = (s.vl + elements_in_src_vline - 1) // elements_in_src_vline

        # Check all source registers in group have correct element width
        for i in range(n_src_vlines):
            assert s.vrf_ordering[self.vs2 + i].ew == element_width

        # Calculate number of destination mask registers needed
        elements_in_dst_vline = vline_bytes * 8  # 1 bit per element
        n_dst_vlines = (s.vl + elements_in_dst_vline - 1) // elements_in_dst_vline

        # Set ordering for destination mask register(s) - masks are 1-bit elements
        mask_ordering = Ordering(WordOrder.STANDARD, 1)
        for i in range(n_dst_vlines):
            s.vrf_ordering[self.vd + i] = mask_ordering

        kinstr = kinstructions.VmsleViOp(
            dst=self.vd,
            src=self.vs2,
            simm5=self.simm5,
            n_elements=s.vl,
            element_width=element_width,
            ordering=s.vrf_ordering[self.vs2],
        )
        await s.add_to_instruction_buffer(kinstr)
        logger.warning(f'{s.clock.cycle}: VMSLE.VI QUEUED VmsleViOp to instruction buffer')
        s.pc += 4


@dataclass
class VmnandMm:
    """VMNAND.MM - Vector Mask NAND.

    vd.mask[i] = !(vs2.mask[i] && vs1.mask[i])

    Pseudoinstruction vmnot.m vd, vs => vmnand.mm vd, vs, vs

    Note: Mask logical operations are always unmasked.

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vs2: int
    vs1: int

    def __str__(self):
        if self.vs2 == self.vs1:
            return f'vmnot.m\tv{self.vd},v{self.vs2}'
        return f'vmnand.mm\tv{self.vd},v{self.vs2},v{self.vs1}'

    async def update_state(self, s: 'state.State'):
        # Get ordering from source mask registers
        vs2_ordering = s.vrf_ordering[self.vs2]
        vs1_ordering = s.vrf_ordering[self.vs1]

        # Mask registers should have element width of 1
        assert vs2_ordering.ew == 1
        assert vs1_ordering.ew == 1

        # Set ordering for destination mask register to match source
        s.vrf_ordering[self.vd] = vs2_ordering

        kinstr = kinstructions.VmnandMmOp(
            dst=self.vd,
            src1=self.vs2,
            src2=self.vs1,
        )
        await s.add_to_instruction_buffer(kinstr)
        s.pc += 4


@dataclass
class VmvVi:
    """VMV.V.I - Vector Move Immediate.

    vd[i] = imm (splat immediate to all active elements)

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    simm5: int

    def __str__(self):
        return f'vmv.v.i\tv{self.vd},{self.simm5}'

    async def update_state(self, s: 'state.State'):
        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = addresses.WordOrder.STANDARD

        s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        sign_extended_imm = self.simm5 if self.simm5 < 16 else self.simm5 - 32

        kinstr = kinstructions.VBroadcastOp(
            dst=self.vd,
            scalar=sign_extended_imm,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
        )
        await s.add_to_instruction_buffer(kinstr)
        s.pc += 4


@dataclass
class VmvVx:
    """VMV.V.X - Vector Move Scalar Register.

    vd[i] = x[rs1] (splat scalar to all active elements)

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    rs1: int

    def __str__(self):
        return f'vmv.v.x\tv{self.vd},{reg_name(self.rs1)}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = addresses.WordOrder.STANDARD

        rs1_bytes = s.scalar.read_reg(self.rs1)
        scalar_val = int.from_bytes(rs1_bytes, byteorder='little', signed=True)

        s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        kinstr = kinstructions.VBroadcastOp(
            dst=self.vd,
            scalar=scalar_val,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
        )
        await s.add_to_instruction_buffer(kinstr)
        s.pc += 4


@dataclass
class VmvVv:
    """VMV.V.V - Vector Move Vector Register.

    vd[i] = vs1[i] (copy vector register to all active elements)

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    vd: int
    vs1: int

    def __str__(self):
        return f'vmv.v.v\tv{self.vd},v{self.vs1}'

    async def update_state(self, s: 'state.State'):
        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = addresses.WordOrder.STANDARD

        assert s.vrf_ordering[self.vs1].ew == element_width

        s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        kinstr = kinstructions.VmvVvOp(
            dst=self.vd,
            src=self.vs1,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
        )
        await s.add_to_instruction_buffer(kinstr)
        s.pc += 4


@dataclass
class VmvXs:
    """VMV.X.S - Vector Move to Scalar Register.

    x[rd] = vs2[0] (extract element 0 from vector register)

    Reference: riscv-isa-manual/src/v-st-ext.adoc
    """
    rd: int
    vs2: int

    def __str__(self):
        return f'vmv.x.s\t{reg_name(self.rd)},v{self.vs2}'

    async def update_state(self, s: 'state.State'):
        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        assert s.vrf_ordering[self.vs2].ew == element_width

        # Read element 0 from the vector register
        value_future = await s.read_register_element(self.vs2, element_index=0, element_width=element_width)
        s.scalar.write_reg_future(self.rd, value_future)
        s.pc += 4


@dataclass
class VreductionVs:
    """Generic Vector Single-Width Integer Reduction.

    vd[0] = reduce_op(vs1[0], vs2[*])
    Reduces all active elements of vs2 with element 0 of vs1 using the specified operation.

    Used for vredsum.vs, vredmax.vs, vredmin.vs, etc.

    Reference: riscv-isa-manual/src/v-st-ext.adoc Section 15.3
    """
    vd: int
    vs2: int
    vs1: int
    vm: int
    op: kinstructions.VRedOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        op_name = f'vred{self.op.value}'
        return f'{op_name}.vs\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'state.State'):
        if s.vstart != 0:
            raise ValueError(f'vred{self.op.value}.vs requires vstart == 0')

        if s.vl == 0:
            s.pc += 4
            return

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew

        if not self.vm:
            mask_reg = 0
        else:
            mask_reg = None

        assert s.vrf_ordering[self.vs2].ew == element_width
        assert s.vrf_ordering[self.vs1].ew == element_width

        word_order = addresses.WordOrder.STANDARD
        s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        await s.handle_vreduction_vs_instr(
            op=self.op,
            dst=self.vd,
            src_vector=self.vs2,
            src_scalar_reg=self.vs1,
            mask_reg=mask_reg,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
        )
        s.pc += 4


@dataclass
class VArithVv:
    """Generic vector-vector arithmetic instruction.

    Used for vmul.vv, vmacc.vv, etc.
    """
    vd: int
    vs1: int
    vs2: int
    vm: int
    op: kinstructions.VArithOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        # MACC uses vs1,vs2 order; MUL uses vs2,vs1 order
        if self.op == kinstructions.VArithOp.MACC:
            return f'v{self.op.value}.vv\tv{self.vd},v{self.vs1},v{self.vs2}{vm_str}'
        else:
            return f'v{self.op.value}.vv\tv{self.vd},v{self.vs2},v{self.vs1}{vm_str}'

    async def update_state(self, s: 'state.State'):
        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = addresses.WordOrder.STANDARD

        if self.op == kinstructions.VArithOp.MACC and self.vd not in s.vrf_ordering:
            s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        assert s.vrf_ordering[self.vs1].ew == element_width
        assert s.vrf_ordering[self.vs2].ew == element_width

        if self.op != kinstructions.VArithOp.MACC:
            s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        kinstr = kinstructions.VArithVvOp(
            op=self.op,
            dst=self.vd,
            src1=self.vs1,
            src2=self.vs2,
            mask_reg=mask_reg,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
        )
        await s.add_to_instruction_buffer(kinstr)
        s.pc += 4


@dataclass
class VArithVx:
    """Generic vector-scalar arithmetic instruction.

    Used for vmul.vx, vmacc.vx, etc.
    """
    vd: int
    rs1: int
    vs2: int
    vm: int
    op: kinstructions.VArithOp

    def __str__(self):
        vm_str = '' if self.vm else ',v0.t'
        if self.op == kinstructions.VArithOp.ADD:
            return f'v{self.op.value}.vx\tv{self.vd},v{self.vs2},{reg_name(self.rs1)}{vm_str}'
        else:
            return f'v{self.op.value}.vx\tv{self.vd},{reg_name(self.rs1)},v{self.vs2}{vm_str}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])

        if self.vm:
            mask_reg = None
        else:
            mask_reg = 0

        vsew = (s.vtype >> 3) & 0x7
        element_width = 8 << vsew
        word_order = addresses.WordOrder.STANDARD

        if self.op == kinstructions.VArithOp.MACC and self.vd not in s.vrf_ordering:
            s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        assert s.vrf_ordering[self.vs2].ew == element_width
        if self.op == kinstructions.VArithOp.MACC:
            assert s.vrf_ordering[self.vd].ew == element_width

        rs1_bytes = s.scalar.read_reg(self.rs1)

        if self.op != kinstructions.VArithOp.MACC:
            s.vrf_ordering[self.vd] = addresses.Ordering(word_order, element_width)

        kinstr = kinstructions.VArithVxOp(
            op=self.op,
            dst=self.vd,
            scalar_bytes=rs1_bytes,
            src2=self.vs2,
            mask_reg=mask_reg,
            n_elements=s.vl,
            element_width=element_width,
            word_order=word_order,
        )
        await s.add_to_instruction_buffer(kinstr)
        s.pc += 4
