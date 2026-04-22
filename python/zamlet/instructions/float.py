"""Floating-point instructions.

Reference: riscv-isa-manual/src/f-st-ext.adoc and d-st-ext.adoc
"""

import math
import struct
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zamlet.oamlet.oamlet import Oamlet

from zamlet.addresses import Ordering
from zamlet.register_names import reg_name, freg_name
from zamlet.instructions.riscv_instr import riscv_instr
from zamlet import utils


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fp_suffix(is_double: bool) -> str:
    return 'd' if is_double else 's'


def _fp_pack_char(is_double: bool) -> str:
    return 'd' if is_double else 'f'


def _fp_width(is_double: bool) -> int:
    return 8 if is_double else 4


def _read_fp(s, freg: int, is_double: bool) -> float:
    w = _fp_width(is_double)
    return struct.unpack(_fp_pack_char(is_double), s.scalar.read_freg(freg)[:w])[0]


def _write_fp(s, freg: int, value: float, is_double: bool, span_id: int) -> None:
    packed = struct.pack(_fp_pack_char(is_double), value)
    if not is_double:
        packed = packed + bytes(4)
    s.scalar.write_freg(freg, packed, span_id)


def _read_fp_bits(s, freg: int, is_double: bool) -> int:
    w = _fp_width(is_double)
    return int.from_bytes(s.scalar.read_freg(freg)[:w], byteorder='little', signed=False)


def _write_fp_bits(s, freg: int, bits: int, is_double: bool, span_id: int) -> None:
    w = _fp_width(is_double)
    data = bits.to_bytes(w, byteorder='little', signed=False)
    if not is_double:
        data = data + bytes(4)
    s.scalar.write_freg(freg, data, span_id)


# ---------------------------------------------------------------------------
# Integer <-> FP register moves (bit-preserving, no type conversion)
# ---------------------------------------------------------------------------

@dataclass
class FmvWX:
    """FMV.W.X - Move from integer register to FP register (single-precision).

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    fd: int
    rs1: int

    def __str__(self):
        return f'fmv.w.x\t{freg_name(self.fd)},{reg_name(self.rs1)}'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(None, self.fd, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        value = int.from_bytes(rs1_bytes, byteorder='little', signed=False) & 0xffffffff
        value_bytes = value.to_bytes(8, byteorder='little', signed=False)
        s.scalar.write_freg(self.fd, value_bytes, span_id)
        s.pc += 4


@dataclass
class FmvXW:
    """FMV.X.W - Move from FP register (single-precision) to integer register.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    rd: int
    rs1: int

    def __str__(self):
        return f'fmv.x.w\t{reg_name(self.rd)},{freg_name(self.rs1)}'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1])
        freg_bytes = s.scalar.read_freg(self.rs1)
        # Sign-extend the 32-bit value to XLEN, per RISC-V spec.
        value = int.from_bytes(freg_bytes[:4], byteorder='little', signed=True)
        value_bytes = value.to_bytes(s.params.word_bytes, byteorder='little', signed=True)
        s.scalar.write_reg(self.rd, value_bytes, span_id)
        s.pc += 4


@dataclass
class FmvXD:
    """FMV.X.D - Move from double FP register to integer register.

    Reference: riscv-isa-manual/src/d-st-ext.adoc
    """
    rd: int
    rs1: int

    def __str__(self):
        return f'fmv.x.d\t{reg_name(self.rd)},{freg_name(self.rs1)}'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1])
        freg_bytes = s.scalar.read_freg(self.rs1)
        value = int.from_bytes(freg_bytes[:8], byteorder='little', signed=False)
        value_bytes = value.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, value_bytes, span_id)
        s.pc += 4


