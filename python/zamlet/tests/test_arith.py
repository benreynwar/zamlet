"""
Tests for vector integer arithmetic kinstr classes.

Two paths are exercised through one runner:
  * VArithVv / VArithVx — same-width single-width ALU ops (vmin/vmax/vmulh/...).
  * VArithVvOv / VArithVxOv — width-asymmetric ops (widening mul/mac, narrowing
    right shift, widening float multiply, mixed-signed high-half mul).

Pass ``shape=None`` to drive the same-width path; pass ``shape=OvShape.{...}``
to drive the Ov path.
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
from zamlet.kamlet.kinstructions import VArithOp, VCmpOp, CARRY_BORROW_OPS
from zamlet.instructions.vector import (
    VArithVv, VArithVx, VArithVi, VArithVvOv, VArithVxOv, OvShape,
    VCmpVv, VCmpVx, VCmpVi,
)
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, dump_span_trees, setup_mask_register,
)

logger = logging.getLogger(__name__)


class ArithForm(Enum):
    """Operand form for the arith runner.

    VV: vector-vector. VX: vector-scalar. VI: vector-immediate (5-bit).
    """
    VV = 'vv'
    VX = 'vx'
    VI = 'vi'


# ----------------------------------------------------------------------------
# Pack / unpack helpers
# ----------------------------------------------------------------------------

def _unpack_int(b: bytes, ew: int, signed: bool) -> int:
    fmt_u = {8: '<B', 16: '<H', 32: '<I', 64: '<Q'}[ew]
    fmt_s = {8: '<b', 16: '<h', 32: '<i', 64: '<q'}[ew]
    return struct.unpack(fmt_s if signed else fmt_u, b)[0]


def _unpack_int_vec(data: bytes, ew: int, signed: bool, vl: int) -> list:
    bw = ew // 8
    return [_unpack_int(data[i * bw:(i + 1) * bw], ew, signed) for i in range(vl)]


def _pack_float(values, ew: int) -> bytes:
    fmt = {16: 'e', 32: 'f', 64: 'd'}[ew]
    return struct.pack(f'<{len(values)}{fmt}', *values)


def _unpack_float(data: bytes, ew: int) -> list:
    fmt = {16: 'e', 32: 'f', 64: 'd'}[ew]
    n = len(data) * 8 // ew
    return list(struct.unpack(f'<{n}{fmt}', data))


def _pack_scalar_float(val: float, ew: int) -> bytes:
    """Pack a single float into the 8-byte scalar register format."""
    fmt = {16: 'e', 32: 'f', 64: 'd'}[ew]
    raw = struct.pack(f'<{fmt}', val)
    return raw + b'\x00' * (8 - len(raw))


def _ov_widths(shape: OvShape, sew: int) -> tuple:
    if shape is OvShape.BASE:
        return sew, sew, sew * 2
    if shape is OvShape.WIDE:
        return sew, sew * 2, sew * 2
    if shape is OvShape.NARROW:
        return sew, sew * 2, sew
    if shape is OvShape.SAME:
        return sew, sew, sew
    raise ValueError(shape)


# ----------------------------------------------------------------------------
# Random inputs
# ----------------------------------------------------------------------------

def _random_int(ew: int, signed: bool, rnd: Random) -> int:
    if signed:
        return rnd.randint(-(1 << (ew - 1)), (1 << (ew - 1)) - 1)
    return rnd.randint(0, (1 << ew) - 1)


def _random_ints(ew: int, signed: bool, vl: int, rnd: Random) -> list:
    return [_random_int(ew, signed, rnd) for _ in range(vl)]


def _random_floats(vl: int, rnd: Random) -> list:
    return [rnd.uniform(-8.0, 8.0) for _ in range(vl)]


# ----------------------------------------------------------------------------
# Integer reference. Matches the implementation's formula by design — the
# high-half MUL family is verified for plumbing + agreement, not formula
# correctness (see RESTART notes).
# ----------------------------------------------------------------------------

def _ref_int(op: VArithOp, s1: int, s2: int, acc: int, dst_ew: int,
             dst_signed: bool, shift_ew: int, carry_in: int = 0) -> int:
    if op is VArithOp.MUL:
        result = s1 * s2
    elif op in (VArithOp.MULH, VArithOp.MULHU, VArithOp.MULHSU):
        # High dst_ew bits of the 2*SEW product. Inputs already canonicalised.
        result = (s1 * s2) >> dst_ew
    elif op is VArithOp.ADD:
        result = s1 + s2
    elif op is VArithOp.ADC:
        result = s1 + s2 + carry_in
    elif op is VArithOp.SBC:
        result = s2 - s1 - carry_in
    elif op is VArithOp.MACC:
        result = s1 * s2 + acc
    elif op is VArithOp.SRL:
        # s2 is the (unsigned) wide source, s1 is the shift count.
        result = s2 >> (s1 & (shift_ew - 1))
    elif op in (VArithOp.MIN, VArithOp.MINU):
        result = min(s1, s2)
    elif op in (VArithOp.MAX, VArithOp.MAXU):
        result = max(s1, s2)
    else:
        raise NotImplementedError(op)
    mask = (1 << dst_ew) - 1
    result &= mask
    if dst_signed and result & (1 << (dst_ew - 1)):
        result -= 1 << dst_ew
    return result


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
    return max(1, (vl * ew + vline_bits - 1) // vline_bits)


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


# ----------------------------------------------------------------------------
# The runner
# ----------------------------------------------------------------------------

# Register layout used by every test.
_RS1 = 5
_VS1_REG = 2
_VS2_REG = 4
_VD_REG = 8


async def _run_arith(
    lamlet,
    *,
    op: VArithOp,
    sew: int,
    vl: int,
    mnemonic: str,
    rnd: Random,
    form: ArithForm = ArithForm.VV,
    shape: OvShape | None = None,
    src1_signed: bool = True,
    src2_signed: bool = True,
    is_float: bool = False,
) -> int:
    """Drive one arith test. Returns 0 on pass, 1 on fail.

    shape=None    → same-width path (VArithVv / VArithVx / VArithVi).
    shape=OvShape → Ov path (VArithVvOv / VArithVxOv).
    """
    if form is ArithForm.VI:
        assert shape is None, 'vi only supported on the same-width path'
        assert not is_float, 'vi only supported for integer ops'
    is_scalar = form is not ArithForm.VV
    vline_bits = lamlet.params.vline_bytes * 8
    page_bytes = lamlet.params.page_bytes

    if shape is None:
        src1_ew = src2_ew = dst_ew = sew
    else:
        src1_ew, src2_ew, dst_ew = _ov_widths(shape, sew)

    # ------------------------------------------------------------------
    # Inputs.
    # ------------------------------------------------------------------
    if is_float:
        s2 = _random_floats(vl, rnd)
        s2_bytes = _pack_float(s2, src2_ew)
        if form is ArithForm.VX:
            s1 = rnd.uniform(-8.0, 8.0)
            scalar_bytes8 = _pack_scalar_float(s1, src1_ew)
        else:
            s1 = _random_floats(vl, rnd)
            s1_bytes = _pack_float(s1, src1_ew)
    else:
        s2 = _random_ints(src2_ew, src2_signed, vl, rnd)
        s2_bytes = pack_elements(s2, src2_ew)
        if form is ArithForm.VI:
            # 5-bit signed immediate. Sign-extended by VArithVi.update_state;
            # canonicalisation in the reference path matches the kinstr's
            # scalar unpack at fmt-width.
            s1 = rnd.randint(-16, 15)
        elif form is ArithForm.VX:
            s1 = _random_int(src1_ew, src1_signed, rnd)
            scalar_bytes8 = s1.to_bytes(8, byteorder='little', signed=src1_signed)
        else:
            s1 = _random_ints(src1_ew, src1_signed, vl, rnd)
            s1_bytes = pack_elements(s1, src1_ew)

    is_accum = op is VArithOp.MACC
    if is_accum:
        if is_float:
            acc = _random_floats(vl, rnd)
            acc_bytes = _pack_float(acc, dst_ew)
        else:
            dst_signed_seed = src1_signed or src2_signed
            acc = _random_ints(dst_ew, dst_signed_seed, vl, rnd)
            acc_bytes = pack_elements(acc, dst_ew)
    else:
        acc = [0] * vl
        acc_bytes = None

    # Carry/borrow ops consume v0 as a per-element carry-in input.
    is_carry_op = op in CARRY_BORROW_OPS
    if is_carry_op:
        carry_in_bits = [rnd.randint(0, 1) for _ in range(vl)]
    else:
        carry_in_bits = None

    # ------------------------------------------------------------------
    # Memory layout and seeding.
    # ------------------------------------------------------------------
    base_addr = 0x90000000
    stride = max(page_bytes, 4096)
    if is_scalar:
        vs2_addr = base_addr
        vd_addr = vs2_addr + stride
    else:
        vs1_addr = base_addr
        vs2_addr = vs1_addr + stride
        vd_addr = vs2_addr + stride
        _alloc_vpu(lamlet, vs1_addr, len(s1_bytes))
    _alloc_vpu(lamlet, vs2_addr, len(s2_bytes))
    _alloc_vpu(lamlet, vd_addr, max(page_bytes, vl * dst_ew // 8))

    vs2_ord = Ordering(lamlet.word_order, src2_ew)
    vd_ord = Ordering(lamlet.word_order, dst_ew)
    if not is_scalar:
        vs1_ord = Ordering(lamlet.word_order, src1_ew)
        await lamlet.set_memory(vs1_addr, s1_bytes, ordering=vs1_ord)
    await lamlet.set_memory(vs2_addr, s2_bytes, ordering=vs2_ord)
    if acc_bytes is not None:
        await lamlet.set_memory(vd_addr, acc_bytes, ordering=vd_ord)

    lamlet.vtype = _vtype_for(sew, vl, vline_bits)

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET,
        mnemonic=f'test_{mnemonic}')

    # ------------------------------------------------------------------
    # Load operands (and seed the scalar reg if vx).
    # ------------------------------------------------------------------
    lamlet.vl = vl
    if form is ArithForm.VX:
        lamlet.scalar.write_reg(_RS1, scalar_bytes8, span_id)
    elif form is ArithForm.VI:
        pass  # immediate is encoded into the instruction itself
    else:
        await lamlet.vload(
            vd=_VS1_REG, addr=vs1_addr, ordering=vs1_ord,
            n_elements=vl, start_index=0, mask_reg=None,
            parent_span_id=span_id, emul=_emul(vl, src1_ew, vline_bits))
    await lamlet.vload(
        vd=_VS2_REG, addr=vs2_addr, ordering=vs2_ord,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=_emul(vl, src2_ew, vline_bits))
    if is_accum:
        await lamlet.vload(
            vd=_VD_REG, addr=vd_addr, ordering=vd_ord,
            n_elements=vl, start_index=0, mask_reg=None,
            parent_span_id=span_id, emul=_emul(vl, dst_ew, vline_bits))
    if is_carry_op:
        # Seed v0 with the per-element carry-in bits.
        await setup_mask_register(
            lamlet, mask_reg=0, mask_bits=[bool(b) for b in carry_in_bits],
            page_bytes=page_bytes, mask_mem_addr=0xa0000000)

    # ------------------------------------------------------------------
    # Run the arith instruction.
    # ------------------------------------------------------------------
    lamlet.vl = vl
    lamlet.pc = 0
    # vadc/vsbc encode with vm=0 (vm=1 reserved); everything else is unmasked.
    vm_value = 0 if is_carry_op else 1
    if shape is None:
        if form is ArithForm.VI:
            instr = VArithVi(vd=_VD_REG, vs2=_VS2_REG, simm5=s1 & 0x1F,
                             vm=vm_value, op=op)
        elif form is ArithForm.VX:
            instr = VArithVx(vd=_VD_REG, rs1=_RS1, vs2=_VS2_REG, vm=vm_value, op=op)
        else:
            instr = VArithVv(vd=_VD_REG, vs1=_VS1_REG, vs2=_VS2_REG, vm=vm_value, op=op)
    else:
        if form is ArithForm.VX:
            instr = VArithVxOv(
                vd=_VD_REG, rs1=_RS1, vs2=_VS2_REG, vm=1,
                op=op, shape=shape,
                scalar_signed=src1_signed, src2_signed=src2_signed,
                mnemonic=mnemonic)
        else:
            instr = VArithVvOv(
                vd=_VD_REG, vs1=_VS1_REG, vs2=_VS2_REG, vm=1,
                op=op, shape=shape,
                src1_signed=src1_signed, src2_signed=src2_signed,
                mnemonic=mnemonic)
    await instr.update_state(lamlet)

    await lamlet.vstore(
        vs=_VD_REG, addr=vd_addr, ordering=vd_ord,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=_emul(vl, dst_ew, vline_bits))

    lamlet.monitor.finalize_children(span_id)

    # ------------------------------------------------------------------
    # Verify.
    # ------------------------------------------------------------------
    result_bytes = await lamlet.get_memory_blocking(vd_addr, vl * dst_ew // 8)

    if is_float:
        actual = _unpack_float(result_bytes, dst_ew)
        # Float reference only handles MUL — only vfwmul is exercised here.
        assert op is VArithOp.FMUL, f'float ref only handles FMUL, got {op}'
        if form is ArithForm.VX:
            expected = [s1 * s2[i] for i in range(vl)]
        else:
            expected = [s1[i] * s2[i] for i in range(vl)]
        tol = 1e-6 * max(1.0, max(abs(v) for v in expected + [1.0]))
        ok = all(abs(actual[i] - expected[i]) <= tol for i in range(vl))
    else:
        dst_signed = src1_signed or src2_signed
        actual = _unpack_int_vec(result_bytes, dst_ew, dst_signed, vl)
        # Canonicalise inputs to Python ints under their declared signedness.
        s2_canon = s2 if src2_signed else [v & ((1 << src2_ew) - 1) for v in s2]
        if is_scalar:
            # vi sign-extends simm5 to src1_ew before the kinstr unpack, so
            # canonicalisation matches vx for both signed and unsigned ops.
            s1_canon = s1 if src1_signed else s1 & ((1 << src1_ew) - 1)
        else:
            s1_canon = s1 if src1_signed else [v & ((1 << src1_ew) - 1) for v in s1]
        shift_ew = src2_ew if op is VArithOp.SRL else dst_ew
        ci = carry_in_bits if carry_in_bits is not None else [0] * vl
        if is_scalar:
            expected = [_ref_int(op, s1_canon, s2_canon[i], 0, dst_ew,
                                 dst_signed, shift_ew, carry_in=ci[i])
                        for i in range(vl)]
        else:
            expected = [_ref_int(op, s1_canon[i], s2_canon[i], acc[i], dst_ew,
                                 dst_signed, shift_ew, carry_in=ci[i])
                        for i in range(vl)]
        ok = actual == expected

    if ok:
        logger.warning(f"PASS {mnemonic} sew={sew} vl={vl}")
        return 0
    logger.error(f"FAIL {mnemonic} sew={sew} vl={vl}")
    if is_scalar:
        logger.error(f"  scalar={s1}")
    else:
        logger.error(f"  s1={s1}")
    logger.error(f"  s2={s2}")
    if is_accum:
        logger.error(f"  acc={acc}")
    logger.error(f"  actual  ={actual}")
    logger.error(f"  expected={expected}")
    return 1


def _run(*, op, sew, vl, mnemonic, form=ArithForm.VV, shape=None,
         src1_signed=True, src2_signed=True, is_float=False,
         seed=0, geometry='k2x1_j1x1'):
    params = get_geometry(geometry)
    clock = Clock(max_cycles=20000)

    async def main():
        clock.register_main()
        clock.create_task(clock.clock_driver())
        lamlet = await setup_lamlet(clock, params)
        rnd = Random(seed)
        try:
            rc = await _run_arith(
                lamlet, op=op, sew=sew, vl=vl, mnemonic=mnemonic,
                rnd=rnd, form=form, shape=shape,
                src1_signed=src1_signed, src2_signed=src2_signed,
                is_float=is_float)
        except Exception:
            dump_span_trees(lamlet.monitor)
            raise
        clock.running = False
        return rc

    rc = asyncio.run(main())
    assert rc == 0, f'{mnemonic} failed'


# ----------------------------------------------------------------------------
# Same-width tests (VArithVv / VArithVx)
# ----------------------------------------------------------------------------

# (op, signed) for same-width single-source-signedness ops at the default
# sew=32 / vl=8 size.
_BASIC_OPS = [
    (VArithOp.MIN,   True),
    (VArithOp.MINU,  False),
    (VArithOp.MAX,   True),
    (VArithOp.MAXU,  False),
    (VArithOp.MULH,  True),
    (VArithOp.MULHU, False),
]


@pytest.mark.parametrize('form', [ArithForm.VV, ArithForm.VX],
                         ids=[f.value for f in (ArithForm.VV, ArithForm.VX)])
@pytest.mark.parametrize('op,signed', _BASIC_OPS,
                         ids=[op.value for op, _ in _BASIC_OPS])
def test_arith_basic(op, signed, form):
    """vmin/vmax/vmulh family — sew=32, vl=8."""
    _run(op=op, sew=32, vl=8, form=form,
         src1_signed=signed, src2_signed=signed,
         mnemonic=f'v{op.value}.{form.value}',
         seed=hash((op.value, signed, form.value)) & 0xffff)


# Alternate-width sanity: sew != 32, vl varied to exercise the lmul-aware
# vtype computation in _vtype_for.
@pytest.mark.parametrize('op,signed,sew,vl,form,seed', [
    (VArithOp.MIN,   True,  16, 12, ArithForm.VV, 1),
    (VArithOp.MAXU,  False,  8, 15, ArithForm.VX, 2),
    (VArithOp.MULH,  True,  16, 12, ArithForm.VV, 7),
    (VArithOp.MULHU, False,  8, 15, ArithForm.VX, 8),
], ids=['vmin.vv-sew16', 'vmaxu.vx-sew8', 'vmulh.vv-sew16', 'vmulhu.vx-sew8'])
def test_arith_basic_alt(op, signed, sew, vl, form, seed):
    _run(op=op, sew=sew, vl=vl, form=form,
         src1_signed=signed, src2_signed=signed,
         mnemonic=f'v{op.value}.{form.value}', seed=seed)


# ----------------------------------------------------------------------------
# Width-asymmetric tests (VArithVvOv / VArithVxOv)
# ----------------------------------------------------------------------------

# (op, shape, src1_signed, src2_signed, is_float, form, mnemonic, seed)
_OV_CASES = [
    (VArithOp.MUL,    OvShape.BASE,   False, False, False, ArithForm.VV, 'vwmulu.vv',  0),
    (VArithOp.MUL,    OvShape.BASE,   True,  True,  False, ArithForm.VV, 'vwmul.vv',   0),
    (VArithOp.MUL,    OvShape.BASE,   False, True,  False, ArithForm.VV, 'vwmulsu.vv', 0),
    (VArithOp.MACC,   OvShape.BASE,   True,  True,  False, ArithForm.VV, 'vwmacc.vv',  0),
    (VArithOp.SRL,    OvShape.NARROW, False, False, False, ArithForm.VV, 'vnsrl.wv',   0),
    (VArithOp.FMUL,   OvShape.BASE,   False, False, True,  ArithForm.VV, 'vfwmul.vv',  0),
    (VArithOp.MUL,    OvShape.BASE,   False, False, False, ArithForm.VX, 'vwmulu.vx',  0),
    (VArithOp.MULHSU, OvShape.SAME,   False, True,  False, ArithForm.VV, 'vmulhsu.vv', 9),
    (VArithOp.MULHSU, OvShape.SAME,   False, True,  False, ArithForm.VX, 'vmulhsu.vx', 10),
]


@pytest.mark.parametrize(
    'op,shape,src1_signed,src2_signed,is_float,form,mnemonic,seed',
    _OV_CASES,
    ids=[case[6] for case in _OV_CASES],
)
def test_arith_ov(op, shape, src1_signed, src2_signed, is_float, form,
                  mnemonic, seed):
    """Width-asymmetric ops: widening, narrowing, mixed-signed high-half mul."""
    _run(op=op, shape=shape, sew=32, vl=4, form=form,
         src1_signed=src1_signed, src2_signed=src2_signed,
         is_float=is_float, mnemonic=mnemonic, seed=seed)


# ----------------------------------------------------------------------------
# Carry/borrow (vadc/vsbc). vm=0 mandatory; v0 carries per-element carry-in.
# ----------------------------------------------------------------------------

def test_vadc_vvm():
    _run(op=VArithOp.ADC, sew=32, vl=8,
         src1_signed=False, src2_signed=False,
         mnemonic='vadc.vvm', seed=11)


def test_vsbc_vvm():
    _run(op=VArithOp.SBC, sew=32, vl=8,
         src1_signed=False, src2_signed=False,
         mnemonic='vsbc.vvm', seed=12)


def test_vadc_vxm():
    _run(op=VArithOp.ADC, sew=32, vl=8, form=ArithForm.VX,
         src1_signed=False, src2_signed=False,
         mnemonic='vadc.vxm', seed=13)


def test_vsbc_vxm():
    _run(op=VArithOp.SBC, sew=32, vl=8, form=ArithForm.VX,
         src1_signed=False, src2_signed=False,
         mnemonic='vsbc.vxm', seed=14)


def test_vadc_vim():
    _run(op=VArithOp.ADC, sew=32, vl=8, form=ArithForm.VI,
         src1_signed=False, src2_signed=False,
         mnemonic='vadc.vim', seed=15)


# ----------------------------------------------------------------------------
# Mask-output carry/borrow (vmadc/vmsbc). Output is one bit per element packed
# into a mask register; vm=0 enables v0 as carry-in, vm=1 means no carry-in.
# ----------------------------------------------------------------------------

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


def _ref_mcmp(op: VCmpOp, vs2: int, other: int, sew: int, carry_in: int) -> int:
    if op is VCmpOp.MADC:
        return ((vs2 + other + carry_in) >> sew) & 1
    if op is VCmpOp.MSBC:
        return 1 if (vs2 - other - carry_in) < 0 else 0
    raise NotImplementedError(op)


async def _run_mcmp(
    lamlet,
    *,
    op: VCmpOp,
    sew: int,
    vl: int,
    mnemonic: str,
    rnd: Random,
    form: ArithForm = ArithForm.VV,
    has_carry_in: bool = True,
) -> int:
    """Drive one vmadc/vmsbc test. Returns 0 on pass, 1 on fail."""
    assert op in (VCmpOp.MADC, VCmpOp.MSBC)
    assert not (op is VCmpOp.MSBC and form is ArithForm.VI), (
        'vmsbc.vim is reserved')

    is_scalar = form is not ArithForm.VV
    vline_bits = lamlet.params.vline_bytes * 8
    wb = lamlet.params.word_bytes
    j_in_l = lamlet.params.j_in_l
    page_bytes = lamlet.params.page_bytes
    sew_mask = (1 << sew) - 1

    s2 = _random_ints(sew, signed=False, vl=vl, rnd=rnd)
    s2_bytes = pack_elements(s2, sew)
    if form is ArithForm.VV:
        s1_list = _random_ints(sew, signed=False, vl=vl, rnd=rnd)
        s1_bytes = pack_elements(s1_list, sew)
        others = list(s1_list)
    elif form is ArithForm.VX:
        s1_scalar = _random_int(sew, signed=False, rnd=rnd)
        scalar_bytes8 = s1_scalar.to_bytes(8, byteorder='little', signed=False)
        others = [s1_scalar] * vl
    else:  # VI: simm5 is sign-extended to SEW, then taken unsigned for carry.
        simm5_signed = rnd.randint(-16, 15)
        others = [simm5_signed & sew_mask] * vl

    if has_carry_in:
        carry_in_bits = [rnd.randint(0, 1) for _ in range(vl)]
    else:
        carry_in_bits = [0] * vl

    base_addr = 0x90000000
    stride = max(page_bytes, 4096)
    if is_scalar:
        vs2_addr = base_addr
    else:
        vs1_addr = base_addr
        vs2_addr = vs1_addr + stride
        _alloc_vpu(lamlet, vs1_addr, len(s1_bytes))
    _alloc_vpu(lamlet, vs2_addr, len(s2_bytes))
    # Memory for reading the dst mask back via vstore-as-ew=64.
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
    if form is ArithForm.VV:
        await lamlet.vload(
            vd=_VS1_REG, addr=vs1_addr, ordering=vs1_ord,
            n_elements=vl, start_index=0, mask_reg=None,
            parent_span_id=span_id, emul=_emul(vl, sew, vline_bits))
    elif form is ArithForm.VX:
        lamlet.scalar.write_reg(_RS1, scalar_bytes8, span_id)
    await lamlet.vload(
        vd=_VS2_REG, addr=vs2_addr, ordering=vs2_ord,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=_emul(vl, sew, vline_bits))

    if has_carry_in:
        await setup_mask_register(
            lamlet, mask_reg=0, mask_bits=[bool(b) for b in carry_in_bits],
            page_bytes=page_bytes, mask_mem_addr=0xa0000000)

    lamlet.vl = vl
    lamlet.pc = 0
    vm_value = 0 if has_carry_in else 1
    if form is ArithForm.VI:
        instr = VCmpVi(vd=_VD_REG, vs2=_VS2_REG, simm5=simm5_signed & 0x1F,
                       vm=vm_value, op=op)
    elif form is ArithForm.VX:
        instr = VCmpVx(vd=_VD_REG, vs2=_VS2_REG, rs1=_RS1, vm=vm_value, op=op)
    else:
        instr = VCmpVv(vd=_VD_REG, vs2=_VS2_REG, vs1=_VS1_REG,
                       vm=vm_value, op=op)
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

    expected = [bool(_ref_mcmp(op, s2[i], others[i], sew, carry_in_bits[i]))
                for i in range(vl)]

    ok = actual == expected
    if ok:
        logger.warning(f"PASS {mnemonic} sew={sew} vl={vl}")
        return 0
    logger.error(f"FAIL {mnemonic} sew={sew} vl={vl}")
    if is_scalar:
        logger.error(f"  scalar/imm={others[0]}")
    else:
        logger.error(f"  s1={others}")
    logger.error(f"  s2={s2}")
    logger.error(f"  cin={carry_in_bits}")
    logger.error(f"  actual  ={actual}")
    logger.error(f"  expected={expected}")
    return 1


def _run_m(*, op, sew, vl, mnemonic, form=ArithForm.VV, has_carry_in=True,
           seed=0, geometry='k2x1_j1x1'):
    params = get_geometry(geometry)
    clock = Clock(max_cycles=20000)

    async def main():
        clock.register_main()
        clock.create_task(clock.clock_driver())
        lamlet = await setup_lamlet(clock, params)
        rnd = Random(seed)
        try:
            rc = await _run_mcmp(
                lamlet, op=op, sew=sew, vl=vl, mnemonic=mnemonic,
                rnd=rnd, form=form, has_carry_in=has_carry_in)
        except Exception:
            dump_span_trees(lamlet.monitor)
            raise
        clock.running = False
        return rc

    rc = asyncio.run(main())
    assert rc == 0, f'{mnemonic} failed'


def test_vmadc_vvm():
    _run_m(op=VCmpOp.MADC, sew=32, vl=8, mnemonic='vmadc.vvm', seed=21)


def test_vmadc_vv():
    _run_m(op=VCmpOp.MADC, sew=32, vl=8, has_carry_in=False,
           mnemonic='vmadc.vv', seed=22)


def test_vmadc_vxm():
    _run_m(op=VCmpOp.MADC, sew=32, vl=8, form=ArithForm.VX,
           mnemonic='vmadc.vxm', seed=23)


def test_vmadc_vx():
    _run_m(op=VCmpOp.MADC, sew=32, vl=8, form=ArithForm.VX,
           has_carry_in=False, mnemonic='vmadc.vx', seed=24)


def test_vmadc_vim():
    _run_m(op=VCmpOp.MADC, sew=32, vl=8, form=ArithForm.VI,
           mnemonic='vmadc.vim', seed=25)


def test_vmadc_vi():
    _run_m(op=VCmpOp.MADC, sew=32, vl=8, form=ArithForm.VI,
           has_carry_in=False, mnemonic='vmadc.vi', seed=26)


def test_vmsbc_vvm():
    _run_m(op=VCmpOp.MSBC, sew=32, vl=8, mnemonic='vmsbc.vvm', seed=31)


def test_vmsbc_vv():
    _run_m(op=VCmpOp.MSBC, sew=32, vl=8, has_carry_in=False,
           mnemonic='vmsbc.vv', seed=32)


def test_vmsbc_vxm():
    _run_m(op=VCmpOp.MSBC, sew=32, vl=8, form=ArithForm.VX,
           mnemonic='vmsbc.vxm', seed=33)


def test_vmsbc_vx():
    _run_m(op=VCmpOp.MSBC, sew=32, vl=8, form=ArithForm.VX,
           has_carry_in=False, mnemonic='vmsbc.vx', seed=34)
