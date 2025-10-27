"""System instructions (CSR manipulation, memory ordering).

Reference: riscv-isa-manual/src/zicsr.adoc, riscv-isa-manual/src/a-st-ext.adoc
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import state

from register_names import reg_name

# CSR names mapping
CSR_NAMES = {
    0x001: 'fflags',
    0x002: 'frm',
    0x003: 'fcsr',
    0x300: 'mstatus',
    0x301: 'misa',
    0x304: 'mie',
    0x305: 'mtvec',
    0x340: 'mscratch',
    0x341: 'mepc',
    0x342: 'mcause',
    0x343: 'mtval',
    0x344: 'mip',
    0xb00: 'mcycle',
    0xb02: 'minstret',
    0xb80: 'mcycleh',
    0xb82: 'minstreth',
    0xc00: 'cycle',
    0xc02: 'instret',
    0xc80: 'cycleh',
    0xc82: 'instreth',
    0xf14: 'mhartid',
}


@dataclass
class Fence:
    """FENCE - Memory ordering instruction.

    Orders memory accesses. In a sequential emulator, this is a no-op.
    pred: predecessor memory operations (4 bits: I/O/R/W)
    succ: successor memory operations (4 bits: I/O/R/W)

    Reference: riscv-isa-manual/src/a-st-ext.adoc
    """
    pred: int
    succ: int

    def __str__(self):
        return 'fence'

    async def update_state(self, s: 'state.State'):
        s.pc += 4


@dataclass
class Csrrw:
    """CSRRW - Atomic Read/Write CSR.

    Atomically swaps values in the CSR and integer register.
    Reads old CSR value, zero-extends to XLEN bits, writes to rd.
    The value in rs1 is written to the CSR.
    If rd=x0, the CSR is not read.

    Reference: riscv-isa-manual/src/zicsr.adoc
    """
    rd: int
    rs1: int
    csr: int

    def __str__(self):
        csr_name = CSR_NAMES.get(self.csr, f'0x{self.csr:x}')

        # Floating-point CSR pseudo-instructions (match objdump)
        if self.csr == 0x001 and self.rd == 0:
            return f'fsflags\t{reg_name(self.rs1)}'
        elif self.csr == 0x002 and self.rd == 0:
            return f'fsrm\t{reg_name(self.rs1)}'
        elif self.csr == 0x003 and self.rd == 0:
            return f'fscsr\t{reg_name(self.rs1)}'
        elif self.csr == 0x001 and self.rs1 == 0:
            return f'frflags\t{reg_name(self.rd)}'
        elif self.csr == 0x002 and self.rs1 == 0:
            return f'frrm\t{reg_name(self.rd)}'
        elif self.csr == 0x003 and self.rs1 == 0:
            return f'frcsr\t{reg_name(self.rd)}'
        # General CSR pseudo-instructions
        elif self.rd == 0:
            return f'csrw\t{csr_name},{reg_name(self.rs1)}'
        elif self.rs1 == 0:
            return f'csrr\t{reg_name(self.rd)},{csr_name}'
        else:
            return f'csrrw\t{reg_name(self.rd)},{csr_name},{reg_name(self.rs1)}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1], [])
        if self.rd != 0:
            csr_bytes = s.scalar.read_csr(self.csr)
            s.scalar.write_reg(self.rd, csr_bytes)
        rs1_bytes = s.scalar.read_reg(self.rs1)
        s.scalar.write_csr(self.csr, rs1_bytes)
        s.pc += 4


@dataclass
class Csrrs:
    """CSRRS - Atomic Read and Set Bits in CSR.

    Reads CSR, zero-extends to XLEN bits, writes to rd.
    Bits set in rs1 are set in the CSR (atomic read-modify-write).
    If rs1=x0, CSR is not written.

    Reference: riscv-isa-manual/src/zicsr.adoc
    """
    rd: int
    rs1: int
    csr: int

    def __str__(self):
        csr_name = CSR_NAMES.get(self.csr, f'0x{self.csr:x}')

        # Pseudo-instruction: csrr rd, csr when rs1=x0
        if self.rs1 == 0 and self.rd != 0:
            return f'csrr\t{reg_name(self.rd)},{csr_name}'
        # Pseudo-instruction: csrs csr, rs when rd=x0
        elif self.rd == 0:
            return f'csrs\t{csr_name},{reg_name(self.rs1)}'
        else:
            return f'csrrs\t{reg_name(self.rd)},{csr_name},{reg_name(self.rs1)}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [self.rs1], [])
        csr_bytes = s.scalar.read_csr(self.csr)
        csr_val = int.from_bytes(csr_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, csr_bytes)
        if self.rs1 != 0:
            rs1_bytes = s.scalar.read_reg(self.rs1)
            rs1_val = int.from_bytes(rs1_bytes, byteorder='little', signed=False)
            new_val = csr_val | rs1_val
            new_bytes = new_val.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
            s.scalar.write_csr(self.csr, new_bytes)
        s.pc += 4