@dataclass
class FmvDX:
    """FMV.D.X - Move from integer register to double FP register.

    Reference: riscv-isa-manual/src/d-st-ext.adoc
    """
    fd: int
    rs1: int

    def __str__(self):
        return f'fmv.d.x\t{freg_name(self.fd)},{reg_name(self.rs1)}'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(None, self.fd, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        value = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        value_bytes = value.to_bytes(8, byteorder='little', signed=False)
        s.scalar.write_freg(self.fd, value_bytes, span_id)
        s.pc += 4


# ---------------------------------------------------------------------------
# Loads / stores
# ---------------------------------------------------------------------------

@dataclass
class Flw:
    """FLW - Floating-Point Load Word.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    fd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'flw\t{freg_name(self.fd)},{self.imm}({reg_name(self.rs1)})'

    async def update_resolve(self, s, future_out, future_in):
        await future_in
        f_data = future_in.result()
        assert isinstance(f_data, bytes)
        assert len(f_data) == 4
        data = utils.pad(f_data, s.params.word_bytes)
        future_out.set_result(data)
        scalar_val = struct.unpack('f', f_data)[0]
        logger.debug(f'{s.clock.cycle} freg: {self.fd} padding the flw result, set result {scalar_val} ')

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(None, self.fd, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        addr = rs1_val + self.imm
        data_future = await s.get_memory(addr, 4)
        padded_future = s.clock.create_future()
        s.clock.create_task(self.update_resolve(s, padded_future, data_future))
        s.scalar.write_freg_future(self.fd, padded_future, span_id)
        s.pc += 4


@dataclass
class Fld:
    """FLD - Floating-Point Load Double.

    Reference: riscv-isa-manual/src/d-st-ext.adoc
    """
    fd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'fld\t{freg_name(self.fd)},{self.imm}({reg_name(self.rs1)})'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(None, self.fd, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        addr = rs1_val + self.imm
        logger.debug(f'Fld: {freg_name(self.fd)} <- mem[0x{addr:x}]')
        data_future = await s.get_memory(addr, 8)
        s.scalar.write_freg_future(self.fd, data_future, span_id)
        s.pc += 4


@dataclass
class Fsw:
    """FSW - Floating-Point Store Word.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    rs2: int
    rs1: int
    imm: int

    def __str__(self):
        return f'fsw\t{freg_name(self.rs2)},{self.imm}({reg_name(self.rs1)})'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [self.rs2])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        addr = rs1_val + self.imm
        freg_bytes = s.scalar.read_freg(self.rs2)
        data = freg_bytes[:4]
        await s.set_memory(addr, data,
                           weak_ordering=Ordering(s.word_order, 32))
        s.pc += 4


@dataclass
class Fsd:
    """FSD - Floating-Point Store Double.

    Reference: riscv-isa-manual/src/d-st-ext.adoc
    """
    rs2: int
    rs1: int
    imm: int

    def __str__(self):
        return f'fsd\t{freg_name(self.rs2)},{self.imm}({reg_name(self.rs1)})'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [self.rs2])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        addr = rs1_val + self.imm
        freg_bytes = s.scalar.read_freg(self.rs2)
        await s.set_memory(addr, freg_bytes[:8],
                           weak_ordering=Ordering(s.word_order, 64))
        s.pc += 4


# ---------------------------------------------------------------------------
# Arithmetic, sign-injection, min/max, sqrt (FArith)
# ---------------------------------------------------------------------------

class FArithOp(Enum):
    FADD = 'fadd'       # binary
    FSUB = 'fsub'       # binary
    FMUL = 'fmul'       # binary
    FDIV = 'fdiv'       # binary
    FSQRT = 'fsqrt'     # unary (rs2 ignored)
    FMIN = 'fmin'       # binary
    FMAX = 'fmax'       # binary
    FSGNJ = 'fsgnj'     # binary (bit-level: sign from rs2, magnitude from rs1)
    FSGNJN = 'fsgnjn'   # binary (bit-level: sign = ~rs2.sign)
    FSGNJX = 'fsgnjx'   # binary (bit-level: sign = rs1.sign ^ rs2.sign)


_FARITH_UNARY = {FArithOp.FSQRT}
_FARITH_SGNJ = {FArithOp.FSGNJ, FArithOp.FSGNJN, FArithOp.FSGNJX}

