"""
Focused tests for the width-asymmetric vector arith classes
(VArithVvOv / VArithVxOv) and the migrated narrowing-shift path.

Covers widening multiply (unsigned, signed, mixed-signedness), widening MAC
(accumulator read path), a narrowing right shift, and a widening float
multiply.
"""

import asyncio
import logging
import struct
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.addresses import GlobalAddress, MemoryType, Ordering
from zamlet.geometries import get_geometry
from zamlet.kamlet.kinstructions import VArithOp
from zamlet.instructions.vector import VArithVvOv, VArithVxOv, OvShape
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, unpack_elements, dump_span_trees,
)

logger = logging.getLogger(__name__)


def _int_to_signed(value: int, ew: int) -> int:
    mask = (1 << ew) - 1
    value &= mask
    if value & (1 << (ew - 1)):
        value -= 1 << ew
    return value


def _unpack_int(b: bytes, ew: int, signed: bool) -> int:
    fmt_u = {8: '<B', 16: '<H', 32: '<I', 64: '<Q'}[ew]
    fmt_s = {8: '<b', 16: '<h', 32: '<i', 64: '<q'}[ew]
    return struct.unpack(fmt_s if signed else fmt_u, b)[0]


def _pack_float(values, ew: int) -> bytes:
    fmt = {16: 'e', 32: 'f', 64: 'd'}[ew]
    return struct.pack(f'<{len(values)}{fmt}', *values)


def _unpack_float(data: bytes, ew: int) -> list:
    fmt = {16: 'e', 32: 'f', 64: 'd'}[ew]
    n = len(data) * 8 // ew
    return list(struct.unpack(f'<{n}{fmt}', data))


def _ov_widths(shape: OvShape, sew: int) -> tuple:
    if shape is OvShape.BASE:
        return sew, sew, sew * 2
    if shape is OvShape.WIDE:
        return sew, sew * 2, sew * 2
    if shape is OvShape.NARROW:
        return sew, sew * 2, sew
    raise ValueError(shape)


def _ref_int(op: VArithOp, s1: int, s2: int, acc, dst_ew: int,
             dst_signed: bool, shift_ew: int) -> int:
    """Python reference for the integer ops we test here."""
    if op is VArithOp.MUL:
        result = s1 * s2
    elif op is VArithOp.ADD:
        result = s1 + s2
    elif op is VArithOp.MACC:
        result = s1 * s2 + acc
    elif op is VArithOp.SRL:
        # s2 is the (unsigned) wide source, s1 is the shift count.
        shift = s1 & (shift_ew - 1)
        result = s2 >> shift
    else:
        raise NotImplementedError(op)

    mask = (1 << dst_ew) - 1
    result &= mask
    if dst_signed and result & (1 << (dst_ew - 1)):
        result -= 1 << dst_ew
    return result


def _make_int_inputs(ew: int, signed: bool, vl: int, rnd: Random) -> list:
    """Random integer inputs in the appropriate signed/unsigned range."""
    if signed:
        lo = -(1 << (ew - 1))
        hi = (1 << (ew - 1)) - 1
        return [rnd.randint(lo, hi) for _ in range(vl)]
    return [rnd.randint(0, (1 << ew) - 1) for _ in range(vl)]


def _alloc_vpu(lamlet, addr: int, size: int):
    page_bytes = lamlet.params.page_bytes
    aligned = ((size + page_bytes - 1) // page_bytes) * page_bytes
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=addr * 8, params=lamlet.params),
        max(aligned, page_bytes), memory_type=MemoryType.VPU)


