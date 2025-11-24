"""Compressed (RVC) instructions.

Reference: riscv-isa-manual/src/c-st-ext.adoc
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import state

from zamlet.register_names import reg_name, freg_name
from zamlet.instructions.control_flow import format_branch_target
from zamlet import utils


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

    async def update_state(self, s: 'state.State'):
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [2], [])
        sp_val = int.from_bytes(s.scalar.read_reg(2), byteorder='little', signed=False)
        result = sp_val + self.imm
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rd], [])
        rd_val = int.from_bytes(s.scalar.read_reg(self.rd), byteorder='little', signed=False)
        result = rd_val + self.imm
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [])
        bs = self.imm.to_bytes(s.params.word_bytes, byteorder='little', signed=True)
        s.scalar.write_reg(self.rd, bs)
        s.pc += 2


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
            return f'sext.w\t{reg_name(self.rd)},{reg_name(self.rd)}'
        else:
            return f'addiw\t{reg_name(self.rd)},{reg_name(self.rd)},{self.imm}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rd], [])
        rd_val = int.from_bytes(s.scalar.read_reg(self.rd), byteorder='little', signed=False)
        result = (rd_val + self.imm) & 0xffffffff
        if result & 0x80000000:
            result = result | 0xffffffff00000000
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        value = self.imm << 12
        data = value.to_bytes(s.params.word_bytes, byteorder='little', signed=True)
        s.scalar.write_reg(self.rd, data)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [2], [])
        sp_val = int.from_bytes(s.scalar.read_reg(2), byteorder='little', signed=False)
        result = sp_val + self.imm
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(2, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs2], [])
        rs2_bytes = s.scalar.read_reg(self.rs2)
        s.scalar.write_reg(self.rd, rs2_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rd, self.rs2], [])
        rd_val = int.from_bytes(s.scalar.read_reg(self.rd), byteorder='little', signed=False)
        rs2_val = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        result = (rd_val + rs2_val) & ((1 << (s.params.word_bytes * 8)) - 1)
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rd], [])
        rd_val = int.from_bytes(s.scalar.read_reg(self.rd), byteorder='little', signed=False)
        result = rd_val << self.shamt
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd_rs1, None, [self.rd_rs1, self.rs2], [])
        rd_val = int.from_bytes(s.scalar.read_reg(self.rd_rs1), byteorder='little', signed=False)
        rs2_val = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        result = rd_val - rs2_val
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd_rs1, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd_rs1, None, [self.rd_rs1, self.rs2], [])
        rd_val = int.from_bytes(s.scalar.read_reg(self.rd_rs1), byteorder='little', signed=False)
        rs2_val = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        result = rd_val ^ rs2_val
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd_rs1, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd_rs1, None, [self.rd_rs1, self.rs2], [])
        rd_val = int.from_bytes(s.scalar.read_reg(self.rd_rs1), byteorder='little', signed=False)
        rs2_val = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        result = rd_val | rs2_val
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd_rs1, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd_rs1, None, [self.rd_rs1, self.rs2], [])
        rd_val = int.from_bytes(s.scalar.read_reg(self.rd_rs1), byteorder='little', signed=False)
        rs2_val = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        result = rd_val & rs2_val
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd_rs1, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd_rs1, None, [self.rd_rs1], [])
        rd_val = int.from_bytes(s.scalar.read_reg(self.rd_rs1), byteorder='little', signed=False)
        result = rd_val & self.imm
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd_rs1, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd_rs1, None, [self.rd_rs1], [])
        val = int.from_bytes(s.scalar.read_reg(self.rd_rs1), byteorder='little', signed=False)
        result = val >> self.shamt
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd_rs1, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd_rs1, None, [self.rd_rs1], [])
        val = int.from_bytes(s.scalar.read_reg(self.rd_rs1), byteorder='little', signed=True)
        result = val >> self.shamt
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=True)
        s.scalar.write_reg(self.rd_rs1, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_val = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        if rs1_val == 0:
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_val = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        if rs1_val != 0:
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [2, self.rs2], [])
        sp_bytes = s.scalar.read_reg(2)
        sp = int.from_bytes(sp_bytes, byteorder='little', signed=False)
        address = sp + self.offset
        value_bytes = s.scalar.read_reg(self.rs2)
        value = int.from_bytes(value_bytes, byteorder='little', signed=False)
        logger.debug(f'C.SDSP: sp=0x{sp:016x}, offset={self.offset}, '
                     f'address=0x{address:016x}, rs2={self.rs2}, value=0x{value:016x}')
        await s.set_memory(address, value_bytes[:8])
        s.pc += 2


@dataclass
class CFldsp:
    """C.FLDSP - Compressed Floating-Point Load Double from Stack Pointer (RV32DC/RV64DC).

    Loads a double-precision floating-point value from memory at sp + offset*8
    into floating-point register fd.
    Expands to: fld fd, offset(x2)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    fd: int
    offset: int

    def __str__(self):
        return f'fld\t{freg_name(self.fd)},{self.offset}(sp)'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, self.fd, [2], [])
        sp_bytes = s.scalar.read_reg(2)
        sp = int.from_bytes(sp_bytes, byteorder='little', signed=False)
        address = sp + self.offset
        data_future = await s.get_memory(address, 8)
        s.scalar.write_freg_future(self.fd, data_future)
        s.pc += 2


