"""M extension - Integer Multiply/Divide instructions.

Reference: riscv-isa-manual/src/m-st-ext.adoc
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zamlet.lamlet.lamlet import Lamlet

from zamlet.register_names import reg_name


def _sign_extend_32_to_64(val):
    """Sign-extend a 32-bit value to 64 bits."""
    val = val & 0xffffffff
    if val & 0x80000000:
        return val | 0xffffffff00000000
    return val


def _to_signed_32(val):
    """Interpret lower 32 bits as signed."""
    val = val & 0xffffffff
    if val & 0x80000000:
        return val - 0x100000000
    return val


@dataclass
class Mul:
    """MUL - Multiply (lower 64 bits of result).

    Performs signed multiplication of rs1 and rs2, writes lower 64 bits to rd.

    Reference: riscv-isa-manual/src/m-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'mul\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        result = (val1 * val2) & 0xffffffffffffffff
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


@dataclass
class Mulh:
    """MULH - Multiply High (upper 64 bits of signed result).

    Performs signed multiplication of rs1 and rs2, writes upper 64 bits to rd.

    Reference: riscv-isa-manual/src/m-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'mulh\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        if val1 & 0x8000000000000000:
            val1 = val1 - 0x10000000000000000
        if val2 & 0x8000000000000000:
            val2 = val2 - 0x10000000000000000
        result = (val1 * val2) >> 64
        result_bytes = (result & 0xffffffffffffffff).to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


@dataclass
class Mulhsu:
    """MULHSU - Multiply High Signed-Unsigned (upper 64 bits).

    Performs signed(rs1) × unsigned(rs2) multiplication, writes upper 64 bits to rd.

    Reference: riscv-isa-manual/src/m-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'mulhsu\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        if val1 & 0x8000000000000000:
            val1 = val1 - 0x10000000000000000
        result = (val1 * val2) >> 64
        result_bytes = (result & 0xffffffffffffffff).to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


@dataclass
class Mulhu:
    """MULHU - Multiply High Unsigned (upper 64 bits of unsigned result).

    Performs unsigned multiplication of rs1 and rs2, writes upper 64 bits to rd.

    Reference: riscv-isa-manual/src/m-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'mulhu\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        result = (val1 * val2) >> 64
        result_bytes = (result & 0xffffffffffffffff).to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


@dataclass
class Div:
    """DIV - Divide (signed).

    Performs signed division of rs1 by rs2, writes quotient to rd.

    Reference: riscv-isa-manual/src/m-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'div\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        if val1 & 0x8000000000000000:
            val1_signed = val1 - 0x10000000000000000
        else:
            val1_signed = val1
        if val2 & 0x8000000000000000:
            val2_signed = val2 - 0x10000000000000000
        else:
            val2_signed = val2
        if val2 == 0:
            result = 0xffffffffffffffff
        elif val1_signed == -0x8000000000000000 and val2_signed == -1:
            result = 0x8000000000000000
        else:
            result = val1_signed // val2_signed
            result = result & 0xffffffffffffffff
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


@dataclass
class Divu:
    """DIVU - Divide Unsigned.

    Performs unsigned division of rs1 by rs2, writes quotient to rd.

    Reference: riscv-isa-manual/src/m-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'divu\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        if val2 == 0:
            result = 0xffffffffffffffff
        else:
            result = val1 // val2
        result_bytes = (result & 0xffffffffffffffff).to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


@dataclass
class Rem:
    """REM - Remainder (signed).

    Performs signed division of rs1 by rs2, writes remainder to rd.

    Reference: riscv-isa-manual/src/m-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'rem\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        if val1 & 0x8000000000000000:
            val1_signed = val1 - 0x10000000000000000
        else:
            val1_signed = val1
        if val2 & 0x8000000000000000:
            val2_signed = val2 - 0x10000000000000000
        else:
            val2_signed = val2
        if val2 == 0:
            result = val1
        elif val1_signed == -0x8000000000000000 and val2_signed == -1:
            result = 0
        else:
            result = val1_signed % val2_signed
            result = result & 0xffffffffffffffff
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