async def _run_vv(
    lamlet, op: VArithOp, shape: OvShape, sew: int, vl: int,
    src1_signed: bool, src2_signed: bool, is_float: bool,
    mnemonic: str, rnd: Random,
) -> int:
    """Drive a VArithVvOv test and return 0 on pass, 1 on fail."""
    src1_ew, src2_ew, dst_ew = _ov_widths(shape, sew)

    # Generate inputs.
    if is_float:
        # Small ranges to avoid subnormals/overflow surprises.
        s1 = [rnd.uniform(-8.0, 8.0) for _ in range(vl)]
        s2 = [rnd.uniform(-8.0, 8.0) for _ in range(vl)]
        s1_bytes = _pack_float(s1, src1_ew)
        s2_bytes = _pack_float(s2, src2_ew)
    else:
        s1 = _make_int_inputs(src1_ew, src1_signed, vl, rnd)
        s2 = _make_int_inputs(src2_ew, src2_signed, vl, rnd)
        s1_bytes = pack_elements(s1, src1_ew)
        s2_bytes = pack_elements(s2, src2_ew)

    # Initial accumulator value in vd (only meaningful for ACCUM ops).
    is_accum = op is VArithOp.MACC
    if is_accum:
        if is_float:
            acc = [rnd.uniform(-8.0, 8.0) for _ in range(vl)]
            acc_bytes = _pack_float(acc, dst_ew)
        else:
            # Destination signedness for MUL/MACC with both signed srcs is signed.
            dst_signed = not (not src1_signed and not src2_signed)
            acc = _make_int_inputs(dst_ew, dst_signed, vl, rnd)
            acc_bytes = pack_elements(acc, dst_ew)
    else:
        acc = [0] * vl
        acc_bytes = None

    # Memory layout.
    page_bytes = lamlet.params.page_bytes
    vs1_addr = 0x90000000
    vs2_addr = vs1_addr + max(page_bytes, 4096)
    vd_addr = vs2_addr + max(page_bytes, 4096)
    _alloc_vpu(lamlet, vs1_addr, len(s1_bytes))
    _alloc_vpu(lamlet, vs2_addr, len(s2_bytes))
    # Allocate dst — we'll write an accumulator seed here (if accum) or just
    # reserve space for the store.
    dst_alloc = max(page_bytes, vl * dst_ew // 8)
    _alloc_vpu(lamlet, vd_addr, dst_alloc)

    vs1_ord = Ordering(lamlet.word_order, src1_ew)
    vs2_ord = Ordering(lamlet.word_order, src2_ew)
    vd_ord = Ordering(lamlet.word_order, dst_ew)

    await lamlet.set_memory(vs1_addr, s1_bytes, ordering=vs1_ord)
    await lamlet.set_memory(vs2_addr, s2_bytes, ordering=vs2_ord)
    if acc_bytes is not None:
        await lamlet.set_memory(vd_addr, acc_bytes, ordering=vd_ord)

    # Set vtype: vsew per SEW, lmul=1.
    vsew = {8: 0, 16: 1, 32: 2, 64: 3}[sew]
    lamlet.vtype = vsew << 3

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic=f'test_{mnemonic}')

    # Register layout — leave headroom so WIDE/NARROW all work.
    vs1_reg = 2
    vs2_reg = 4
    vd_reg = 8

    # Load vs1, vs2, and (if accum) the vd seed. The vload call sets emul
    # based on the ordering width relative to vline bytes.
    src1_emul = max(1, (vl * src1_ew + lamlet.params.vline_bytes * 8 - 1)
                    // (lamlet.params.vline_bytes * 8))
    src2_emul = max(1, (vl * src2_ew + lamlet.params.vline_bytes * 8 - 1)
                    // (lamlet.params.vline_bytes * 8))
    dst_emul = max(1, (vl * dst_ew + lamlet.params.vline_bytes * 8 - 1)
                   // (lamlet.params.vline_bytes * 8))

    lamlet.vl = vl
    await lamlet.vload(
        vd=vs1_reg, addr=vs1_addr, ordering=vs1_ord,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=src1_emul)
    await lamlet.vload(
        vd=vs2_reg, addr=vs2_addr, ordering=vs2_ord,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=src2_emul)
    if is_accum:
        await lamlet.vload(
            vd=vd_reg, addr=vd_addr, ordering=vd_ord,
            n_elements=vl, start_index=0, mask_reg=None,
            parent_span_id=span_id, emul=dst_emul)

    # Run the widening/narrowing arith instruction.
    lamlet.vl = vl
    lamlet.pc = 0
    instr = VArithVvOv(
        vd=vd_reg, vs1=vs1_reg, vs2=vs2_reg, vm=1,
        op=op, shape=shape,
        src1_signed=src1_signed, src2_signed=src2_signed,
        mnemonic=mnemonic,
    )
    await instr.update_state(lamlet)

    # Store vd back.
    await lamlet.vstore(
        vs=vd_reg, addr=vd_addr, ordering=vd_ord,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=dst_emul)

    lamlet.monitor.finalize_children(span_id)

    # Verify.
    dst_bytes_len = vl * dst_ew // 8
    result_bytes = await lamlet.get_memory_blocking(vd_addr, dst_bytes_len)

    if is_float:
        actual = _unpack_float(result_bytes, dst_ew)
        expected = [s1[i] * s2[i] for i in range(vl)]
        tol = 1e-6 * max(1.0, max(abs(v) for v in expected + [1.0]))
        ok = all(abs(actual[i] - expected[i]) <= tol for i in range(vl))
    else:
        dst_signed = not (not src1_signed and not src2_signed)
        actual = [_unpack_int(result_bytes[i * (dst_ew // 8):(i + 1) * (dst_ew // 8)],
                              dst_ew, dst_signed) for i in range(vl)]
        # Canonicalize inputs to Python ints under the right signedness.
        s1_as = s1 if src1_signed else [v & ((1 << src1_ew) - 1) for v in s1]
        s2_as = s2 if src2_signed else [v & ((1 << src2_ew) - 1) for v in s2]
        shift_ew = src2_ew if op is VArithOp.SRL else dst_ew
        expected = [
            _ref_int(op, s1_as[i], s2_as[i], acc[i], dst_ew, dst_signed, shift_ew)
            for i in range(vl)]
        ok = actual == expected

    if ok:
        logger.warning(f"PASS {mnemonic} sew={sew} vl={vl}")
        return 0
    logger.error(f"FAIL {mnemonic} sew={sew} vl={vl}")
    logger.error(f"  s1={s1}")
    logger.error(f"  s2={s2}")
    if is_accum:
        logger.error(f"  acc={acc}")
    logger.error(f"  actual  ={actual}")
    logger.error(f"  expected={expected}")
    return 1


async def _run_vx(
    lamlet, op: VArithOp, shape: OvShape, sew: int, vl: int,
    scalar_signed: bool, src2_signed: bool, is_float: bool,
    mnemonic: str, rnd: Random,
) -> int:
    """Drive a VArithVxOv (.vx form) test and return 0 on pass, 1 on fail."""
    src1_ew, src2_ew, dst_ew = _ov_widths(shape, sew)
    scalar_ew = src1_ew

    # Inputs.
    if is_float:
        scalar_val = rnd.uniform(-8.0, 8.0)
        s2 = [rnd.uniform(-8.0, 8.0) for _ in range(vl)]
        scalar_bytes8 = struct.pack('<d', scalar_val) if scalar_ew == 64 else (
            struct.pack('<f', scalar_val) + b'\x00' * 4 if scalar_ew == 32 else
            struct.pack('<e', scalar_val) + b'\x00' * 6)
        s2_bytes = _pack_float(s2, src2_ew)
    else:
        scalar_val = (rnd.randint(-(1 << (scalar_ew - 1)), (1 << (scalar_ew - 1)) - 1)
                      if scalar_signed else rnd.randint(0, (1 << scalar_ew) - 1))
        s2 = _make_int_inputs(src2_ew, src2_signed, vl, rnd)
        scalar_bytes8 = scalar_val.to_bytes(
            8, byteorder='little', signed=scalar_signed)
        s2_bytes = pack_elements(s2, src2_ew)

    page_bytes = lamlet.params.page_bytes
    vs2_addr = 0x90000000
    vd_addr = vs2_addr + max(page_bytes, 4096)
    _alloc_vpu(lamlet, vs2_addr, len(s2_bytes))
    _alloc_vpu(lamlet, vd_addr, max(page_bytes, vl * dst_ew // 8))

    vs2_ord = Ordering(lamlet.word_order, src2_ew)
    vd_ord = Ordering(lamlet.word_order, dst_ew)
    await lamlet.set_memory(vs2_addr, s2_bytes, ordering=vs2_ord)

    vsew = {8: 0, 16: 1, 32: 2, 64: 3}[sew]
    lamlet.vtype = vsew << 3

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic=f'test_{mnemonic}')

    rs1 = 5
    lamlet.scalar.write_reg(rs1, scalar_bytes8, span_id)

    vs2_reg = 4
    vd_reg = 8

    src2_emul = max(1, (vl * src2_ew + lamlet.params.vline_bytes * 8 - 1)
                    // (lamlet.params.vline_bytes * 8))
    dst_emul = max(1, (vl * dst_ew + lamlet.params.vline_bytes * 8 - 1)
                   // (lamlet.params.vline_bytes * 8))

    lamlet.vl = vl
    await lamlet.vload(
        vd=vs2_reg, addr=vs2_addr, ordering=vs2_ord,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=src2_emul)

    lamlet.vl = vl
    lamlet.pc = 0
    instr = VArithVxOv(
        vd=vd_reg, rs1=rs1, vs2=vs2_reg, vm=1,
        op=op, shape=shape,
        scalar_signed=scalar_signed, src2_signed=src2_signed,
        mnemonic=mnemonic,
    )
    await instr.update_state(lamlet)

    await lamlet.vstore(
        vs=vd_reg, addr=vd_addr, ordering=vd_ord,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=dst_emul)

    lamlet.monitor.finalize_children(span_id)

    dst_bytes_len = vl * dst_ew // 8
    result_bytes = await lamlet.get_memory_blocking(vd_addr, dst_bytes_len)

    if is_float:
        actual = _unpack_float(result_bytes, dst_ew)
        expected = [scalar_val * s2[i] for i in range(vl)]
        tol = 1e-6 * max(1.0, max(abs(v) for v in expected + [1.0]))
        ok = all(abs(actual[i] - expected[i]) <= tol for i in range(vl))
    else:
        dst_signed = not (not scalar_signed and not src2_signed)
        actual = [_unpack_int(result_bytes[i * (dst_ew // 8):(i + 1) * (dst_ew // 8)],
                              dst_ew, dst_signed) for i in range(vl)]
        s2_as = s2 if src2_signed else [v & ((1 << src2_ew) - 1) for v in s2]
        scalar_canon = scalar_val if scalar_signed else (
            scalar_val & ((1 << scalar_ew) - 1))
        shift_ew = src2_ew if op is VArithOp.SRL else dst_ew
        expected = [
            _ref_int(op, scalar_canon, s2_as[i], 0, dst_ew, dst_signed, shift_ew)
            for i in range(vl)]
        ok = actual == expected

    if ok:
        logger.warning(f"PASS {mnemonic} sew={sew} vl={vl}")
        return 0
    logger.error(f"FAIL {mnemonic} sew={sew} vl={vl}")
    logger.error(f"  scalar={scalar_val}")
    logger.error(f"  s2={s2}")
    logger.error(f"  actual  ={actual}")
    logger.error(f"  expected={expected}")
    return 1


async def _test_main(clock, params, op, shape, sew, vl,
                     src1_signed, src2_signed, is_float, mnemonic, seed):
    lamlet = await setup_lamlet(clock, params)
    rnd = Random(seed)
    try:
        return await _run_vv(
            lamlet, op, shape, sew, vl,
            src1_signed, src2_signed, is_float, mnemonic, rnd)
    except Exception:
        dump_span_trees(lamlet.monitor)
        raise


def _run(op, shape, sew, vl, src1_signed, src2_signed, is_float, mnemonic,
         seed=0, geometry='k2x1_j1x1'):
    params = get_geometry(geometry)
    clock = Clock(max_cycles=20000)

    async def main():
        clock.register_main()
        clock.create_task(clock.clock_driver())
        rc = await _test_main(
            clock, params, op, shape, sew, vl,
            src1_signed, src2_signed, is_float, mnemonic, seed)
        clock.running = False
        return rc

    rc = asyncio.run(main())
    assert rc == 0, f'{mnemonic} failed'


def test_vwmulu_vv():
    """Unsigned widening multiply (BASE shape, both unsigned)."""
    _run(VArithOp.MUL, OvShape.BASE, sew=32, vl=4,
         src1_signed=False, src2_signed=False, is_float=False,
         mnemonic='vwmulu.vv')


def test_vwmul_vv():
    """Signed widening multiply (BASE shape, both signed)."""
    _run(VArithOp.MUL, OvShape.BASE, sew=32, vl=4,
         src1_signed=True, src2_signed=True, is_float=False,
         mnemonic='vwmul.vv')


def test_vwmulsu_vv():
    """Mixed-signedness widening multiply: vs1 unsigned, vs2 signed.

    Matches decode.py funct6=0x3a: ``src1_signed=False, src2_signed=True``.
    """
    _run(VArithOp.MUL, OvShape.BASE, sew=32, vl=4,
         src1_signed=False, src2_signed=True, is_float=False,
         mnemonic='vwmulsu.vv')


def test_vwmacc_vv():
    """Widening MAC (signed): exercises the ACCUM read path at dst_ew=2*SEW."""
    _run(VArithOp.MACC, OvShape.BASE, sew=32, vl=4,
         src1_signed=True, src2_signed=True, is_float=False,
         mnemonic='vwmacc.vv')


def test_vnsrl_wv():
    """Narrowing right shift: vs2 at 2*SEW, shift count (vs1) at SEW, dst at SEW."""
    _run(VArithOp.SRL, OvShape.NARROW, sew=32, vl=4,
         src1_signed=False, src2_signed=False, is_float=False,
         mnemonic='vnsrl.wv')


def test_vfwmul_vv():
    """Widening float multiply: 32-bit floats in, 64-bit float out."""
    _run(VArithOp.FMUL, OvShape.BASE, sew=32, vl=4,
         src1_signed=False, src2_signed=False, is_float=True,
         mnemonic='vfwmul.vv')


def _run_vx_case(op, shape, sew, vl, scalar_signed, src2_signed,
                 is_float, mnemonic, seed=0, geometry='k2x1_j1x1'):
    params = get_geometry(geometry)
    clock = Clock(max_cycles=20000)

    async def main():
        clock.register_main()
        clock.create_task(clock.clock_driver())
        lamlet = await setup_lamlet(clock, params)
        rnd = Random(seed)
        try:
            rc = await _run_vx(
                lamlet, op, shape, sew, vl,
                scalar_signed, src2_signed, is_float, mnemonic, rnd)
        except Exception:
            dump_span_trees(lamlet.monitor)
            raise
        clock.running = False
        return rc

    rc = asyncio.run(main())
    assert rc == 0, f'{mnemonic} failed'


def test_vwmulu_vx():
    """Unsigned widening multiply (scalar form).

    Matches the shape the FFT kernel hits: ``vwmulu.vx`` scales 32-bit
    indices by 8 to produce 64-bit byte offsets.
    """
    _run_vx_case(VArithOp.MUL, OvShape.BASE, sew=32, vl=4,
                 scalar_signed=False, src2_signed=False, is_float=False,
                 mnemonic='vwmulu.vx')


