"""
Test vslideup / vslidedown / vslide1up / vslide1down / vfslide1up /
vfslide1down instructions.

Drives each variant through the RISC-V instruction class's update_state
(Vslide for vslideup/vslidedown.{vx,vi}; Vslide1 for both vslide1*.vx and
vfslide1*.vf, dispatched on the is_float flag) so the decode-layer plumbing
(scalar read from reg or freg, ordering set, WriteRegElement injection for
slide1 kinds) is exercised end-to-end.

- slideup:     vd[i] = vs2[i - offset], prestart (i < offset) preserved.
- slidedown:   vd[i] = vs2[i + offset], 0 when i + offset >= vlmax.
- slide1up:    vd[0]    = x[rs1], vd[i+1] = vs2[i] for 0 <= i < vl-1.
- slide1down:  vd[vl-1] = x[rs1], vd[i]   = vs2[i+1] for 0 <= i < vl-1
               (vs2[vl] wraps to 0 if vl == vlmax).
"""

import asyncio
import logging
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.addresses import GlobalAddress, MemoryType, Ordering
from zamlet.geometries import SMALL_GEOMETRIES, scale_n_tests
from zamlet.monitor import CompletionType, SpanType
from zamlet.instructions.vector import Vslide, Vslide1
from zamlet.transactions.reg_slide import SlideDirection
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, unpack_elements, dump_span_trees,
    setup_mask_register,
)

logger = logging.getLogger(__name__)


# Instruction variants under test. Each drives a different dispatch path:
# - 'vx':       Vslide(is_imm=False), offset from scalar reg.
# - 'vi':       Vslide(is_imm=True),  offset as 5-bit immediate (<=31).
# - 'slide1':   Vslide1(is_float=False), scalar from x[rs1].
# - 'slide1_f': Vslide1(is_float=True),  scalar from f[rs1] (vfslide1*.vf).
# Masking is an orthogonal axis: vm=0 routes v0 through the bulk slide
# (RegSlide mask check) and — for slide1 kinds — also gates the boundary-lane
# WriteRegElement inject.
KINDS = ('vx', 'vi', 'slide1', 'slide1_f')


async def run_reg_slide_test(
    clock: Clock,
    kind: str,
    direction: SlideDirection,
    data_ew: int,
    vl: int,
    offset: int,
    masked: bool,
    params: ZamletParams,
    seed: int,
    dump_spans: bool = False,
):
    lamlet = await setup_lamlet(clock, params)
    try:
        return await _run_reg_slide_inner(
            lamlet, kind, direction, data_ew, vl, offset, masked, params, seed)
    finally:
        if dump_spans:
            dump_span_trees(lamlet.monitor)


def _compute_expected(kind: str, direction: SlideDirection, src_data, init_vd,
                      vl: int, vlmax: int, offset: int, scalar_val: int,
                      mask_bits):
    """Spec-accurate reference: return the expected [0..vl) body of vd.

    Tail (>= vl) is left undisturbed under vta=False, so the caller only
    needs to check the body — this function returns only that slice.
    `mask_bits` is a list of bool (one per element, indexed by destination
    lane). Pass None for unmasked (all lanes active).
    """
    expected = list(init_vd[:vl])
    active = (lambda i: True) if mask_bits is None else (lambda i: mask_bits[i])

    if kind in ('slide1', 'slide1_f'):
        eff_offset = 1
    else:
        eff_offset = offset

    if direction == SlideDirection.UP:
        body_start = max(0, eff_offset)
    else:
        body_start = 0

    for i in range(body_start, vl):
        if not active(i):
            continue
        if direction == SlideDirection.UP:
            src_idx = i - eff_offset
            expected[i] = src_data[src_idx]
        else:
            src_idx = i + eff_offset
            expected[i] = src_data[src_idx] if src_idx < vlmax else 0

    # slide1 boundary-lane scalar overwrite (vstart==0). The inject is also
    # gated by the mask bit at the boundary lane.
    if kind in ('slide1', 'slide1_f') and vl >= 1:
        boundary = 0 if direction == SlideDirection.UP else vl - 1
        if active(boundary):
            expected[boundary] = scalar_val

    return expected


