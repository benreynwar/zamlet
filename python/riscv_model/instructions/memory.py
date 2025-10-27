"""Memory access (load/store) instructions.

Reference: riscv-isa-manual/src/rv32.adoc
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import state

from register_names import reg_name


logger = logging.getLogger(__name__)


@dataclass
class Sb:
    """SB - Store Byte instruction.

    Stores the least significant byte of rs2 to memory at address rs1+imm.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rs1: int
    rs2: int
    imm: int

    def __str__(self):
        return f'sb\t{reg_name(self.rs2)},{self.imm}({reg_name(self.rs1)})'

    async def update_state(self, s):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.imm
        rs2_bytes = s.scalar.read_reg(self.rs2)
        logger.debug(f'Setting memory address {hex(address)} reg {self.rs1} imm {self.imm} reg contents {rs1_val}')
        await s.set_memory(address, rs2_bytes[:1])
        s.pc += 4


@dataclass
class Sh:
    """SH - Store Halfword instruction.

    Stores the least significant 2 bytes of rs2 to memory at address rs1+imm.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rs1: int
    rs2: int
    imm: int

    def __str__(self):
        return f'sh\t{reg_name(self.rs2)},{self.imm}({reg_name(self.rs1)})'

    async def update_state(self, s):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.imm
        rs2_bytes = s.scalar.read_reg(self.rs2)
        await s.set_memory(address, rs2_bytes[:2])
        s.pc += 4


@dataclass
class Sw:
    """SW - Store Word instruction.

    Stores the least significant 4 bytes of rs2 to memory at address rs1+imm.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rs1: int
    rs2: int
    imm: int

    def __str__(self):
        return f'sw\t{reg_name(self.rs2)},{self.imm}({reg_name(self.rs1)})'

    async def update_state(self, s):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.imm
        rs2_bytes = s.scalar.read_reg(self.rs2)
        await s.set_memory(address, rs2_bytes[:4])
        s.pc += 4

@dataclass
class Sd:
    """SD - Store Doubleword instruction (RV64I).

    Stores 8 bytes from rs2 to memory at address rs1+imm.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rs1: int
    rs2: int
    imm: int

    def __str__(self):
        return f'sd\t{reg_name(self.rs2)},{self.imm}({reg_name(self.rs1)})'

    async def update_state(self, s):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1, self.rs2], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.imm
        rs2_bytes = s.scalar.read_reg(self.rs2)
        logger.debug(f'About to set memory {address} to {rs2_bytes[:8]}')
        await s.set_memory(address, rs2_bytes[:8])
        s.pc += 4

@dataclass
class Lb:
    """LB - Load Byte (sign-extended).

    Loads a byte from memory at address rs1+imm and sign-extends to 64 bits.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'lb\t{reg_name(self.rd)},{self.imm}({reg_name(self.rs1)})'

    async def update_resolve(self, s, result_future, data_future):
        await data_future
        data = data_future.result()
        value = int.from_bytes(data, byteorder='little', signed=True)
        result_bytes = value.to_bytes(s.params.word_bytes, byteorder='little', signed=True)
        result_future.set_result(result_bytes)

    async def update_state(self, s):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.imm
        data_future = await s.get_memory(address, 1)
        result_future = s.clock.create_future()
        s.clock.create_task(self.update_resolve(s, result_future, data_future))
        s.scalar.write_reg_future(self.rd, result_future)
        s.pc += 4


