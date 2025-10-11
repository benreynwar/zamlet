"""Control flow instructions: branches and jumps.

Reference: riscv-isa-manual/src/rv32.adoc
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import state

from register_names import reg_name


def format_branch_target(pc, offset):
    """Format branch target as absolute address like objdump does."""
    target = pc + offset
    return f'{target:x}'


@dataclass
class Auipc:
    """AUIPC - Add Upper Immediate to PC.

    Forms a 32-bit offset from the 20-bit U-immediate (filling lower 12 bits with zeros),
    adds this offset to the PC of the AUIPC instruction, and places the result in rd.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    imm: int

    def __str__(self):
        return f'auipc\t{reg_name(self.rd)},0x{self.imm & 0xfffff:x}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.pc + (self.imm << 12))
        s.pc += 4


@dataclass
class Jal:
    """JAL - Jump and Link.

    Jumps to PC + sign-extended offset and stores return address (PC+4) in rd.
    The offset is a multiple of 2 bytes.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    imm: int

    def __str__(self):
        if self.rd == 0:
            return f'j\t{hex(self.imm)}'
        else:
            return f'jal\t{reg_name(self.rd)},{hex(self.imm)}'

    def disasm(self, pc):
        """Disassemble with PC for absolute address calculation."""
        target = format_branch_target(pc, self.imm)
        if self.rd == 0:
            return f'j\t{target}'
        elif self.rd == 1:
            # Pseudo-instruction: jal offset when rd=ra (common function call)
            return f'jal\t{target}'
        else:
            return f'jal\t{reg_name(self.rd)},{target}'

    def update_state(self, s: 'state.State'):
        s.scalar.write_reg(self.rd, s.pc + 4)
        s.pc += self.imm


@dataclass
class Beq:
    """BEQ - Branch if Equal.

    Takes the branch if rs1 == rs2.
    Target address is pc + sign-extended offset.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rs1: int
    rs2: int
    imm: int

    def __str__(self):
        return f'beq\t{reg_name(self.rs1)},{reg_name(self.rs2)},{hex(self.imm)}'

    def disasm(self, pc):
        """Disassemble with PC for absolute address calculation."""
        target = format_branch_target(pc, self.imm)
        if self.rs2 == 0:
            return f'beqz\t{reg_name(self.rs1)},{target}'
        else:
            return f'beq\t{reg_name(self.rs1)},{reg_name(self.rs2)},{target}'

    def update_state(self, s: 'state.State'):
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        if val1 == val2:
            s.pc += self.imm
        else:
            s.pc += 4


@dataclass
class Bne:
    """BNE - Branch if Not Equal.

    Takes the branch if rs1 != rs2.
    Target address is pc + sign-extended offset.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rs1: int
    rs2: int
    imm: int

    def __str__(self):
        return f'bne\t{reg_name(self.rs1)},{reg_name(self.rs2)},{hex(self.imm)}'

    def disasm(self, pc):
        """Disassemble with PC for absolute address calculation."""
        target = format_branch_target(pc, self.imm)
        if self.rs2 == 0:
            return f'bnez\t{reg_name(self.rs1)},{target}'
        else:
            return f'bne\t{reg_name(self.rs1)},{reg_name(self.rs2)},{target}'

    def update_state(self, s: 'state.State'):
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        if val1 != val2:
            s.pc += self.imm
        else:
            s.pc += 4


@dataclass
class Blt:
    """BLT - Branch if Less Than (signed comparison).

    Takes the branch if rs1 < rs2 (signed comparison).
    Target address is pc + sign-extended offset.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rs1: int
    rs2: int
    imm: int

    def __str__(self):
        if self.rs1 == 0 and self.rs2 != 0:
            return f'bgtz\t{reg_name(self.rs2)},{hex(self.imm)}'
        elif self.rs2 == 0:
            return f'bltz\t{reg_name(self.rs1)},{hex(self.imm)}'
        else:
            return f'blt\t{reg_name(self.rs1)},{reg_name(self.rs2)},{hex(self.imm)}'

    def disasm(self, pc):
        """Disassemble with PC for absolute address calculation."""
        target = format_branch_target(pc, self.imm)
        if self.rs1 == 0 and self.rs2 != 0:
            return f'bgtz\t{reg_name(self.rs2)},{target}'
        elif self.rs2 == 0:
            return f'bltz\t{reg_name(self.rs1)},{target}'
        else:
            return f'blt\t{reg_name(self.rs1)},{reg_name(self.rs2)},{target}'

    def update_state(self, s: 'state.State'):
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        if val1 & 0x8000000000000000:
            val1 = val1 - 0x10000000000000000
        if val2 & 0x8000000000000000:
            val2 = val2 - 0x10000000000000000
        if val1 < val2:
            s.pc += self.imm
        else:
            s.pc += 4


