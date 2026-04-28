"""
Tests for vector floating-point compare and classify kinstrs.

Covers the C4 chunk of PLAN_rvv_coverage.md:
  * vmfeq.vv/.vf, vmfne.vv/.vf, vmflt.vv/.vf, vmfle.vv/.vf — VCmpVvFloat /
    VCmpVxFloat producing a 1-bit-per-element mask.
  * vmfgt.vf, vmfge.vf — .vf only (the .vv forms are pseudoinstructions
    that swap operands of vmflt.vv / vmfle.vv).
  * vfclass.v — VUnary with VUnaryOp.FCLASS, dst element holds the 10-bit
    classification mask in the low bits (upper bits zero, defined for
    SEW >= 16).
"""

import asyncio
import logging
import struct
from enum import Enum
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.addresses import GlobalAddress, MemoryType, Ordering
from zamlet.geometries import get_geometry
from zamlet.kamlet.kinstructions import VCmpOp, VUnaryOp
from zamlet.instructions.vector import VCmpVvFloat, VCmpVxFloat, VUnary
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests.test_utils import setup_lamlet, dump_span_trees

logger = logging.getLogger(__name__)


class FCmpForm(Enum):
    """Operand form for FP compare. VV: vector-vector. VF: vector-scalar."""
    VV = 'vv'
    VF = 'vf'


# ----------------------------------------------------------------------------
# Pack / unpack helpers (see test_arith.py for the integer-side equivalents).
# ----------------------------------------------------------------------------

def _pack_float(values, ew: int) -> bytes:
    fmt = {16: 'e', 32: 'f', 64: 'd'}[ew]
    return struct.pack(f'<{len(values)}{fmt}', *values)


def _pack_scalar_float(val: float, ew: int) -> bytes:
    """Pack a single float into the 8-byte scalar register format."""
    fmt = {16: 'e', 32: 'f', 64: 'd'}[ew]
    raw = struct.pack(f'<{fmt}', val)
    return raw + b'\x00' * (8 - len(raw))


def _unpack_uint_vec(data: bytes, ew: int, vl: int) -> list:
    fmt = {8: '<B', 16: '<H', 32: '<I', 64: '<Q'}[ew]
    bw = ew // 8
    return [struct.unpack(fmt, data[i * bw:(i + 1) * bw])[0] for i in range(vl)]


def _decode_mask_bytes(byts: bytes, j_in_l: int, wb: int, vl: int) -> list:
    """Inverse of mask_bits_to_ew64_bytes for the first vline of mask data."""
    bits = [False] * vl
    for jamlet_idx in range(j_in_l):
        chunk = byts[jamlet_idx * wb:(jamlet_idx + 1) * wb]
        for byte_idx, b in enumerate(chunk):
            for bit_idx in range(8):
                element_idx = jamlet_idx + (byte_idx * 8 + bit_idx) * j_in_l
                if element_idx < vl:
                    bits[element_idx] = bool((b >> bit_idx) & 1)
    return bits


# ----------------------------------------------------------------------------
# Memory and vtype helpers
# ----------------------------------------------------------------------------

def _alloc_vpu(lamlet, addr: int, size: int):
    page_bytes = lamlet.params.page_bytes
    aligned = ((size + page_bytes - 1) // page_bytes) * page_bytes
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=addr * 8, params=lamlet.params),
        max(aligned, page_bytes), memory_type=MemoryType.VPU)


