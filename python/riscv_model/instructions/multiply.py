"""M extension - Integer Multiply/Divide instructions.

Reference: riscv-isa-manual/src/m-st-ext.adoc
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import state

from register_names import reg_name


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        result = (val1 * val2) & 0xffffffffffffffff
        s.scalar.write_reg(self.rd, result)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        # Sign extend to handle signed multiplication
        if val1 & 0x8000000000000000:
            val1 = val1 - 0x10000000000000000
        if val2 & 0x8000000000000000:
            val2 = val2 - 0x10000000000000000
        result = (val1 * val2) >> 64
        s.scalar.write_reg(self.rd, result & 0xffffffffffffffff)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        # Sign extend val1 only
        if val1 & 0x8000000000000000:
            val1 = val1 - 0x10000000000000000
        result = (val1 * val2) >> 64
        s.scalar.write_reg(self.rd, result & 0xffffffffffffffff)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        result = (val1 * val2) >> 64
        s.scalar.write_reg(self.rd, result & 0xffffffffffffffff)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        # Sign extend for signed division
        if val1 & 0x8000000000000000:
            val1_signed = val1 - 0x10000000000000000
        else:
            val1_signed = val1
        if val2 & 0x8000000000000000:
            val2_signed = val2 - 0x10000000000000000
        else:
            val2_signed = val2
        if val2 == 0:
            result = 0xffffffffffffffff  # Division by zero: all bits set
        elif val1_signed == -0x8000000000000000 and val2_signed == -1:
            result = 0x8000000000000000  # Overflow: quotient equals dividend
        else:
            result = val1_signed // val2_signed
            result = result & 0xffffffffffffffff
        s.scalar.write_reg(self.rd, result)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        if val2 == 0:
            result = 0xffffffffffffffff  # Division by zero
        else:
            result = val1 // val2
        s.scalar.write_reg(self.rd, result & 0xffffffffffffffff)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        # Sign extend for signed remainder
        if val1 & 0x8000000000000000:
            val1_signed = val1 - 0x10000000000000000
        else:
            val1_signed = val1
        if val2 & 0x8000000000000000:
            val2_signed = val2 - 0x10000000000000000
        else:
            val2_signed = val2
        if val2 == 0:
            result = val1  # Division by zero: remainder equals dividend
        elif val1_signed == -0x8000000000000000 and val2_signed == -1:
            result = 0  # Overflow: remainder is zero
        else:
            result = val1_signed % val2_signed
            result = result & 0xffffffffffffffff
        s.scalar.write_reg(self.rd, result)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        if val2 == 0:
            result = val1  # Division by zero
        else:
            result = val1 % val2
        s.scalar.write_reg(self.rd, result & 0xffffffffffffffff)