@dataclass
class Bge:
    """BGE - Branch if Greater or Equal (signed comparison).

    Takes the branch if rs1 >= rs2 (signed comparison).
    Target address is pc + sign-extended offset.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rs1: int
    rs2: int
    imm: int

    def __str__(self):
        if self.rs1 == 0 and self.rs2 != 0:
            return f'blez\t{reg_name(self.rs2)},{hex(self.imm)}'
        elif self.rs2 == 0:
            return f'bgez\t{reg_name(self.rs1)},{hex(self.imm)}'
        else:
            return f'bge\t{reg_name(self.rs1)},{reg_name(self.rs2)},{hex(self.imm)}'

    def disasm(self, pc):
        """Disassemble with PC for absolute address calculation."""
        target = format_branch_target(pc, self.imm)
        if self.rs1 == 0 and self.rs2 != 0:
            return f'blez\t{reg_name(self.rs2)},{target}'
        elif self.rs2 == 0:
            return f'bgez\t{reg_name(self.rs1)},{target}'
        else:
            return f'bge\t{reg_name(self.rs1)},{reg_name(self.rs2)},{target}'

    def update_state(self, s: 'state.State'):
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        if val1 & 0x8000000000000000:
            val1 = val1 - 0x10000000000000000
        if val2 & 0x8000000000000000:
            val2 = val2 - 0x10000000000000000
        if val1 >= val2:
            s.pc += self.imm
        else:
            s.pc += 4


@dataclass
class Bltu:
    """BLTU - Branch if Less Than Unsigned.

    Takes the branch if rs1 < rs2 (unsigned comparison).
    Target address is pc + sign-extended offset.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rs1: int
    rs2: int
    imm: int

    def __str__(self):
        return f'bltu\t{reg_name(self.rs1)},{reg_name(self.rs2)},{hex(self.imm)}'

    def disasm(self, pc):
        """Disassemble with PC for absolute address calculation."""
        target = format_branch_target(pc, self.imm)
        return f'bltu\t{reg_name(self.rs1)},{reg_name(self.rs2)},{target}'

    def update_state(self, s: 'state.State'):
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        if val1 < val2:
            s.pc += self.imm
        else:
            s.pc += 4


@dataclass
class Bgeu:
    """BGEU - Branch if Greater or Equal Unsigned.

    Takes the branch if rs1 >= rs2 (unsigned comparison).
    Target address is pc + sign-extended offset.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rs1: int
    rs2: int
    imm: int

    def __str__(self):
        return f'bgeu\t{reg_name(self.rs1)},{reg_name(self.rs2)},{hex(self.imm)}'

    def disasm(self, pc):
        """Disassemble with PC for absolute address calculation."""
        target = format_branch_target(pc, self.imm)
        return f'bgeu\t{reg_name(self.rs1)},{reg_name(self.rs2)},{target}'

    def update_state(self, s: 'state.State'):
        val1 = s.scalar.read_reg(self.rs1)
        val2 = s.scalar.read_reg(self.rs2)
        if val1 >= val2:
            s.pc += self.imm
        else:
            s.pc += 4
