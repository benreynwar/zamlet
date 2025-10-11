"""Base integer instructions from RV32I and RV64I.

Reference: riscv-isa-manual/src/rv32.adoc, rv64.adoc
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import state

from register_names import reg_name


@dataclass
class Addi:
    """ADDI - Add Immediate.

    Adds the sign-extended 12-bit immediate to register rs1.
    Arithmetic overflow is ignored.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        if self.rs1 == 0:
            return f'li\t{reg_name(self.rd)},{self.imm}'
        elif self.imm == 0:
            return f'mv\t{reg_name(self.rd)},{reg_name(self.rs1)}'
        else:
            return f'addi\t{reg_name(self.rd)},{reg_name(self.rs1)},{self.imm}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rs1) + self.imm)
        s.pc += 4


@dataclass
class Andi:
    """ANDI - AND Immediate.

    Performs bitwise AND on register rs1 and sign-extended 12-bit immediate.
    Result is written to rd.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        if self.imm == 255:
            return f'zext.b\t{reg_name(self.rd)},{reg_name(self.rs1)}'
        else:
            return f'andi\t{reg_name(self.rd)},{reg_name(self.rs1)},{self.imm}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rs1) & self.imm)
        s.pc += 4


@dataclass
class Ori:
    """ORI - OR Immediate.

    Performs bitwise OR on register rs1 and sign-extended 12-bit immediate.
    Result is written to rd.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'ori\t{reg_name(self.rd)},{reg_name(self.rs1)},{self.imm}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rs1) | self.imm)
        s.pc += 4


@dataclass
class Xori:
    """XORI - XOR Immediate.

    Performs bitwise XOR on register rs1 and sign-extended 12-bit immediate.
    Result is written to rd.
    Note: XORI rd,rs1,-1 performs bitwise NOT (pseudo-op not).

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        if self.imm == -1:
            return f'not\t{reg_name(self.rd)},{reg_name(self.rs1)}'
        else:
            return f'xori\t{reg_name(self.rd)},{reg_name(self.rs1)},{self.imm}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rs1) ^ self.imm)
        s.pc += 4


@dataclass
class Slli:
    """SLLI - Shift Left Logical Immediate.

    Performs logical left shift of rs1 by shamt and writes result to rd.
    For RV64I, shamt is 6 bits (bits 25:20).

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    shamt: int

    def __str__(self):
        return f'slli\t{reg_name(self.rd)},{reg_name(self.rs1)},0x{self.shamt:x}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rs1) << self.shamt)
        s.pc += 4


@dataclass
class Add:
    """ADD - Add.

    Adds rs1 and rs2, writes result to rd. Overflow is ignored.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'add\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rs1) + s.scalar.read_reg(self.rs2))
        s.pc += 4


@dataclass
class Sub:
    """SUB - Subtract.

    Subtracts rs2 from rs1 and writes result to rd.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        if self.rs1 == 0:
            return f'neg\t{reg_name(self.rd)},{reg_name(self.rs2)}'
        else:
            return f'sub\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rs1) - s.scalar.read_reg(self.rs2))
        s.pc += 4


@dataclass
class And:
    """AND - Bitwise AND.

    Performs bitwise AND on rs1 and rs2, writes result to rd.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'and\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rs1) & s.scalar.read_reg(self.rs2))
        s.pc += 4


@dataclass
class Or:
    """OR - Bitwise OR.

    Performs bitwise OR on rs1 and rs2, writes result to rd.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'or\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rs1) | s.scalar.read_reg(self.rs2))
        s.pc += 4


@dataclass
class Xor:
    """XOR - Bitwise XOR.

    Performs bitwise XOR on rs1 and rs2, writes result to rd.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'xor\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rs1) ^ s.scalar.read_reg(self.rs2))
        s.pc += 4


@dataclass
class Lui:
    """LUI - Load Upper Immediate.

    Loads a 20-bit immediate into the upper 20 bits of rd, filling the lower
    12 bits with zeros. Used to build 32-bit constants.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    imm: int

    def __str__(self):
        return f'lui\t{reg_name(self.rd)},0x{self.imm & 0xfffff:x}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        value = self.imm << 12
        if value & 0x80000000:
            value = value - 0x100000000
        s.scalar.write_reg(self.rd, value)