@dataclass
class Remu:
    """REMU - Remainder Unsigned.

    Performs unsigned division of rs1 by rs2, writes remainder to rd.

    Reference: riscv-isa-manual/src/m-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'remu\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        if val2 == 0:
            result = val1
        else:
            result = val1 % val2
        result_bytes = (result & 0xffffffffffffffff).to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


# RV64M *W instructions - operate on lower 32 bits, sign-extend result.
# Reference: riscv-isa-manual/src/m-st-ext.adoc


@dataclass
class Mulw:
    """MULW - Multiply Word.

    Multiplies lower 32 bits of rs1 and rs2, sign-extends lower 32 bits
    of the product to 64 bits.
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return (f'mulw\t{reg_name(self.rd)},'
                f'{reg_name(self.rs1)},{reg_name(self.rs2)}')

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(
            self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(
            s.scalar.read_reg(self.rs1), byteorder='little',
            signed=False)
        val2 = int.from_bytes(
            s.scalar.read_reg(self.rs2), byteorder='little',
            signed=False)
        product = (val1 * val2) & 0xffffffff
        result = _sign_extend_32_to_64(product)
        result_bytes = (result & 0xffffffffffffffff).to_bytes(
            s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


@dataclass
class Divw:
    """DIVW - Divide Word (signed).

    Divides lower 32 bits of rs1 by lower 32 bits of rs2 (signed),
    sign-extends 32-bit quotient to 64 bits.
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return (f'divw\t{reg_name(self.rd)},'
                f'{reg_name(self.rs1)},{reg_name(self.rs2)}')

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(
            self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(
            s.scalar.read_reg(self.rs1), byteorder='little',
            signed=False)
        val2 = int.from_bytes(
            s.scalar.read_reg(self.rs2), byteorder='little',
            signed=False)
        val1_s = _to_signed_32(val1)
        val2_s = _to_signed_32(val2)
        if val2_s == 0:
            result = 0xffffffffffffffff
        elif val1_s == -0x80000000 and val2_s == -1:
            result = _sign_extend_32_to_64(0x80000000)
        else:
            q = int(val1_s / val2_s)
            result = _sign_extend_32_to_64(q)
        result_bytes = (result & 0xffffffffffffffff).to_bytes(
            s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


@dataclass
class Divuw:
    """DIVUW - Divide Word Unsigned.

    Divides lower 32 bits of rs1 by lower 32 bits of rs2 (unsigned),
    sign-extends 32-bit quotient to 64 bits.
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return (f'divuw\t{reg_name(self.rd)},'
                f'{reg_name(self.rs1)},{reg_name(self.rs2)}')

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(
            self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(
            s.scalar.read_reg(self.rs1), byteorder='little',
            signed=False) & 0xffffffff
        val2 = int.from_bytes(
            s.scalar.read_reg(self.rs2), byteorder='little',
            signed=False) & 0xffffffff
        if val2 == 0:
            result = 0xffffffffffffffff
        else:
            result = _sign_extend_32_to_64(val1 // val2)
        result_bytes = (result & 0xffffffffffffffff).to_bytes(
            s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


@dataclass
class Remw:
    """REMW - Remainder Word (signed).

    Divides lower 32 bits of rs1 by lower 32 bits of rs2 (signed),
    sign-extends 32-bit remainder to 64 bits.
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return (f'remw\t{reg_name(self.rd)},'
                f'{reg_name(self.rs1)},{reg_name(self.rs2)}')

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(
            self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(
            s.scalar.read_reg(self.rs1), byteorder='little',
            signed=False)
        val2 = int.from_bytes(
            s.scalar.read_reg(self.rs2), byteorder='little',
            signed=False)
        val1_s = _to_signed_32(val1)
        val2_s = _to_signed_32(val2)
        if val2_s == 0:
            result = _sign_extend_32_to_64(val1)
        elif val1_s == -0x80000000 and val2_s == -1:
            result = 0
        else:
            r = val1_s - (int(val1_s / val2_s) * val2_s)
            result = _sign_extend_32_to_64(r)
        result_bytes = (result & 0xffffffffffffffff).to_bytes(
            s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)


@dataclass
class Remuw:
    """REMUW - Remainder Word Unsigned.

    Divides lower 32 bits of rs1 by lower 32 bits of rs2 (unsigned),
    sign-extends 32-bit remainder to 64 bits.
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return (f'remuw\t{reg_name(self.rd)},'
                f'{reg_name(self.rs1)},{reg_name(self.rs2)}')

    async def update_state(self, s: 'Lamlet'):
        await s.scalar.wait_all_regs_ready(
            self.rd, None, [self.rs1, self.rs2], [])
        s.pc += 4
        val1 = int.from_bytes(
            s.scalar.read_reg(self.rs1), byteorder='little',
            signed=False) & 0xffffffff
        val2 = int.from_bytes(
            s.scalar.read_reg(self.rs2), byteorder='little',
            signed=False) & 0xffffffff
        if val2 == 0:
            result = _sign_extend_32_to_64(val1)
        else:
            result = _sign_extend_32_to_64(val1 % val2)
        result_bytes = (result & 0xffffffffffffffff).to_bytes(
            s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
