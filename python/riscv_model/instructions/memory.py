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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        address = s.scalar.read_reg(self.rs1) + self.imm
        value = s.scalar.read_reg(self.rs2) & 0xff
        s.set_memory(address, value.to_bytes(1, byteorder='little'))


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        address = s.scalar.read_reg(self.rs1) + self.imm
        value = s.scalar.read_reg(self.rs2) & 0xffff
        s.set_memory(address, value.to_bytes(2, byteorder='little'))


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        address = s.scalar.read_reg(self.rs1) + self.imm
        value = s.scalar.read_reg(self.rs2) & 0xffffffff
        s.set_memory(address, value.to_bytes(4, byteorder='little'))


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        address = s.scalar.read_reg(self.rs1) + self.imm
        value = s.scalar.read_reg(self.rs2)
        s.set_memory(address, value.to_bytes(8, byteorder='little'), force_vpu=True)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        address = s.scalar.read_reg(self.rs1) + self.imm
        data = s.get_memory(address, 1)
        value = int.from_bytes(data, byteorder='little')
        if value & 0x80:
            value = value - 0x100
        s.scalar.write_reg(self.rd, value)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        address = s.scalar.read_reg(self.rs1) + self.imm
        data = s.get_memory(address, 1)
        value = int.from_bytes(data, byteorder='little')
        s.scalar.write_reg(self.rd, value)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        address = s.scalar.read_reg(self.rs1) + self.imm
        data = s.get_memory(address, 2)
        value = int.from_bytes(data, byteorder='little')
        if value & 0x8000:
            value = value - 0x10000
        s.scalar.write_reg(self.rd, value)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        address = s.scalar.read_reg(self.rs1) + self.imm
        data = s.get_memory(address, 2)
        value = int.from_bytes(data, byteorder='little')
        s.scalar.write_reg(self.rd, value)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        address = s.scalar.read_reg(self.rs1) + self.imm
        data = s.get_memory(address, 4)
        value = int.from_bytes(data, byteorder='little')
        if value & 0x80000000:
            value = value - 0x100000000
        s.scalar.write_reg(self.rd, value)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        address = s.scalar.read_reg(self.rs1) + self.imm
        data = s.get_memory(address, 4)
        value = int.from_bytes(data, byteorder='little')
        s.scalar.write_reg(self.rd, value)


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

    def update_state(self, s: 'state.State'):
        s.pc += 4
        address = s.scalar.read_reg(self.rs1) + self.imm
        data = s.get_memory(address, 8)
        value = int.from_bytes(data, byteorder='little')
        s.scalar.write_reg(self.rd, value)