@dataclass
class Lbu:
    """LBU - Load Byte Unsigned.

    Loads a byte from memory at address rs1+imm and zero-extends to 64 bits.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'lbu\t{reg_name(self.rd)},{self.imm}({reg_name(self.rs1)})'

    async def update_resolve(self, s, result_future, data_future):
        await data_future
        data = data_future.result()
        value = int.from_bytes(data, byteorder='little', signed=False)
        result_bytes = value.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        result_future.set_result(result_bytes)

    async def update_state(self, s):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.imm
        data_future = await s.get_memory(address, 1)
        result_future = s.clock.create_future()
        s.clock.create_task(self.update_resolve(s, result_future, data_future))
        s.scalar.write_reg_future(self.rd, result_future)
        s.pc += 4

@dataclass
class Lh:
    """LH - Load Halfword (sign-extended).

    Loads 2 bytes from memory at address rs1+imm and sign-extends to 64 bits.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'lh\t{reg_name(self.rd)},{self.imm}({reg_name(self.rs1)})'

    async def update_resolve(self, s, result_future, data_future):
        await data_future
        data = data_future.result()
        value = int.from_bytes(data, byteorder='little', signed=False)
        if value & 0x8000:
            value = value | 0xffffffffffff0000
        result_bytes = value.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        result_future.set_result(result_bytes)

    async def update_state(self, s):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.imm
        data_future = await s.get_memory(address, 2)
        result_future = s.clock.create_future()
        s.clock.create_task(self.update_resolve(s, result_future, data_future))
        s.scalar.write_reg_future(self.rd, result_future)
        s.pc += 4


@dataclass
class Lhu:
    """LHU - Load Halfword Unsigned.

    Loads 2 bytes from memory at address rs1+imm and zero-extends to 64 bits.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'lhu\t{reg_name(self.rd)},{self.imm}({reg_name(self.rs1)})'

    async def update_resolve(self, s, result_future, data_future):
        await data_future
        data = data_future.result()
        value = int.from_bytes(data, byteorder='little', signed=False)
        result_bytes = value.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        result_future.set_result(result_bytes)

    async def update_state(self, s):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.imm
        data_future = await s.get_memory(address, 2)
        result_future = s.clock.create_future()
        s.clock.create_task(self.update_resolve(s, result_future, data_future))
        s.scalar.write_reg_future(self.rd, result_future)
        s.pc += 4


@dataclass
class Lw:
    """LW - Load Word (sign-extended).

    Loads 4 bytes from memory at address rs1+imm and sign-extends to 64 bits.

    Reference: riscv-isa-manual/src/rv32.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'lw\t{reg_name(self.rd)},{self.imm}({reg_name(self.rs1)})'

    async def update_resolve(self, s, result_future, data_future):
        await data_future
        data = data_future.result()
        value = int.from_bytes(data, byteorder='little', signed=False)
        if value & 0x80000000:
            value = value | 0xffffffff00000000
        result_bytes = value.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        result_future.set_result(result_bytes)

    async def update_state(self, s):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.imm
        data_future = await s.get_memory(address, 4)
        result_future = s.clock.create_future()
        s.clock.create_task(self.update_resolve(s, result_future, data_future))
        s.scalar.write_reg_future(self.rd, result_future)
        s.pc += 4


@dataclass
class Lwu:
    """LWU - Load Word Unsigned (RV64I).

    Loads 4 bytes from memory at address rs1+imm and zero-extends to 64 bits.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'lwu\t{reg_name(self.rd)},{self.imm}({reg_name(self.rs1)})'

    async def update_resolve(self, s, result_future, data_future):
        await data_future
        data = data_future.result()
        value = int.from_bytes(data, byteorder='little', signed=False)
        result_bytes = value.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        result_future.set_result(result_bytes)

    async def update_state(self, s):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.imm
        data_future = await s.get_memory(address, 4)
        result_future = s.clock.create_future()
        s.clock.create_task(self.update_resolve(s, result_future, data_future))
        s.scalar.write_reg_future(self.rd, result_future)
        s.pc += 4


@dataclass
class Ld:
    """LD - Load Doubleword (RV64I).

    Loads 8 bytes from memory at address rs1+imm.

    Reference: riscv-isa-manual/src/rv64.adoc
    """
    rd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'ld\t{reg_name(self.rd)},{self.imm}({reg_name(self.rs1)})'

    async def update_state(self, s):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        address = rs1_val + self.imm
        data_future = await s.get_memory(address, 8)
        s.scalar.write_reg_future(self.rd, data_future)
        s.pc += 4