def _emul(vl: int, ew: int, vline_bits: int) -> int:
    """Vlines occupied by vl elements at ew, rounded up to the next power of
    two so it is a legal LMUL. The kinstr bounds iteration by vl, so the
    extra (unused) vline is harmless."""
    n_vlines = max(1, (vl * ew + vline_bits - 1) // vline_bits)
    lmul = 1
    while lmul < n_vlines:
        lmul *= 2
    assert lmul in (1, 2, 4, 8), f'unsupported lmul={lmul} for vl={vl} ew={ew}'
    return lmul


def _vtype_for(sew: int, vl: int, vline_bits: int) -> int:
    """Pack vsew and vlmul so the EMUL group covers vl elements at sew."""
    n_vlines = _emul(vl, sew, vline_bits)
    lmul = 1
    while lmul < n_vlines:
        lmul *= 2
    assert lmul in (1, 2, 4, 8), f'unsupported lmul={lmul} for sew={sew} vl={vl}'
    vsew = {8: 0, 16: 1, 32: 2, 64: 3}[sew]
    vlmul = {1: 0, 2: 1, 4: 2, 8: 3}[lmul]
    return (vsew << 3) | vlmul


# Register layout used by every test in this file. vs1/vs2/vd are 4-aligned so
# the same layout works for any LMUL up to 4 (RVV requires register groups to
# be aligned to LMUL). vl=11 sew=32 rounds emul up to 4 (the next legal LMUL),
# so a misaligned vs1 would alias vs2's group.
_RS1 = 5
_VS1_REG = 4
_VS2_REG = 8
_VD_REG = 12


# ----------------------------------------------------------------------------
# FP compare (vmf{eq,ne,lt,le,gt,ge}). Mask-output, vm=1 unmasked.
# ----------------------------------------------------------------------------

# Hand-crafted FP specials (struct-packable, qNaN only — Python's float('nan')
# canonicalises to qNaN). These exercise the IEEE comparison rules: NaN is
# unordered (so eq is false, ne is true, lt/le/gt/ge are all false), ±0 are
# equal, ±inf are ordered.
_FP_SPECIALS = [
    float('nan'), float('inf'), float('-inf'), 0.0, -0.0,
    1.0, -1.0, 3.14, -3.14, 1e-30, -1e-30,
]


def _ref_fcmp(op: VCmpOp, a: float, b: float) -> bool:
    """Reference for FP compare. Python float comparison semantics already
    match RVV (NE returns True for NaN inputs; others return False)."""
    if op is VCmpOp.EQ:
        return a == b
    if op is VCmpOp.NE:
        return a != b
    if op is VCmpOp.LT:
        return a < b
    if op is VCmpOp.LE:
        return a <= b
    if op is VCmpOp.GT:
        return a > b
    if op is VCmpOp.GE:
        return a >= b
    raise NotImplementedError(op)


def _build_fcmp_inputs(form: FCmpForm, vl: int, rnd: Random):
    """Return (s2_list, other_list, scalar_bytes). Other is per-element so the
    reference and the bytes path can share the same lookup."""
    pad = max(0, vl - len(_FP_SPECIALS))
    s2 = list(_FP_SPECIALS) + [rnd.uniform(-8.0, 8.0) for _ in range(pad)]
    s2 = s2[:vl]
    rnd.shuffle(s2)
    if form is FCmpForm.VF:
        s1_scalar = (rnd.choice(_FP_SPECIALS)
                     if rnd.random() < 0.5 else rnd.uniform(-8.0, 8.0))
        return s2, [s1_scalar] * vl, s1_scalar
    s1 = list(_FP_SPECIALS) + [rnd.uniform(-8.0, 8.0) for _ in range(pad)]
    s1 = s1[:vl]
    rnd.shuffle(s1)
    return s2, s1, None


async def _run_fcmp(
    lamlet,
    *,
    op: VCmpOp,
    sew: int,
    vl: int,
    mnemonic: str,
    rnd: Random,
    form: FCmpForm,
) -> int:
    """Drive one FP compare test. Returns 0 on pass, 1 on fail."""
    is_scalar = form is FCmpForm.VF
    vline_bits = lamlet.params.vline_bytes * 8
    wb = lamlet.params.word_bytes
    j_in_l = lamlet.params.j_in_l
    page_bytes = lamlet.params.page_bytes

    s2, others, s1_scalar = _build_fcmp_inputs(form, vl, rnd)
    s2_bytes = _pack_float(s2, sew)

    base_addr = 0x90000000
    stride = max(page_bytes, 4096)
    if is_scalar:
        vs2_addr = base_addr
        scalar_bytes8 = _pack_scalar_float(s1_scalar, sew)
    else:
        vs1_addr = base_addr
        vs2_addr = vs1_addr + stride
        s1_bytes = _pack_float(others, sew)
        _alloc_vpu(lamlet, vs1_addr, len(s1_bytes))
    _alloc_vpu(lamlet, vs2_addr, len(s2_bytes))
    mask_out_addr = base_addr + 3 * stride
    _alloc_vpu(lamlet, mask_out_addr, max(page_bytes, lamlet.params.vline_bytes))

    vs2_ord = Ordering(lamlet.word_order, sew)
    if not is_scalar:
        vs1_ord = Ordering(lamlet.word_order, sew)
        await lamlet.set_memory(vs1_addr, s1_bytes, ordering=vs1_ord)
    await lamlet.set_memory(vs2_addr, s2_bytes, ordering=vs2_ord)

    lamlet.vtype = _vtype_for(sew, vl, vline_bits)

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET,
        mnemonic=f'test_{mnemonic}')

    lamlet.vl = vl
    if is_scalar:
        lamlet.scalar.write_freg(_RS1, scalar_bytes8, span_id)
    else:
        await lamlet.vload(
            vd=_VS1_REG, addr=vs1_addr, ordering=vs1_ord,
            n_elements=vl, start_index=0, mask_reg=None,
            parent_span_id=span_id, emul=_emul(vl, sew, vline_bits))
    await lamlet.vload(
        vd=_VS2_REG, addr=vs2_addr, ordering=vs2_ord,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=_emul(vl, sew, vline_bits))

    lamlet.vl = vl
    lamlet.pc = 0
    if is_scalar:
        instr = VCmpVxFloat(vd=_VD_REG, vs2=_VS2_REG, rs1=_RS1, vm=1, op=op)
    else:
        instr = VCmpVvFloat(vd=_VD_REG, vs2=_VS2_REG, vs1=_VS1_REG, vm=1, op=op)
    await instr.update_state(lamlet)

    # Read the dst mask back: retag to ew=64 and vstore one vline of bytes.
    mask_out_ord = Ordering(lamlet.word_order, 64)
    lamlet.vrf_ordering[_VD_REG] = mask_out_ord
    await lamlet.vstore(
        vs=_VD_REG, addr=mask_out_addr, ordering=mask_out_ord,
        n_elements=j_in_l, start_index=0, mask_reg=None,
        parent_span_id=span_id)

    lamlet.monitor.finalize_children(span_id)

    out_bytes = await lamlet.get_memory_blocking(mask_out_addr, j_in_l * wb)
    actual = _decode_mask_bytes(out_bytes, j_in_l, wb, vl)
    expected = [_ref_fcmp(op, s2[i], others[i]) for i in range(vl)]

    if actual == expected:
        logger.warning(f"PASS {mnemonic} sew={sew} vl={vl}")
        return 0
    logger.error(f"FAIL {mnemonic} sew={sew} vl={vl}")
    if is_scalar:
        logger.error(f"  scalar={others[0]}")
    else:
        logger.error(f"  s1={others}")
    logger.error(f"  s2={s2}")
    logger.error(f"  actual  ={actual}")
    logger.error(f"  expected={expected}")
    return 1