async def _run_reg_slide_inner(
    lamlet,
    kind: str,
    direction: SlideDirection,
    data_ew: int,
    vl: int,
    offset: int,
    masked: bool,
    params: ZamletParams,
    seed: int,
):
    rnd = Random(seed)
    data_bytes = data_ew // 8
    data_mask = (1 << data_ew) - 1

    logger.info(
        f"Test: kind={kind} direction={direction.value} data_ew={data_ew} "
        f"vl={vl} offset={offset} masked={masked} seed={seed}")

    data_base_addr = 0x90000000
    page_bytes = params.page_bytes
    ordering = Ordering(lamlet.word_order, data_ew)

    for i in range(6):
        page_addr = data_base_addr + i * page_bytes
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=page_addr * 8, params=params),
            page_bytes, memory_type=MemoryType.VPU)

    elements_in_vline = params.vline_bytes * 8 // data_ew
    vlmax = elements_in_vline  # LMUL=1

    src_data = [rnd.getrandbits(data_ew) for _ in range(vlmax)]
    init_vd = [rnd.getrandbits(data_ew) | 0x1 for _ in range(vlmax)]
    for i in range(vlmax):
        if init_vd[i] == src_data[i]:
            init_vd[i] ^= 0x1

    # Scalar injected at the boundary lane for slide1; unused otherwise but
    # still loaded into rs1 for vx-form offset.
    scalar_val = rnd.getrandbits(data_ew)
    while scalar_val in (0,) or scalar_val in src_data:
        scalar_val = rnd.getrandbits(data_ew)

    src_mem_addr = data_base_addr
    init_mem_addr = data_base_addr + 2 * page_bytes
    dst_mem_addr = data_base_addr + 4 * page_bytes

    await lamlet.set_memory(
        src_mem_addr, pack_elements(src_data, data_ew), ordering=ordering)
    await lamlet.set_memory(
        init_mem_addr, pack_elements(init_vd, data_ew), ordering=ordering)

    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x8, 32: 0x10, 64: 0x18}[data_ew]
    lamlet.vstart = 0
    lamlet.pc = 0

    # v0 is reserved for the mask register, so put vs2 elsewhere.
    vs2_reg = 1
    vd_reg = 4
    rs1_reg = 5
    mask_reg = 0

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_reg_slide")

    await lamlet.vload(
        vd=vs2_reg, addr=src_mem_addr, ordering=ordering, n_elements=vlmax,
        mask_reg=None, start_index=0, parent_span_id=span_id, emul=1)
    await lamlet.vload(
        vd=vd_reg, addr=init_mem_addr, ordering=ordering, n_elements=vlmax,
        mask_reg=None, start_index=0, parent_span_id=span_id, emul=1)

    # Set up the v0 mask when masked. Bit i gates destination lane i.
    mask_bits = None
    if masked:
        mask_bits = [bool(rnd.getrandbits(1)) for _ in range(vlmax)]
        # Keep at least one bit set and at least one clear so the test
        # meaningfully exercises both masked-in and masked-out lanes.
        if all(mask_bits):
            mask_bits[rnd.randrange(vlmax)] = False
        if not any(mask_bits):
            mask_bits[rnd.randrange(vlmax)] = True
        mask_mem_addr = data_base_addr + 6 * page_bytes
        await setup_mask_register(lamlet, mask_reg, mask_bits, page_bytes,
                                  mask_mem_addr)

    vm = 0 if masked else 1

    # For vx-form, rs1 carries the offset; for slide1/slide1_f, rs1 carries
    # the scalar (integer register for slide1, FP register for slide1_f).
    if kind == 'vx':
        rs1_val = offset
    elif kind in ('slide1', 'slide1_f'):
        rs1_val = scalar_val
    else:
        rs1_val = 0

    rs1_bytes = rs1_val.to_bytes(8, byteorder='little', signed=False)
    if kind == 'slide1_f':
        lamlet.scalar.write_freg(rs1_reg, rs1_bytes, span_id)
    else:
        lamlet.scalar.write_reg(rs1_reg, rs1_bytes, span_id)

    # Dispatch via the instruction class under test.
    if kind == 'vx':
        instr = Vslide(vd=vd_reg, vs2=vs2_reg, offset_src=rs1_reg,
                       is_imm=False, vm=vm, direction=direction)
    elif kind == 'vi':
        instr = Vslide(vd=vd_reg, vs2=vs2_reg, offset_src=offset,
                       is_imm=True, vm=vm, direction=direction)
    else:  # slide1 or slide1_f
        instr = Vslide1(vd=vd_reg, vs2=vs2_reg, rs1=rs1_reg, vm=vm,
                        direction=direction,
                        is_float=(kind == 'slide1_f'))

    await instr.update_state(lamlet)

    await lamlet.vstore(
        vs=vd_reg, addr=dst_mem_addr, ordering=ordering, n_elements=vlmax,
        start_index=0, mask_reg=None, parent_span_id=span_id)

    # The scalar we injected is sign-extended/truncated to data_ew on the
    # hardware path (WriteRegElement packs with signed=True into eb bytes).
    effective_scalar = scalar_val & data_mask

    expected = _compute_expected(
        kind, direction, src_data, init_vd, vl, vlmax, offset, effective_scalar,
        mask_bits)

    errors = []
    for i in range(vl):
        addr = dst_mem_addr + i * data_bytes
        future = await lamlet.get_memory(addr, data_bytes)
        await future
        actual = unpack_elements(future.result(), data_ew)[0]
        if actual != expected[i]:
            errors.append(f"  [{i}] expected={expected[i]:#x} actual={actual:#x}")

    if errors:
        logger.error(f"FAIL: {len(errors)} elements in body differ")
        for err in errors[:16]:
            logger.error(err)
        if len(errors) > 16:
            logger.error(f"  ... and {len(errors) - 16} more")
        return 1

    logger.info(f"PASS: {vl} elements correct")
    lamlet.monitor.finalize_children(span_id)
    return 0