# Pseudo-mnemonic for sgnj ops when rs1 == rs2.
_FARITH_SGNJ_PSEUDO = {
    FArithOp.FSGNJ: 'fmv',
    FArithOp.FSGNJN: 'fneg',
    FArithOp.FSGNJX: 'fabs',
}

# Rounding-mode suffix (funct3 field). DYN (7) is the default and is omitted.
_RM_SUFFIX = {0: 'rne', 1: 'rtz', 2: 'rdn', 3: 'rup', 4: 'rmm'}


@dataclass
class FArith:
    """Generic scalar FP arithmetic / sign-inject / min-max / sqrt.

    Covers FADD.{S,D}, FSUB.{S,D}, FMUL.{S,D}, FDIV.{S,D}, FSQRT.{S,D},
    FMIN.{S,D}, FMAX.{S,D}, FSGNJ{,N,X}.{S,D}.

    Reference: riscv-isa-manual/src/f-st-ext.adoc and d-st-ext.adoc
    """
    fd: int
    rs1: int
    rs2: int       # ignored for unary ops
    op: FArithOp
    is_double: bool

    def __str__(self):
        if self.op in _FARITH_SGNJ and self.rs1 == self.rs2:
            pseudo = _FARITH_SGNJ_PSEUDO[self.op]
            return (f'{pseudo}.{_fp_suffix(self.is_double)}\t'
                    f'{freg_name(self.fd)},{freg_name(self.rs1)}')
        mnem = f'{self.op.value}.{_fp_suffix(self.is_double)}'
        if self.op in _FARITH_UNARY:
            return f'{mnem}\t{freg_name(self.fd)},{freg_name(self.rs1)}'
        return (f'{mnem}\t{freg_name(self.fd)},'
                f'{freg_name(self.rs1)},{freg_name(self.rs2)}')

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        if self.op in _FARITH_UNARY:
            src_fregs = [self.rs1]
        else:
            src_fregs = [self.rs1, self.rs2]
        await s.scalar.wait_all_regs_ready(None, self.fd, [], src_fregs)

        if self.op in _FARITH_SGNJ:
            width = 64 if self.is_double else 32
            sign_bit = 1 << (width - 1)
            b1 = _read_fp_bits(s, self.rs1, self.is_double)
            b2 = _read_fp_bits(s, self.rs2, self.is_double)
            magnitude = b1 & (sign_bit - 1)
            if self.op is FArithOp.FSGNJ:
                new_sign = b2 & sign_bit
            elif self.op is FArithOp.FSGNJN:
                new_sign = (b2 & sign_bit) ^ sign_bit
            else:
                new_sign = (b1 ^ b2) & sign_bit
            _write_fp_bits(s, self.fd, magnitude | new_sign, self.is_double, span_id)
            s.pc += 4
            return

        v1 = _read_fp(s, self.rs1, self.is_double)
        if self.op is FArithOp.FSQRT:
            result = math.sqrt(v1)
        else:
            v2 = _read_fp(s, self.rs2, self.is_double)
            if self.op is FArithOp.FADD:
                result = v1 + v2
            elif self.op is FArithOp.FSUB:
                result = v1 - v2
            elif self.op is FArithOp.FMUL:
                result = v1 * v2
            elif self.op is FArithOp.FDIV:
                result = v1 / v2
            elif self.op is FArithOp.FMIN:
                result = min(v1, v2)
            elif self.op is FArithOp.FMAX:
                result = max(v1, v2)
            else:
                raise AssertionError(f'unhandled FArithOp {self.op}')
        _write_fp(s, self.fd, result, self.is_double, span_id)
        s.pc += 4


# ---------------------------------------------------------------------------
# Comparisons (FEQ / FLT / FLE)
# ---------------------------------------------------------------------------

class FCmpOp(Enum):
    FEQ = 'feq'
    FLT = 'flt'
    FLE = 'fle'


