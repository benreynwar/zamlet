"""Control flow instructions: branches and jumps.

Reference: riscv-isa-manual/src/rv32.adoc
"""

from dataclasses import dataclass

from zamlet.register_names import reg_name


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [])
        result = s.pc + (self.imm << 12)
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [])
        result = s.pc + 4
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        val1 = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        val2 = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        if val1 >= val2:
            s.pc += self.imm
        else:
            s.pc += 4
