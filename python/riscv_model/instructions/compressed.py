"""Compressed (RVC) instructions.

Reference: riscv-isa-manual/src/c-st-ext.adoc
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import state

from register_names import reg_name
from instructions.control_flow import format_branch_target


logger = logging.getLogger(__name__)


@dataclass
class CNop:
    """C.NOP - Compressed No Operation instruction.

    Does not change any user-visible state except advancing PC.
    Expands to: nop (addi x0, x0, 0)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """

    def __str__(self):
        return 'nop'

    def update_state(self, s: 'state.State'):
        s.pc += 2


@dataclass
class CAddi4spn:
    """C.ADDI4SPN - Compressed Add Immediate (scaled by 4) to SP, Non-destructive.

    Adds a zero-extended immediate (scaled by 4) to stack pointer x2,
    and writes result to rd'. Used to generate pointers to stack-allocated variables.
    Expands to: addi rd', x2, nzuimm[9:2]

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    imm: int

    def __str__(self):
        return f'addi\t{reg_name(self.rd)},sp,{self.imm}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd, s.scalar.read_reg(2) + self.imm)


@dataclass
class CAddi:
    """C.ADDI - Compressed Add Immediate instruction.

    Adds sign-extended 6-bit immediate to rd and writes result to rd.
    Expands to: addi rd, rd, imm

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    imm: int

    def __str__(self):
        return f'addi\t{reg_name(self.rd)},{reg_name(self.rd)},{self.imm}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rd) + self.imm)


@dataclass
class CLi:
    """C.LI - Compressed Load Immediate instruction.

    Loads a sign-extended 6-bit immediate into register rd.
    Expands to: addi rd, x0, imm

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    imm: int

    def __str__(self):
        return f'li\t{reg_name(self.rd)},{self.imm}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd, self.imm)


@dataclass
class CAddiw:
    """C.ADDIW - Compressed Add Immediate Word (RV64C).

    Adds sign-extended 6-bit immediate to rd, produces 32-bit result,
    sign-extended to 64 bits. When imm=0, this is sext.w rd.
    Expands to: addiw rd, rd, imm

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    imm: int

    def __str__(self):
        if self.imm == 0:
            return f'sext.w\t{reg_name(self.rd)}'
        else:
            return f'addiw\t{reg_name(self.rd)},{reg_name(self.rd)},{self.imm}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        result = (s.scalar.read_reg(self.rd) + self.imm) & 0xffffffff
        if result & 0x80000000:
            result = result | 0xffffffff00000000
        s.scalar.write_reg(self.rd, result)


@dataclass
class CLui:
    """C.LUI - Compressed Load Upper Immediate instruction.

    Loads a non-zero 6-bit immediate into bits 17-12 of register rd.
    Expands to: lui rd, nzimm

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    imm: int

    def __str__(self):
        return f'lui\t{reg_name(self.rd)},0x{self.imm:x}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd, self.imm << 12)


@dataclass
class CAddi16sp:
    """C.ADDI16SP - Compressed Add Immediate to Stack Pointer.

    Adds a non-zero sign-extended 6-bit immediate (scaled by 16) to sp.
    Immediate range is [-512, 496].
    Expands to: addi x2, x2, nzimm[9:4]

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    imm: int

    def __str__(self):
        return f'addi\tsp,sp,{self.imm}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(2, s.scalar.read_reg(2) + self.imm)


@dataclass
class CMv:
    """C.MV - Compressed Move instruction.

    Copies the value in register rs2 into register rd.
    Expands to: add rd, x0, rs2

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    rs2: int

    def __str__(self):
        return f'mv\t{reg_name(self.rd)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rs2))


@dataclass
class CAdd:
    """C.ADD - Compressed Add instruction.

    Adds the values in registers rd and rs2 and writes result to rd.
    Expands to: add rd, rd, rs2

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    rs2: int

    def __str__(self):
        return f'add\t{reg_name(self.rd)},{reg_name(self.rd)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rd) + s.scalar.read_reg(self.rs2))


@dataclass
class CSlli:
    """C.SLLI - Compressed Shift Left Logical Immediate.

    Performs a logical left shift of the value in register rd by shamt.
    Expands to: slli rd, rd, shamt[5:0]

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    shamt: int

    def __str__(self):
        return f'slli\t{reg_name(self.rd)},{reg_name(self.rd)},0x{self.shamt:x}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd, s.scalar.read_reg(self.rd) << self.shamt)


