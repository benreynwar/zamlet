"""Floating-point instructions.

Reference: riscv-isa-manual/src/f-st-ext.adoc
"""

import struct
import logging
from dataclasses import dataclass

from zamlet.register_names import reg_name, freg_name
import zamlet.utils


logger = logging.getLogger(__name__)


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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, self.fd, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        value = int.from_bytes(rs1_bytes, byteorder='little', signed=False) & 0xffffffff
        value_bytes = value.to_bytes(8, byteorder='little', signed=False)
        s.scalar.write_freg(self.fd, value_bytes)
        s.pc += 4


@dataclass
class FmvD:
    """FMV.D - Move double FP register (pseudo-instruction using FSGNJ.D).

    Copies the double-precision value from floating-point register rs1
    to floating-point register fd.

    Reference: riscv-isa-manual/src/d-st-ext.adoc
    """
    fd: int
    rs1: int

    def __str__(self):
        return f'fmv.d\t{freg_name(self.fd)},{freg_name(self.rs1)}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, self.fd, [], [self.rs1])
        value_bytes = s.scalar.read_freg(self.rs1)
        value = struct.unpack('d', value_bytes[:8])[0]
        logger.debug(f'FmvD: {freg_name(self.fd)} <- {freg_name(self.rs1)} = {value}')
        s.scalar.write_freg(self.fd, value_bytes)
        s.pc += 4


@dataclass
class FmvXD:
    """FMV.X.D - Move from double FP register to integer register.

    Moves the double-precision value from floating-point register rs1
    to integer register rd. Bits are not modified.

    Reference: riscv-isa-manual/src/d-st-ext.adoc
    """
    rd: int
    rs1: int

    def __str__(self):
        return f'fmv.x.d\t{reg_name(self.rd)},{freg_name(self.rs1)}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1])
        freg_bytes = s.scalar.read_freg(self.rs1)
        value = int.from_bytes(freg_bytes[:8], byteorder='little', signed=False)
        value_bytes = value.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, value_bytes)
        s.pc += 4


@dataclass
class FmvDX:
    """FMV.D.X - Move from integer register to double FP register.

    Moves the double-precision value from the lower 64 bits of integer
    register rs1 to floating-point register fd. Bits are not modified.

    Reference: riscv-isa-manual/src/d-st-ext.adoc
    """
    fd: int
    rs1: int

    def __str__(self):
        return f'fmv.d.x\t{freg_name(self.fd)},{reg_name(self.rs1)}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, self.fd, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        value = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        value_bytes = value.to_bytes(8, byteorder='little', signed=False)
        s.scalar.write_freg(self.fd, value_bytes)
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

    async def update_resolve(self, s, future_out, future_in):
        await future_in
        f_data = future_in.result()
        assert isinstance(f_data, bytes)
        assert len(f_data) == 4
        data = utils.pad(f_data, s.params.word_bytes)
        future_out.set_result(data)
        scalar_val = struct.unpack('f', f_data)[0]
        logger.debug(f'{s.clock.cycle} freg: {self.fd} padding the flw result, set result {scalar_val} ')

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, self.fd, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        addr = rs1_val + self.imm
        data_future = await s.get_memory(addr, 4)
        padded_future = s.clock.create_future()
        s.clock.create_task(self.update_resolve(s, padded_future, data_future))
        s.scalar.write_freg_future(self.fd, padded_future)
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, self.fd, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        addr = rs1_val + self.imm
        logger.debug(f'Fld: {freg_name(self.fd)} <- mem[0x{addr:x}]')
        data_future = await s.get_memory(addr, 8)
        s.scalar.write_freg_future(self.fd, data_future)
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [self.rs2])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        addr = rs1_val + self.imm
        freg_bytes = s.scalar.read_freg(self.rs2)
        data = freg_bytes[:4]
        await s.set_memory(addr, data)
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

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, None, [self.rs1], [self.rs2])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
        addr = rs1_val + self.imm
        freg_bytes = s.scalar.read_freg(self.rs2)
        await s.set_memory(addr, freg_bytes[:8])
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

    async def update_state(self, s: 'state.State'):
        import struct
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1, self.rs2])
        val1_bytes = s.scalar.read_freg(self.rs1)
        val2_bytes = s.scalar.read_freg(self.rs2)
        val1 = struct.unpack('f', val1_bytes[:4])[0]
        val2 = struct.unpack('f', val2_bytes[:4])[0]
        result = 1 if val1 == val2 else 0
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
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

    async def update_state(self, s: 'state.State'):
        import struct
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1, self.rs2])
        val1_bytes = s.scalar.read_freg(self.rs1)
        val2_bytes = s.scalar.read_freg(self.rs2)
        val1 = struct.unpack('f', val1_bytes[:4])[0]
        val2 = struct.unpack('f', val2_bytes[:4])[0]
        result = 1 if val1 <= val2 else 0
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
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

    async def update_state(self, s: 'state.State'):
        import struct
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1, self.rs2])
        val1_bytes = s.scalar.read_freg(self.rs1)
        val2_bytes = s.scalar.read_freg(self.rs2)
        val1 = struct.unpack('d', val1_bytes[:8])[0]
        val2 = struct.unpack('d', val2_bytes[:8])[0]
        result = 1 if val1 <= val2 else 0
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
        s.pc += 4