def _run_fcmp_test(*, op, sew, vl, mnemonic, form, seed, geometry='k2x1_j1x1'):
    params = get_geometry(geometry)
    clock = Clock(max_cycles=20000)

    async def main():
        clock.register_main()
        clock.create_task(clock.clock_driver())
        lamlet = await setup_lamlet(clock, params)
        rnd = Random(seed)
        try:
            rc = await _run_fcmp(lamlet, op=op, sew=sew, vl=vl,
                                 mnemonic=mnemonic, rnd=rnd, form=form)
        except Exception:
            dump_span_trees(lamlet.monitor)
            raise
        clock.running = False
        return rc

    rc = asyncio.run(main())
    assert rc == 0, f'{mnemonic} failed'


_FCMP_VV_OPS = [
    (VCmpOp.EQ, 'vmfeq.vv', 41),
    (VCmpOp.NE, 'vmfne.vv', 42),
    (VCmpOp.LT, 'vmflt.vv', 43),
    (VCmpOp.LE, 'vmfle.vv', 44),
]
_FCMP_VF_OPS = [
    (VCmpOp.EQ, 'vmfeq.vf', 51),
    (VCmpOp.NE, 'vmfne.vf', 52),
    (VCmpOp.LT, 'vmflt.vf', 53),
    (VCmpOp.LE, 'vmfle.vf', 54),
    (VCmpOp.GT, 'vmfgt.vf', 55),
    (VCmpOp.GE, 'vmfge.vf', 56),
]


@pytest.mark.parametrize('op,mnemonic,seed', _FCMP_VV_OPS,
                         ids=[m for _, m, _ in _FCMP_VV_OPS])
def test_fcmp_vv(op, mnemonic, seed):
    _run_fcmp_test(op=op, sew=32, vl=11, mnemonic=mnemonic,
                   form=FCmpForm.VV, seed=seed)


@pytest.mark.parametrize('op,mnemonic,seed', _FCMP_VF_OPS,
                         ids=[m for _, m, _ in _FCMP_VF_OPS])
def test_fcmp_vf(op, mnemonic, seed):
    _run_fcmp_test(op=op, sew=32, vl=11, mnemonic=mnemonic,
                   form=FCmpForm.VF, seed=seed)