@dataclass
class CFsdsp:
    """C.FSDSP - Compressed Floating-Point Store Double to Stack Pointer (RV32DC/RV64DC).

    Stores a double-precision floating-point value from floating-point register
    fs2 to memory at sp + offset*8.
    Expands to: fsd fs2, offset(x2)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    fs2: int
    offset: int

    def __str__(self):
        return f'fsd\t{freg_name(self.fs2)},{self.offset}(sp)'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [2], [self.fs2])
        sp_bytes = s.scalar.read_reg(2)
        sp = int.from_bytes(sp_bytes, byteorder='little', signed=False)
        address = sp + self.offset
        freg_bytes = s.scalar.read_freg(self.fs2)
        await s.set_memory(address, freg_bytes[:8])
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [2, self.rs2], [])
        sp_bytes = s.scalar.read_reg(2)
        sp = int.from_bytes(sp_bytes, byteorder='little', signed=False)
        address = sp + self.offset
        value_bytes = s.scalar.read_reg(self.rs2)
        await s.set_memory(address, value_bytes[:4])
        s.pc += 2


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

    async def update_resolve(self, s, result_future, data_future):
        await data_future
        data = data_future.result()
        value = int.from_bytes(data, byteorder='little', signed=False)
        if value & 0x80000000:
            value = value | 0xffffffff00000000
        result_bytes = value.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        result_future.set_result(result_bytes)

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [2], [])
        sp_bytes = s.scalar.read_reg(2)
        sp = int.from_bytes(sp_bytes, byteorder='little', signed=False)
        address = sp + self.offset
        data_future = await s.get_memory(address, 4)
        result_future = s.clock.create_future()
        s.clock.create_task(self.update_resolve(s, result_future, data_future))
        s.scalar.write_reg_future(self.rd, result_future)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [2], [])
        sp_bytes = s.scalar.read_reg(2)
        sp = int.from_bytes(sp_bytes, byteorder='little', signed=False)
        address = sp + self.offset
        data_future = await s.get_memory(address, 8)
        s.scalar.write_reg_future(self.rd, data_future)
        s.pc += 2


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

    async def update_resolve(self, s, result_future, data_future):
        await data_future
        data = data_future.result()
        value = int.from_bytes(data, byteorder='little', signed=False)
        if value & 0x80000000:
            value = value | 0xffffffff00000000
        result_bytes = value.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        result_future.set_result(result_bytes)

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.offset
        data_future = await s.get_memory(address, 4)
        result_future = s.clock.create_future()
        s.clock.create_task(self.update_resolve(s, result_future, data_future))
        s.scalar.write_reg_future(self.rd, result_future)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.offset
        data_future = await s.get_memory(address, 8)
        s.scalar.write_reg_future(self.rd, data_future)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.offset
        value_bytes = s.scalar.read_reg(self.rs2)
        await s.set_memory(address, value_bytes[:4])
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.offset
        value_bytes = s.scalar.read_reg(self.rs2)
        await s.set_memory(address, value_bytes[:8])
        s.pc += 2


@dataclass
class CFld:
    """C.FLD - Compressed Floating-Point Load Double (RV32DC/RV64DC).

    Loads a double-precision floating-point value from memory at rs1 + offset
    into floating-point register fd. The offset is zero-extended and scaled by 8.
    Expands to: fld fd, offset(rs1)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    fd: int
    rs1: int
    offset: int

    def __str__(self):
        return f'fld\t{freg_name(self.fd)},{self.offset}({reg_name(self.rs1)})'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, self.fd, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.offset
        data_future = await s.get_memory(address, 8)
        s.scalar.write_freg_future(self.fd, data_future)
        s.pc += 2


@dataclass
class CFsd:
    """C.FSD - Compressed Floating-Point Store Double (RV32DC/RV64DC).

    Stores a double-precision floating-point value from floating-point register
    fs2 to memory at rs1 + offset. The offset is zero-extended and scaled by 8.
    Expands to: fsd fs2, offset(rs1)

    Reference: riscv-isa-manual/src/c-st-ext.adoc
    """
    rs1: int
    fs2: int
    offset: int

    def __str__(self):
        return f'fsd\t{freg_name(self.fs2)},{self.offset}({reg_name(self.rs1)})'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [self.fs2])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.offset
        freg_bytes = s.scalar.read_freg(self.fs2)
        await s.set_memory(address, freg_bytes[:8])
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd_rs1, None, [self.rd_rs1, self.rs2], [])
        rd_val = int.from_bytes(s.scalar.read_reg(self.rd_rs1), byteorder='little', signed=False)
        rs2_val = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        result = (rd_val + rs2_val) & 0xffffffff
        if result & 0x80000000:
            result = result | 0xffffffff00000000
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd_rs1, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd_rs1, None, [self.rd_rs1, self.rs2], [])
        rd_val = int.from_bytes(s.scalar.read_reg(self.rd_rs1), byteorder='little', signed=False)
        rs2_val = int.from_bytes(s.scalar.read_reg(self.rs2), byteorder='little', signed=False)
        result = (rd_val - rs2_val) & 0xffffffff
        if result & 0x80000000:
            result = result | 0xffffffff00000000
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd_rs1, result_bytes)
        s.pc += 2


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        target = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        s.pc = target


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [])
        target = int.from_bytes(s.scalar.read_reg(self.rs1), byteorder='little', signed=False)
        return_addr = s.pc + 2
        return_addr_bytes = return_addr.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(1, return_addr_bytes)
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

    async def update_state(self, s: 'state.State'):
        raise NotImplementedError('C.EBREAK not implemented')