@dataclass
class CSub:
    """C.SUB - Compressed Subtract instruction.

    Subtracts rs2' from rd'/rs1' and writes result to rd'.
    Expands to: sub rd', rd', rs2'

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd_rs1: int
    rs2: int

    def __str__(self):
        return f'sub\t{reg_name(self.rd_rs1)},{reg_name(self.rd_rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd_rs1, s.scalar.read_reg(self.rd_rs1) - s.scalar.read_reg(self.rs2))


@dataclass
class CXor:
    """C.XOR - Compressed XOR instruction.

    XORs rd'/rs1' and rs2', writes result to rd'.
    Expands to: xor rd', rd', rs2'

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd_rs1: int
    rs2: int

    def __str__(self):
        return f'xor\t{reg_name(self.rd_rs1)},{reg_name(self.rd_rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd_rs1, s.scalar.read_reg(self.rd_rs1) ^ s.scalar.read_reg(self.rs2))


@dataclass
class COr:
    """C.OR - Compressed OR instruction.

    ORs rd'/rs1' and rs2', writes result to rd'.
    Expands to: or rd', rd', rs2'

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd_rs1: int
    rs2: int

    def __str__(self):
        return f'or\t{reg_name(self.rd_rs1)},{reg_name(self.rd_rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd_rs1, s.scalar.read_reg(self.rd_rs1) | s.scalar.read_reg(self.rs2))


@dataclass
class CAnd:
    """C.AND - Compressed AND instruction.

    ANDs rd'/rs1' and rs2', writes result to rd'.
    Expands to: and rd', rd', rs2'

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd_rs1: int
    rs2: int

    def __str__(self):
        return f'and\t{reg_name(self.rd_rs1)},{reg_name(self.rd_rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd_rs1, s.scalar.read_reg(self.rd_rs1) & s.scalar.read_reg(self.rs2))


@dataclass
class CAndi:
    """C.ANDI - Compressed AND Immediate instruction.

    Performs bitwise AND on rd'/rs1' and sign-extended 6-bit immediate.
    Expands to: andi rd', rd', imm

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd_rs1: int
    imm: int

    def __str__(self):
        return f'andi\t{reg_name(self.rd_rs1)},{reg_name(self.rd_rs1)},{self.imm}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd_rs1, s.scalar.read_reg(self.rd_rs1) & self.imm)


@dataclass
class CSrli:
    """C.SRLI - Compressed Shift Right Logical Immediate.

    Performs logical right shift of rd'/rs1' by shamt.
    Expands to: srli rd', rd', shamt

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd_rs1: int
    shamt: int

    def __str__(self):
        return f'srli\t{reg_name(self.rd_rs1)},{reg_name(self.rd_rs1)},{self.shamt}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        s.scalar.write_reg(self.rd_rs1, s.scalar.read_reg(self.rd_rs1) >> self.shamt)


@dataclass
class CSrai:
    """C.SRAI - Compressed Shift Right Arithmetic Immediate.

    Performs arithmetic right shift of rd'/rs1' by shamt.
    Expands to: srai rd', rd', shamt

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd_rs1: int
    shamt: int

    def __str__(self):
        return f'srai\t{reg_name(self.rd_rs1)},{reg_name(self.rd_rs1)},{self.shamt}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        val = s.scalar.read_reg(self.rd_rs1)
        if val & 0x8000000000000000:
            val = val - 0x10000000000000000
        result = val >> self.shamt
        s.scalar.write_reg(self.rd_rs1, result)


@dataclass
class CJ:
    """C.J - Compressed Jump (unconditional).

    Jumps to PC + sign-extended offset.
    Expands to: jal x0, offset

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    offset: int

    def __str__(self):
        return f'j\t{self.offset}'

    def disasm(self, pc):
        """Disassemble with PC for absolute address calculation."""
        target = format_branch_target(pc, self.offset)
        return f'j\t{target}'

    def update_state(self, s: 'state.State'):
        s.pc += self.offset