@dataclass
class Addiw:
    """ADDIW - Add Immediate Word (RV64I).

    Adds sign-extended 12-bit immediate to rs1, produces 32-bit result,
    sign-extended to 64 bits and written to rd.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        if self.imm == 0:
            return f'sext.w\t{reg_name(self.rd)},{reg_name(self.rs1)}'
        else:
            return f'addiw\t{reg_name(self.rd)},{reg_name(self.rs1)},{self.imm}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        result = (s.scalar.read_reg(self.rs1) + self.imm) & 0xffffffff
        if result & 0x80000000:
            result = result - 0x100000000
        s.scalar.write_reg(self.rd, result)


@dataclass
class Addw:
    """ADDW - Add Word (RV64I).

    Adds rs1 and rs2, produces 32-bit result,
    sign-extended to 64 bits and written to rd.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'addw\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        result = (s.scalar.read_reg(self.rs1) + s.scalar.read_reg(self.rs2)) & 0xffffffff
        if result & 0x80000000:
            result = result - 0x100000000
        s.scalar.write_reg(self.rd, result)


@dataclass
class Subw:
    """SUBW - Subtract Word (RV64I).

    Subtracts rs2 from rs1, produces 32-bit result,
    sign-extended to 64 bits and written to rd.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'subw\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        result = (s.scalar.read_reg(self.rs1) - s.scalar.read_reg(self.rs2)) & 0xffffffff
        if result & 0x80000000:
            result = result - 0x100000000
        s.scalar.write_reg(self.rd, result)


@dataclass
class Slliw:
    """SLLIW - Shift Left Logical Immediate Word (RV64I).

    Logical left shift of lower 32 bits of rs1 by shamt,
    sign-extended to 64 bits and written to rd.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rd: int
    rs1: int
    shamt: int

    def __str__(self):
        return f'slliw\t{reg_name(self.rd)},{reg_name(self.rs1)},0x{self.shamt:x}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val = s.scalar.read_reg(self.rs1) & 0xffffffff
        result = (val << self.shamt) & 0xffffffff
        if result & 0x80000000:
            result = result - 0x100000000
        s.scalar.write_reg(self.rd, result)


@dataclass
class Srliw:
    """SRLIW - Shift Right Logical Immediate Word (RV64I).

    Logical right shift of lower 32 bits of rs1 by shamt,
    sign-extended to 64 bits and written to rd.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rd: int
    rs1: int
    shamt: int

    def __str__(self):
        return f'srliw\t{reg_name(self.rd)},{reg_name(self.rs1)},0x{self.shamt:x}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val = s.scalar.read_reg(self.rs1) & 0xffffffff
        result = (val >> self.shamt) & 0xffffffff
        if result & 0x80000000:
            result = result - 0x100000000
        s.scalar.write_reg(self.rd, result)


@dataclass
class Sraiw:
    """SRAIW - Shift Right Arithmetic Immediate Word (RV64I).

    Arithmetic right shift of lower 32 bits of rs1 by shamt,
    sign-extended to 64 bits and written to rd.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rd: int
    rs1: int
    shamt: int

    def __str__(self):
        return f'sraiw\t{reg_name(self.rd)},{reg_name(self.rs1)},0x{self.shamt:x}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val = s.scalar.read_reg(self.rs1) & 0xffffffff
        if val & 0x80000000:
            val = val | 0xffffffff00000000
        result = (val >> self.shamt) & 0xffffffff
        if result & 0x80000000:
            result = result - 0x100000000
        s.scalar.write_reg(self.rd, result)


