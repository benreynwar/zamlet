"""Floating-point instructions.

Reference: riscv-isa-manual/src/f-st-ext.adoc
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import state

from register_names import reg_name, freg_name


@dataclass
class FmvWX:
    """FMV.W.X - Move from integer register to FP register.

    Moves the single-precision value from the lower 32 bits of integer
    register rs1 to floating-point register fd. Bits are not modified.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    fd: int
    rs1: int

    def __str__(self):
        return f'fmv.w.x\t{freg_name(self.fd)},{reg_name(self.rs1)}'

    def update_state(self, s: 'state.State'):
        value = s.scalar.read_reg(self.rs1) & 0xffffffff
        s.scalar.write_freg(self.fd, value)
        s.pc += 4


@dataclass
class Flw:
    """FLW - Floating-Point Load Word.

    Loads a single-precision floating-point value from memory into
    floating-point register fd.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    fd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'flw\t{freg_name(self.fd)},{self.imm}({reg_name(self.rs1)})'

    def update_state(self, s: 'state.State'):
        addr = s.scalar.read_reg(self.rs1) + self.imm
        data = s.get_memory(addr, 4)
        value = int.from_bytes(data, byteorder='little', signed=False)
        s.scalar.write_freg(self.fd, value)
        s.pc += 4


@dataclass
class Fld:
    """FLD - Floating-Point Load Double.

    Loads a double-precision floating-point value from memory into
    floating-point register fd.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    fd: int
    rs1: int
    imm: int

    def __str__(self):
        return f'fld\t{freg_name(self.fd)},{self.imm}({reg_name(self.rs1)})'

    def update_state(self, s: 'state.State'):
        addr = s.scalar.read_reg(self.rs1) + self.imm
        data = s.get_memory(addr, 8)
        value = int.from_bytes(data, byteorder='little', signed=False)
        s.scalar.write_freg(self.fd, value)
        s.pc += 4


@dataclass
class Fsw:
    """FSW - Floating-Point Store Word.

    Stores a single-precision floating-point value from floating-point
    register rs2 to memory.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    rs2: int
    rs1: int
    imm: int

    def __str__(self):
        return f'fsw\t{freg_name(self.rs2)},{self.imm}({reg_name(self.rs1)})'

    def update_state(self, s: 'state.State'):
        addr = s.scalar.read_reg(self.rs1) + self.imm
        value = s.scalar.read_freg(self.rs2) & 0xffffffff
        data = value.to_bytes(4, byteorder='little', signed=False)
        s.set_memory(addr, data)
        s.pc += 4


@dataclass
class Fsd:
    """FSD - Floating-Point Store Double.

    Stores a double-precision floating-point value from floating-point
    register rs2 to memory.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    rs2: int
    rs1: int
    imm: int

    def __str__(self):
        return f'fsd\t{freg_name(self.rs2)},{self.imm}({reg_name(self.rs1)})'

    def update_state(self, s: 'state.State'):
        addr = s.scalar.read_reg(self.rs1) + self.imm
        value = s.scalar.read_freg(self.rs2)
        data = value.to_bytes(8, byteorder='little', signed=False)
        s.set_memory(addr, data)
        s.pc += 4


@dataclass
class FeqS:
    """FEQ.S - Floating-Point Equal (Single-Precision).

    Compares two single-precision floating-point values for equality.
    Writes 1 to rd if equal, 0 otherwise.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'feq.s\t{reg_name(self.rd)},{freg_name(self.rs1)},{freg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        import struct
        val1_bits = s.scalar.read_freg(self.rs1) & 0xffffffff
        val2_bits = s.scalar.read_freg(self.rs2) & 0xffffffff
        val1 = struct.unpack('f', struct.pack('I', val1_bits))[0]
        val2 = struct.unpack('f', struct.pack('I', val2_bits))[0]
        result = 1 if val1 == val2 else 0
        s.scalar.write_reg(self.rd, result)
        s.pc += 4


@dataclass
class FleS:
    """FLE.S - Floating-Point Less Than or Equal (Single-Precision).

    Compares two single-precision floating-point values.
    Writes 1 to rd if rs1 <= rs2, 0 otherwise.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'fle.s\t{reg_name(self.rd)},{freg_name(self.rs1)},{freg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        import struct
        val1_bits = s.scalar.read_freg(self.rs1) & 0xffffffff
        val2_bits = s.scalar.read_freg(self.rs2) & 0xffffffff
        val1 = struct.unpack('f', struct.pack('I', val1_bits))[0]
        val2 = struct.unpack('f', struct.pack('I', val2_bits))[0]
        result = 1 if val1 <= val2 else 0
        s.scalar.write_reg(self.rd, result)
        s.pc += 4