@dataclass
class FltS:
    """FLT.S - Floating-Point Less Than (Single-Precision).

    Compares two single-precision floating-point values.
    Writes 1 to rd if rs1 < rs2, 0 otherwise.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'flt.s\t{reg_name(self.rd)},{freg_name(self.rs1)},{freg_name(self.rs2)}'

    async def update_state(self, s: 'state.State'):
        import struct
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1, self.rs2])
        val1_bytes = s.scalar.read_freg(self.rs1)
        val2_bytes = s.scalar.read_freg(self.rs2)
        val1 = struct.unpack('f', val1_bytes[:4])[0]
        val2 = struct.unpack('f', val2_bytes[:4])[0]
        result = 1 if val1 < val2 else 0
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
        s.pc += 4


@dataclass
class FltD:
    """FLT.D - Floating-Point Less Than (Double-Precision).

    Compares two double-precision floating-point values.
    Writes 1 to rd if rs1 < rs2, 0 otherwise.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'flt.d\t{reg_name(self.rd)},{freg_name(self.rs1)},{freg_name(self.rs2)}'

    async def update_state(self, s: 'state.State'):
        import struct
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1, self.rs2])
        val1_bytes = s.scalar.read_freg(self.rs1)
        val2_bytes = s.scalar.read_freg(self.rs2)
        val1 = struct.unpack('d', val1_bytes[:8])[0]
        val2 = struct.unpack('d', val2_bytes[:8])[0]
        result = 1 if val1 < val2 else 0
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
        s.pc += 4