@dataclass
class Sllw:
    """SLLW - Shift Left Logical Word (RV64I).

    Logical left shift of lower 32 bits of rs1 by rs2[4:0],
    sign-extended to 64 bits and written to rd.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'sllw\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val = s.scalar.read_reg(self.rs1) & 0xffffffff
        shamt = s.scalar.read_reg(self.rs2) & 0x1f
        result = (val << shamt) & 0xffffffff
        if result & 0x80000000:
            result = result - 0x100000000
        s.scalar.write_reg(self.rd, result)


@dataclass
class Srlw:
    """SRLW - Shift Right Logical Word (RV64I).

    Logical right shift of lower 32 bits of rs1 by rs2[4:0],
    sign-extended to 64 bits and written to rd.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'srlw\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val = s.scalar.read_reg(self.rs1) & 0xffffffff
        shamt = s.scalar.read_reg(self.rs2) & 0x1f
        result = (val >> shamt) & 0xffffffff
        if result & 0x80000000:
            result = result - 0x100000000
        s.scalar.write_reg(self.rd, result)


@dataclass
class Sraw:
    """SRAW - Shift Right Arithmetic Word (RV64I).

    Arithmetic right shift of lower 32 bits of rs1 by rs2[4:0],
    sign-extended to 64 bits and written to rd.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'sraw\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val = s.scalar.read_reg(self.rs1) & 0xffffffff
        if val & 0x80000000:
            val = val | 0xffffffff00000000
        shamt = s.scalar.read_reg(self.rs2) & 0x1f
        result = (val >> shamt) & 0xffffffff
        if result & 0x80000000:
            result = result - 0x100000000
        s.scalar.write_reg(self.rd, result)


@dataclass
class Slti:
    """SLTI - Set Less Than Immediate (signed).

    Sets rd to 1 if rs1 < imm (signed comparison), else 0.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'slti\t{reg_name(self.rd)},{reg_name(self.rs1)},{self.imm}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val = s.scalar.read_reg(self.rs1)
        if val & 0x8000000000000000:
            val = val - 0x10000000000000000
        s.scalar.write_reg(self.rd, 1 if val < self.imm else 0)


@dataclass
class Sltiu:
    """SLTIU - Set Less Than Immediate Unsigned.

    Sets rd to 1 if rs1 < imm (unsigned comparison), else 0.
    Note: SLTIU rd,rs1,1 sets rd to 1 if rs1==0 (pseudo-op seqz).

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        if self.imm == 1:
            return f'seqz\t{reg_name(self.rd)},{reg_name(self.rs1)}'
        else:
            return f'sltiu\t{reg_name(self.rd)},{reg_name(self.rs1)},{self.imm}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val = s.scalar.read_reg(self.rs1)
        # Immediate is sign-extended then compared unsigned
        imm_unsigned = self.imm if self.imm >= 0 else self.imm + 0x10000000000000000
        s.scalar.write_reg(self.rd, 1 if val < imm_unsigned else 0)


@dataclass
class Slt:
    """SLT - Set Less Than (signed).

    Sets rd to 1 if rs1 < rs2 (signed comparison), else 0.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        if self.rs2 == 0:
            return f'sltz\t{reg_name(self.rd)},{reg_name(self.rs1)}'
        else:
            return f'slt\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        if val1 & 0x8000000000000000:
            val1 = val1 - 0x10000000000000000
        if val2 & 0x8000000000000000:
            val2 = val2 - 0x10000000000000000
        s.scalar.write_reg(self.rd, 1 if val1 < val2 else 0)


@dataclass
class Sltu:
    """SLTU - Set Less Than Unsigned.

    Sets rd to 1 if rs1 < rs2 (unsigned comparison), else 0.
    Note: SLTU rd,x0,rs2 sets rd to 1 if rs2!=0 (pseudo-op snez).

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        if self.rs1 == 0:
            return f'snez\t{reg_name(self.rd)},{reg_name(self.rs2)}'
        else:
            return f'sltu\t{reg_name(self.rd)},{reg_name(self.rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 4
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        s.scalar.write_reg(self.rd, 1 if val1 < val2 else 0)