@dataclass
class CBeqz:
    """C.BEQZ - Compressed Branch if Equal to Zero.

    Branches to PC + offset if rs1' equals zero.
    Expands to: beq rs1', x0, offset

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rs1: int
    offset: int

    def __str__(self):
        return f'beqz\t{reg_name(self.rs1)},{hex(self.offset)}'

    def disasm(self, pc):
        """Disassemble with PC for absolute address calculation."""
        target = format_branch_target(pc, self.offset)
        return f'beqz\t{reg_name(self.rs1)},{target}'

    def update_state(self, s: 'state.State'):
        if s.scalar.read_reg(self.rs1) == 0:
            s.pc += self.offset
        else:
            s.pc += 2


@dataclass
class CBnez:
    """C.BNEZ - Compressed Branch if Not Equal to Zero.

    Branches to PC + offset if rs1' is not zero.
    Expands to: bne rs1', x0, offset

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rs1: int
    offset: int

    def __str__(self):
        return f'bnez\t{reg_name(self.rs1)},{hex(self.offset)}'

    def disasm(self, pc):
        """Disassemble with PC for absolute address calculation."""
        target = format_branch_target(pc, self.offset)
        return f'bnez\t{reg_name(self.rs1)},{target}'

    def update_state(self, s: 'state.State'):
        if s.scalar.read_reg(self.rs1) != 0:
            s.pc += self.offset
        else:
            s.pc += 2


@dataclass
class CSdsp:
    """C.SDSP - Compressed Store Doubleword from Stack Pointer (RV64C).

    Stores a 64-bit value from rs2 to memory at sp + offset*8.
    Expands to: sd rs2, offset(x2)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rs2: int
    offset: int

    def __str__(self):
        return f'sd\t{reg_name(self.rs2)},{self.offset}(sp)'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        sp = s.scalar.read_reg(2)
        address = sp + self.offset
        value = s.scalar.read_reg(self.rs2)
        logger.debug(f'C.SDSP: sp=0x{sp:016x}, offset={self.offset}, '
                     f'address=0x{address:016x}, rs2={self.rs2}, value=0x{value:016x}')
        data = value.to_bytes(8, byteorder='little')
        s.set_memory(address, data)


@dataclass
class CSwsp:
    """C.SWSP - Compressed Store Word to Stack Pointer (RV32C/RV64C).

    Stores a 32-bit value from rs2 to memory at sp + offset*4.
    Expands to: sw rs2, offset(x2)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rs2: int
    offset: int

    def __str__(self):
        return f'sw\t{reg_name(self.rs2)},{self.offset}(sp)'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        sp = s.scalar.read_reg(2)
        address = sp + self.offset
        value = s.scalar.read_reg(self.rs2) & 0xffffffff
        data = value.to_bytes(4, byteorder='little')
        s.set_memory(address, data)


@dataclass
class CLwsp:
    """C.LWSP - Compressed Load Word from Stack Pointer (RV32C/RV64C).

    Loads a 32-bit value from memory at sp + offset*4 into rd, sign-extended to 64 bits.
    Expands to: lw rd, offset(x2)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    offset: int

    def __str__(self):
        return f'lw\t{reg_name(self.rd)},{self.offset}(sp)'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        sp = s.scalar.read_reg(2)
        address = sp + self.offset
        data = s.get_memory(address, 4)
        value = int.from_bytes(data, byteorder='little')
        if value & 0x80000000:
            value = value | 0xffffffff00000000
        s.scalar.write_reg(self.rd, value)


@dataclass
class CLdsp:
    """C.LDSP - Compressed Load Doubleword from Stack Pointer (RV64C).

    Loads a 64-bit value from memory at sp + offset*8 into rd.
    Expands to: ld rd, offset(x2)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    offset: int

    def __str__(self):
        return f'ld\t{reg_name(self.rd)},{self.offset}(sp)'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        sp = s.scalar.read_reg(2)
        address = sp + self.offset
        data = s.get_memory(address, 8)
        value = int.from_bytes(data, byteorder='little')
        s.scalar.write_reg(self.rd, value)


@dataclass
class CLw:
    """C.LW - Compressed Load Word (RV32C/RV64C).

    Loads a 32-bit value from memory at rs1 + offset into rd, sign-extended to 64 bits.
    The offset is zero-extended and scaled by 4.
    Expands to: lw rd, offset(rs1)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    rs1: int
    offset: int

    def __str__(self):
        return f'lw\t{reg_name(self.rd)},{self.offset}({reg_name(self.rs1)})'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        address = s.scalar.read_reg(self.rs1) + self.offset
        data = s.get_memory(address, 4)
        value = int.from_bytes(data, byteorder='little')
        if value & 0x80000000:
            value = value | 0xffffffff00000000
        s.scalar.write_reg(self.rd, value)


@dataclass
class CLd:
    """C.LD - Compressed Load Doubleword (RV64C).

    Loads a 64-bit value from memory at rs1 + offset into rd.
    The offset is zero-extended and scaled by 8.
    Expands to: ld rd, offset(rs1)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd: int
    rs1: int
    offset: int

    def __str__(self):
        return f'ld\t{reg_name(self.rd)},{self.offset}({reg_name(self.rs1)})'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        address = s.scalar.read_reg(self.rs1) + self.offset
        data = s.get_memory(address, 8)
        value = int.from_bytes(data, byteorder='little')
        s.scalar.write_reg(self.rd, value)