@dataclass
class FleD:
    """FLE.D - Floating-Point Less Than or Equal (Double-Precision).

    Compares two double-precision floating-point values.
    Writes 1 to rd if rs1 <= rs2, 0 otherwise.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'fle.d\t{reg_name(self.rd)},{freg_name(self.rs1)},{freg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        import struct
        val1_bits = s.scalar.read_freg(self.rs1)
        val2_bits = s.scalar.read_freg(self.rs2)
        val1 = struct.unpack('d', struct.pack('Q', val1_bits))[0]
        val2 = struct.unpack('d', struct.pack('Q', val2_bits))[0]
        result = 1 if val1 <= val2 else 0
        s.scalar.write_reg(self.rd, result)
        s.pc += 4


@dataclass
class FsubS:
    """FSUB.S - Floating-Point Subtract (Single-Precision).

    Subtracts single-precision floating-point values: fd = fs1 - fs2

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    fd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'fsub.s\t{freg_name(self.fd)},{freg_name(self.rs1)},{freg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        import struct
        val1_bits = s.scalar.read_freg(self.rs1) & 0xffffffff
        val2_bits = s.scalar.read_freg(self.rs2) & 0xffffffff
        val1 = struct.unpack('f', struct.pack('I', val1_bits))[0]
        val2 = struct.unpack('f', struct.pack('I', val2_bits))[0]
        result = val1 - val2
        result_bits = struct.unpack('I', struct.pack('f', result))[0]
        s.scalar.write_freg(self.fd, result_bits)
        s.pc += 4


@dataclass
class FsubD:
    """FSUB.D - Floating-Point Subtract (Double-Precision).

    Subtracts double-precision floating-point values: fd = fs1 - fs2

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    fd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'fsub.d\t{freg_name(self.fd)},{freg_name(self.rs1)},{freg_name(self.rs2)}'

    def update_state(self, s: 'state.State'):
        import struct
        val1_bits = s.scalar.read_freg(self.rs1)
        val2_bits = s.scalar.read_freg(self.rs2)
        val1 = struct.unpack('d', struct.pack('Q', val1_bits))[0]
        val2 = struct.unpack('d', struct.pack('Q', val2_bits))[0]
        result = val1 - val2
        result_bits = struct.unpack('Q', struct.pack('d', result))[0]
        s.scalar.write_freg(self.fd, result_bits)
        s.pc += 4


@dataclass
class FabsS:
    """FABS.S - Floating-Point Absolute Value (Single-Precision).

    Pseudo-instruction: fsgnj.s fd, fs, fs
    Computes absolute value of single-precision floating-point value.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    fd: int
    rs1: int

    def __str__(self):
        return f'fabs.s\t{freg_name(self.fd)},{freg_name(self.rs1)}'

    def update_state(self, s: 'state.State'):
        import struct
        val_bits = s.scalar.read_freg(self.rs1) & 0xffffffff
        val = struct.unpack('f', struct.pack('I', val_bits))[0]
        result = abs(val)
        result_bits = struct.unpack('I', struct.pack('f', result))[0]
        s.scalar.write_freg(self.fd, result_bits)
        s.pc += 4


@dataclass
class FabsD:
    """FABS.D - Floating-Point Absolute Value (Double-Precision).

    Pseudo-instruction: fsgnj.d fd, fs, fs
    Computes absolute value of double-precision floating-point value.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    fd: int
    rs1: int

    def __str__(self):
        return f'fabs.d\t{freg_name(self.fd)},{freg_name(self.rs1)}'

    def update_state(self, s: 'state.State'):
        import struct
        val_bits = s.scalar.read_freg(self.rs1)
        val = struct.unpack('d', struct.pack('Q', val_bits))[0]
        result = abs(val)
        result_bits = struct.unpack('Q', struct.pack('d', result))[0]
        s.scalar.write_freg(self.fd, result_bits)
        s.pc += 4