@dataclass
class FCmp:
    """Generic scalar FP comparison. Writes 0/1 to integer register rd.

    Reference: riscv-isa-manual/src/f-st-ext.adoc and d-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int
    op: FCmpOp
    is_double: bool

    def __str__(self):
        mnem = f'{self.op.value}.{_fp_suffix(self.is_double)}'
        return (f'{mnem}\t{reg_name(self.rd)},'
                f'{freg_name(self.rs1)},{freg_name(self.rs2)}')

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1, self.rs2])
        v1 = _read_fp(s, self.rs1, self.is_double)
        v2 = _read_fp(s, self.rs2, self.is_double)
        if self.op is FCmpOp.FEQ:
            result = 1 if v1 == v2 else 0
        elif self.op is FCmpOp.FLT:
            result = 1 if v1 < v2 else 0
        elif self.op is FCmpOp.FLE:
            result = 1 if v1 <= v2 else 0
        else:
            raise AssertionError(f'unhandled FCmpOp {self.op}')
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes, span_id)
        s.pc += 4


# ---------------------------------------------------------------------------
# Conversions (int<->float, precision)
# ---------------------------------------------------------------------------

class FType(Enum):
    F32 = 'f32'
    F64 = 'f64'
    I32 = 'i32'
    I64 = 'i64'
    U32 = 'u32'
    U64 = 'u64'


_FT_IS_FP = {FType.F32, FType.F64}
_FT_BYTES = {
    FType.F32: 4, FType.F64: 8,
    FType.I32: 4, FType.U32: 4,
    FType.I64: 8, FType.U64: 8,
}
_FT_MNEMONIC = {
    FType.F32: 's', FType.F64: 'd',
    FType.I32: 'w', FType.U32: 'wu',
    FType.I64: 'l', FType.U64: 'lu',
}
_FT_SIGNED = {FType.I32: True, FType.I64: True, FType.U32: False, FType.U64: False}


@dataclass
class FCvt:
    """Generic FP conversion (int<->float or precision change).

    dst/src are register numbers; whether each refers to an FP or integer
    register is determined by dst_type / src_type. rm is the rounding-mode
    field (funct3); 7 = DYN (default, omitted from disasm).

    Reference: riscv-isa-manual/src/f-st-ext.adoc and d-st-ext.adoc
    """
    dst: int
    src: int
    dst_type: FType
    src_type: FType
    rm: int = 7

    def __str__(self):
        mnem = f'fcvt.{_FT_MNEMONIC[self.dst_type]}.{_FT_MNEMONIC[self.src_type]}'
        dst_name = freg_name(self.dst) if self.dst_type in _FT_IS_FP else reg_name(self.dst)
        src_name = freg_name(self.src) if self.src_type in _FT_IS_FP else reg_name(self.src)
        suffix = _RM_SUFFIX.get(self.rm)
        tail = f',{suffix}' if suffix is not None else ''
        return f'{mnem}\t{dst_name},{src_name}{tail}'

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        dst_is_fp = self.dst_type in _FT_IS_FP
        src_is_fp = self.src_type in _FT_IS_FP
        rd_arg = None if dst_is_fp else self.dst
        fd_arg = self.dst if dst_is_fp else None
        src_regs = [] if src_is_fp else [self.src]
        src_fregs = [self.src] if src_is_fp else []
        await s.scalar.wait_all_regs_ready(rd_arg, fd_arg, src_regs, src_fregs)

        src_w = _FT_BYTES[self.src_type]
        if src_is_fp:
            raw = s.scalar.read_freg(self.src)[:src_w]
            value = struct.unpack(_fp_pack_char(self.src_type is FType.F64), raw)[0]
        else:
            raw = s.scalar.read_reg(self.src)[:src_w]
            value = int.from_bytes(raw, byteorder='little', signed=_FT_SIGNED[self.src_type])

        if dst_is_fp:
            float_val = float(value)
            packed = struct.pack(_fp_pack_char(self.dst_type is FType.F64), float_val)
            if self.dst_type is FType.F32:
                packed = packed + bytes(4)
            s.scalar.write_freg(self.dst, packed, span_id)
        else:
            int_val = int(value)
            dst_w = _FT_BYTES[self.dst_type]
            signed = _FT_SIGNED[self.dst_type]
            # Saturate to destination range per RISC-V spec.
            if signed:
                lo, hi = -(1 << (dst_w * 8 - 1)), (1 << (dst_w * 8 - 1)) - 1
            else:
                lo, hi = 0, (1 << (dst_w * 8)) - 1
            if int_val < lo:
                int_val = lo
            elif int_val > hi:
                int_val = hi
            word_bytes = s.params.word_bytes
            # Sign- or zero-extend to XLEN.
            data = int_val.to_bytes(dst_w, byteorder='little', signed=signed)
            if len(data) < word_bytes:
                pad_byte = 0xff if (signed and int_val < 0) else 0x00
                data = data + bytes([pad_byte] * (word_bytes - len(data)))
            s.scalar.write_reg(self.dst, data, span_id)
        s.pc += 4


# ---------------------------------------------------------------------------
# Fused multiply-add (FMA)
# ---------------------------------------------------------------------------

class FmaOp(Enum):
    FMADD = 'fmadd'      # +(rs1*rs2) + rs3
    FMSUB = 'fmsub'      # +(rs1*rs2) - rs3
    FNMSUB = 'fnmsub'    # -(rs1*rs2) + rs3
    FNMADD = 'fnmadd'    # -(rs1*rs2) - rs3


@dataclass
class FMA:
    """Generic fused multiply-add.

    Reference: riscv-isa-manual/src/f-st-ext.adoc and d-st-ext.adoc
    """
    fd: int
    rs1: int
    rs2: int
    rs3: int
    op: FmaOp
    is_double: bool

    def __str__(self):
        mnem = f'{self.op.value}.{_fp_suffix(self.is_double)}'
        return (f'{mnem}\t{freg_name(self.fd)},{freg_name(self.rs1)},'
                f'{freg_name(self.rs2)},{freg_name(self.rs3)}')

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(
            None, self.fd, [], [self.rs1, self.rs2, self.rs3])
        v1 = _read_fp(s, self.rs1, self.is_double)
        v2 = _read_fp(s, self.rs2, self.is_double)
        v3 = _read_fp(s, self.rs3, self.is_double)
        prod = v1 * v2
        if self.op is FmaOp.FMADD:
            result = prod + v3
        elif self.op is FmaOp.FMSUB:
            result = prod - v3
        elif self.op is FmaOp.FNMSUB:
            result = -prod + v3
        elif self.op is FmaOp.FNMADD:
            result = -prod - v3
        else:
            raise AssertionError(f'unhandled FmaOp {self.op}')
        _write_fp(s, self.fd, result, self.is_double, span_id)
        s.pc += 4


# ---------------------------------------------------------------------------
# FClass (classify)
# ---------------------------------------------------------------------------

@dataclass
class FClass:
    """FCLASS.{S,D} - classify FP value, write one-hot mask to integer reg.

    Reference: riscv-isa-manual/src/f-st-ext.adoc and d-st-ext.adoc
    """
    rd: int
    rs1: int
    is_double: bool

    def __str__(self):
        return (f'fclass.{_fp_suffix(self.is_double)}\t'
                f'{reg_name(self.rd)},{freg_name(self.rs1)}')

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1])
        bits = _read_fp_bits(s, self.rs1, self.is_double)
        if self.is_double:
            exp_shift, exp_max, width = 52, 0x7ff, 64
        else:
            exp_shift, exp_max, width = 23, 0xff, 32
        sign = (bits >> (width - 1)) & 1
        exp = (bits >> exp_shift) & exp_max
        mant = bits & ((1 << exp_shift) - 1)
        if exp == 0:
            if mant == 0:
                cls = 3 if sign else 4          # ±0
            else:
                cls = 2 if sign else 5          # ±subnormal
        elif exp == exp_max:
            if mant == 0:
                cls = 0 if sign else 7          # ±inf
            elif mant & (1 << (exp_shift - 1)):
                cls = 9                          # quiet NaN
            else:
                cls = 8                          # signaling NaN
        else:
            cls = 1 if sign else 6              # ±normal
        result = 1 << cls
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes, span_id)
        s.pc += 4