@dataclass
class FeqD:
    """FEQ.D - Floating-Point Equal (Double-Precision).

    Compares two double-precision floating-point values.
    Writes 1 to rd if rs1 == rs2, 0 otherwise.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    rd: int
    rs1: int
    rs2: int

    def __str__(self):
        return f'feq.d\t{reg_name(self.rd)},{freg_name(self.rs1)},{freg_name(self.rs2)}'

    async def update_state(self, s: 'state.State'):
        import struct
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1, self.rs2])
        val1_bytes = s.scalar.read_freg(self.rs1)
        val2_bytes = s.scalar.read_freg(self.rs2)
        val1 = struct.unpack('d', val1_bytes[:8])[0]
        val2 = struct.unpack('d', val2_bytes[:8])[0]
        result = 1 if val1 == val2 else 0
        result_bytes = result.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, result_bytes)
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

    async def update_state(self, s: 'state.State'):
        import struct
        await s.scalar.wait_all_regs_ready(None, self.fd, [], [self.rs1, self.rs2])
        val1_bytes = s.scalar.read_freg(self.rs1)
        val2_bytes = s.scalar.read_freg(self.rs2)
        val1 = struct.unpack('f', val1_bytes[:4])[0]
        val2 = struct.unpack('f', val2_bytes[:4])[0]
        result = val1 - val2
        result_bytes = struct.pack('f', result) + bytes(4)
        s.scalar.write_freg(self.fd, result_bytes)
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

    async def update_state(self, s: 'state.State'):
        import struct
        await s.scalar.wait_all_regs_ready(None, self.fd, [], [self.rs1, self.rs2])
        val1_bytes = s.scalar.read_freg(self.rs1)
        val2_bytes = s.scalar.read_freg(self.rs2)
        val1 = struct.unpack('d', val1_bytes[:8])[0]
        val2 = struct.unpack('d', val2_bytes[:8])[0]
        result = val1 - val2
        result_bytes = struct.pack('d', result)
        s.scalar.write_freg(self.fd, result_bytes)
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

    async def update_state(self, s: 'state.State'):
        import struct
        await s.scalar.wait_all_regs_ready(None, self.fd, [], [self.rs1])
        val_bytes = s.scalar.read_freg(self.rs1)
        val = struct.unpack('f', val_bytes[:4])[0]
        result = abs(val)
        result_bytes = struct.pack('f', result) + bytes(4)
        s.scalar.write_freg(self.fd, result_bytes)
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

    async def update_state(self, s: 'state.State'):
        import struct
        await s.scalar.wait_all_regs_ready(None, self.fd, [], [self.rs1])
        val_bytes = s.scalar.read_freg(self.rs1)
        val = struct.unpack('d', val_bytes[:8])[0]
        result = abs(val)
        result_bytes = struct.pack('d', result)
        s.scalar.write_freg(self.fd, result_bytes)
        s.pc += 4


@dataclass
class FcvtDL:
    """FCVT.D.L - Convert signed long to double-precision float.

    Converts a 64-bit signed integer in integer register rs1 to a
    double-precision floating-point value in floating-point register fd.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    fd: int
    rs1: int

    def __str__(self):
        return f'fcvt.d.l\t{freg_name(self.fd)},{reg_name(self.rs1)}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, self.fd, [self.rs1], [])
        rs1_bytes = s.scalar.read_reg(self.rs1)
        int_val = int.from_bytes(rs1_bytes, byteorder='little', signed=True)
        float_val = float(int_val)
        result_bytes = struct.pack('d', float_val)
        s.scalar.write_freg(self.fd, result_bytes)
        s.pc += 4


@dataclass
class FcvtLD:
    """FCVT.L.D - Convert double-precision float to signed long.

    Converts a double-precision floating-point value in floating-point
    register rs1 to a 64-bit signed integer in integer register rd.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    rd: int
    rs1: int

    def __str__(self):
        return f'fcvt.l.d\t{reg_name(self.rd)},{freg_name(self.rs1)}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [self.rs1])
        freg_bytes = s.scalar.read_freg(self.rs1)
        float_val = struct.unpack('d', freg_bytes[:8])[0]
        int_val = int(float_val)
        result_bytes = int_val.to_bytes(s.params.word_bytes, byteorder='little', signed=True)
        s.scalar.write_reg(self.rd, result_bytes)
        s.pc += 4


@dataclass
class FmaddD:
    """FMADD.D - Fused Multiply-Add (Double-Precision).

    Performs fused multiply-add: fd = (fs1 * fs2) + fs3
    The operation is performed with a single rounding at the end.

    Reference: riscv-isa-manual/src/f-st-ext.adoc
    """
    fd: int
    rs1: int
    rs2: int
    rs3: int

    def __str__(self):
        return f'fmadd.d\t{freg_name(self.fd)},{freg_name(self.rs1)},{freg_name(self.rs2)},{freg_name(self.rs3)}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(None, self.fd, [], [self.rs1, self.rs2, self.rs3])
        val1_bytes = s.scalar.read_freg(self.rs1)
        val2_bytes = s.scalar.read_freg(self.rs2)
        val3_bytes = s.scalar.read_freg(self.rs3)
        val1 = struct.unpack('d', val1_bytes[:8])[0]
        val2 = struct.unpack('d', val2_bytes[:8])[0]
        val3 = struct.unpack('d', val3_bytes[:8])[0]
        result = (val1 * val2) + val3
        result_bytes = struct.pack('d', result)
        s.scalar.write_freg(self.fd, result_bytes)
        s.pc += 4