async def main(clock, kind, direction, data_ew, vl, offset, masked, params,
               seed, dump_spans=False):
    clock.register_main()
    clock.create_task(clock.clock_driver())
    exit_code = await run_reg_slide_test(
        clock, kind=kind, direction=direction, data_ew=data_ew, vl=vl,
        offset=offset, masked=masked, params=params, seed=seed,
        dump_spans=dump_spans)
    clock.running = False
    return exit_code


def run_test(kind: str, direction: SlideDirection, data_ew: int, vl: int,
             offset: int, masked: bool, params: ZamletParams, seed: int,
             dump_spans: bool = False):
    clock = Clock(max_cycles=50000)
    exit_code = asyncio.run(main(
        clock, kind=kind, direction=direction, data_ew=data_ew, vl=vl,
        offset=offset, masked=masked, params=params, seed=seed,
        dump_spans=dump_spans))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def generate_test_params(n_tests: int = 32, seed: int = 42):
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name = rnd.choice(list(SMALL_GEOMETRIES.keys()))
        geom_params = SMALL_GEOMETRIES[geom_name]
        data_ew = rnd.choice([8, 16, 32, 64])
        max_vl = geom_params.vline_bytes * 8 // data_ew
        vl = rnd.randint(1, max_vl)
        direction = rnd.choice([SlideDirection.UP, SlideDirection.DOWN])
        kind = rnd.choice(KINDS)
        masked = bool(rnd.getrandbits(1))
        if kind in ('slide1', 'slide1_f'):
            offset = 1
        else:
            offset_pool = [0, 1, vl // 2, vl - 1, vl, max_vl - 1]
            offset = max(0, rnd.choice(offset_pool))
            if kind == 'vi':
                offset &= 0x1f  # uimm5
        dir_tag = 'up' if direction == SlideDirection.UP else 'dn'
        m_tag = 'm' if masked else 'u'
        id_str = (f"{i}_{geom_name}_{kind}_{dir_tag}_ew{data_ew}"
                  f"_vl{vl}_off{offset}_{m_tag}")
        test_params.append(pytest.param(
            geom_params, kind, direction, data_ew, vl, offset, masked, i,
            id=id_str))
    return test_params


@pytest.mark.parametrize(
    "params,kind,direction,data_ew,vl,offset,masked,seed",
    generate_test_params(n_tests=scale_n_tests(48)))
def test_reg_slide(params, kind, direction, data_ew, vl, offset, masked, seed):
    run_test(kind=kind, direction=direction, data_ew=data_ew, vl=vl,
             offset=offset, masked=masked, params=params, seed=seed)


if __name__ == '__main__':
    import sys
    import argparse

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(
        description='Test vslide{up,down}.{vx,vi} / vslide1{up,down}.vx')
    parser.add_argument('--kind', choices=list(KINDS), default='vx')
    parser.add_argument('--direction', choices=['up', 'down'], default='up')
    parser.add_argument('--data-ew', type=int, default=32)
    parser.add_argument('--vl', type=int, default=8)
    parser.add_argument('--offset', type=int, default=2)
    parser.add_argument('--masked', action='store_true')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--geometry', '-g', default='k2x2_j1x2')
    parser.add_argument('--list-geometries', action='store_true')
    parser.add_argument('--dump-spans', action='store_true')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    direction = SlideDirection.UP if args.direction == 'up' else SlideDirection.DOWN
    params = get_geometry(args.geometry)
    run_test(kind=args.kind, direction=direction, data_ew=args.data_ew,
             vl=args.vl, offset=args.offset, masked=args.masked,
             params=params, seed=args.seed, dump_spans=args.dump_spans)