# ----------------------------------------------------------------------------
# vfclass.v — unary, dst element holds the 10-bit class mask in low bits.
# Curated input vector covers every class bit position 0..9 for binary32,
# including both qNaN (frac MSB=1) and sNaN (frac MSB=0, frac != 0).
# ----------------------------------------------------------------------------

def _build_fp32(sign: int, exp: int, frac: int) -> bytes:
    val = (sign << 31) | (exp << 23) | frac
    return val.to_bytes(4, byteorder='little')


_FCLASS_FP32_CASES = [
    (_build_fp32(1, 0xff, 0),         1 << 0),  # -inf
    (_build_fp32(1, 0x80, 0),         1 << 1),  # -normal
    (_build_fp32(1, 0x00, 0x123),     1 << 2),  # -subnormal
    (_build_fp32(1, 0x00, 0),         1 << 3),  # -0
    (_build_fp32(0, 0x00, 0),         1 << 4),  # +0
    (_build_fp32(0, 0x00, 0x456),     1 << 5),  # +subnormal
    (_build_fp32(0, 0x80, 0),         1 << 6),  # +normal
    (_build_fp32(0, 0xff, 0),         1 << 7),  # +inf
    (_build_fp32(0, 0xff, 0x123456),  1 << 8),  # sNaN (frac MSB = 0)
    (_build_fp32(0, 0xff, 0x456789),  1 << 9),  # qNaN (frac MSB = 1)
]


async def _run_fclass(lamlet, *, sew: int, rnd: Random) -> int:
    """Drive vfclass.v over the curated case vector at the given sew."""
    assert sew == 32, 'curated cases are fp32; extend if needed'
    cases = list(_FCLASS_FP32_CASES)
    rnd.shuffle(cases)
    vl = len(cases)
    vline_bits = lamlet.params.vline_bytes * 8
    page_bytes = lamlet.params.page_bytes

    s2_bytes = b''.join(c[0] for c in cases)
    expected = [c[1] for c in cases]

    base_addr = 0x90000000
    stride = max(page_bytes, 4096)
    vs2_addr = base_addr
    vd_addr = vs2_addr + stride
    _alloc_vpu(lamlet, vs2_addr, len(s2_bytes))
    _alloc_vpu(lamlet, vd_addr, max(page_bytes, vl * sew // 8))

    vs2_ord = Ordering(lamlet.word_order, sew)
    vd_ord = Ordering(lamlet.word_order, sew)
    await lamlet.set_memory(vs2_addr, s2_bytes, ordering=vs2_ord)

    lamlet.vtype = _vtype_for(sew, vl, vline_bits)

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET,
        mnemonic='test_vfclass.v')

    lamlet.vl = vl
    await lamlet.vload(
        vd=_VS2_REG, addr=vs2_addr, ordering=vs2_ord,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=_emul(vl, sew, vline_bits))

    lamlet.vl = vl
    lamlet.pc = 0
    instr = VUnary(vd=_VD_REG, vs2=_VS2_REG, vm=1, op=VUnaryOp.FCLASS,
                   factor=1, widening=True, mnemonic='vfclass.v')
    await instr.update_state(lamlet)

    await lamlet.vstore(
        vs=_VD_REG, addr=vd_addr, ordering=vd_ord,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=_emul(vl, sew, vline_bits))

    lamlet.monitor.finalize_children(span_id)

    result_bytes = await lamlet.get_memory_blocking(vd_addr, vl * sew // 8)
    actual = _unpack_uint_vec(result_bytes, sew, vl)

    if actual == expected:
        logger.warning(f"PASS vfclass.v sew={sew} vl={vl}")
        return 0
    logger.error(f"FAIL vfclass.v sew={sew} vl={vl}")
    logger.error(f"  actual  ={[hex(v) for v in actual]}")
    logger.error(f"  expected={[hex(v) for v in expected]}")
    return 1


def test_vfclass_v():
    params = get_geometry('k2x1_j1x1')
    clock = Clock(max_cycles=20000)

    async def main():
        clock.register_main()
        clock.create_task(clock.clock_driver())
        lamlet = await setup_lamlet(clock, params)
        rnd = Random(61)
        try:
            rc = await _run_fclass(lamlet, sew=32, rnd=rnd)
        except Exception:
            dump_span_trees(lamlet.monitor)
            raise
        clock.running = False
        return rc

    rc = asyncio.run(main())
    assert rc == 0, 'vfclass.v failed'