@dataclass
class CSw:
    """C.SW - Compressed Store Word (RV32C/RV64C).

    Stores a 32-bit value from rs2 to memory at rs1 + offset.
    The offset is zero-extended and scaled by 4.
    Expands to: sw rs2, offset(rs1)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rs1: int
    rs2: int
    offset: int

    def __str__(self):
        return f'sw\t{reg_name(self.rs2)},{self.offset}({reg_name(self.rs1)})'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        address = s.scalar.read_reg(self.rs1) + self.offset
        value = s.scalar.read_reg(self.rs2) & 0xffffffff
        data = value.to_bytes(4, byteorder='little')
        s.set_memory(address, data)


@dataclass
class CSd:
    """C.SD - Compressed Store Doubleword (RV64C).

    Stores a 64-bit value from rs2 to memory at rs1 + offset.
    The offset is zero-extended and scaled by 8.
    Expands to: sd rs2, offset(rs1)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rs1: int
    rs2: int
    offset: int

    def __str__(self):
        return f'sd\t{reg_name(self.rs2)},{self.offset}({reg_name(self.rs1)})'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        address = s.scalar.read_reg(self.rs1) + self.offset
        value = s.scalar.read_reg(self.rs2)
        data = value.to_bytes(8, byteorder='little')
        s.set_memory(address, data)


@dataclass
class CAddw:
    """C.ADDW - Compressed Add Word (RV64C).

    Adds values in rd'/rs1' and rs2', sign-extends lower 32 bits, writes to rd'.
    Expands to: addw rd', rd', rs2'

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd_rs1: int
    rs2: int

    def __str__(self):
        return f'addw\t{reg_name(self.rd_rs1)},{reg_name(self.rd_rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        result = (s.scalar.read_reg(self.rd_rs1) + s.scalar.read_reg(self.rs2)) & 0xffffffff
        if result & 0x80000000:
            result = result | 0xffffffff00000000
        s.scalar.write_reg(self.rd_rs1, result)


@dataclass
class CSubw:
    """C.SUBW - Compressed Subtract Word (RV64C).

    Subtracts rs2' from rd'/rs1', sign-extends lower 32 bits, writes to rd'.
    Expands to: subw rd', rd', rs2'

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rd_rs1: int
    rs2: int

    def __str__(self):
        return f'subw\t{reg_name(self.rd_rs1)},{reg_name(self.rd_rs1)},{reg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        s.pc += 2
        result = (s.scalar.read_reg(self.rd_rs1) - s.scalar.read_reg(self.rs2)) & 0xffffffff
        if result & 0x80000000:
            result = result | 0xffffffff00000000
        s.scalar.write_reg(self.rd_rs1, result)


@dataclass
class CJr:
    """C.JR - Compressed Jump Register instruction.

    Performs an unconditional control transfer to the address in register rs1.
    Expands to: jalr x0, 0(rs1)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rs1: int

    def __str__(self):
        if self.rs1 == 1:
            return 'ret'
        else:
            return f'jr\t{reg_name(self.rs1)}'

    def update_state(self, s: 'state.State'):
        s.pc = s.scalar.read_reg(self.rs1)


@dataclass
class CJalr:
    """C.JALR - Compressed Jump And Link Register instruction.

    Performs an unconditional control transfer to the address in register rs1,
    and writes the address of the instruction following the jump (pc+2) to x1.
    Expands to: jalr x1, 0(rs1)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rs1: int

    def __str__(self):
        return f'jalr\t{reg_name(self.rs1)}'

    def update_state(self, s: 'state.State'):
        target = s.scalar.read_reg(self.rs1)
        s.scalar.write_reg(1, s.pc + 2)
        s.pc = target


@dataclass
class CEbreak:
    """C.EBREAK - Compressed Breakpoint instruction.

    Causes control to be transferred back to the debugging environment.
    Expands to: ebreak

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """

    def __str__(self):
        return 'ebreak'

    def update_state(self, s: 'state.State'):
        raise NotImplementedError('C.EBREAK not implemented')
