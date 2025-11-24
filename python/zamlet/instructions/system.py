"""System instructions (CSR manipulation, memory ordering).

Reference: riscv-isa-manual/src/zicsr.adoc, riscv-isa-manual/src/a-st-ext.adoc
"""

from dataclasses import dataclass

from zamlet.register_names import reg_name

# CSR names mapping
CSR_NAMES = {
    # Floating-point CSRs
    0x001: 'fflags',
    0x002: 'frm',
    0x003: 'fcsr',
    # Vector CSRs
    0x008: 'vstart',
    0x009: 'vxsat',
    0x00a: 'vxrm',
    0x00b: 'vtype',
    0x00c: 'vl',
    0x00e: 'vlenb',
    0x00f: 'vcsr',
    # User CSRs
    0x011: 'ssp',
    0x015: 'seed',
    0x017: 'jvt',
    # Supervisor CSRs
    0x100: 'sstatus',
    0x104: 'sie',
    0x105: 'stvec',
    0x106: 'scounteren',
    0x10a: 'senvcfg',
    0x120: 'scountinhibit',
    0x140: 'sscratch',
    0x141: 'sepc',
    0x142: 'scause',
    0x143: 'stval',
    0x144: 'sip',
    0x180: 'satp',
    0x5a8: 'scontext',
    # Hypervisor CSRs
    0x600: 'hstatus',
    0x602: 'hedeleg',
    0x603: 'hideleg',
    0x604: 'hie',
    0x606: 'hcounteren',
    0x607: 'hgeie',
    0x643: 'htval',
    0x644: 'hip',
    0x645: 'hvip',
    0x64a: 'htinst',
    0x680: 'hgatp',
    0x6a8: 'hcontext',
    # Machine CSRs
    0x300: 'mstatus',
    0x301: 'misa',
    0x302: 'medeleg',
    0x303: 'mideleg',
    0x304: 'mie',
    0x305: 'mtvec',
    0x306: 'mcounteren',
    0x30a: 'menvcfg',
    0x310: 'mstatush',
    0x320: 'mcountinhibit',
    0x340: 'mscratch',
    0x341: 'mepc',
    0x342: 'mcause',
    0x343: 'mtval',
    0x344: 'mip',
    0x34a: 'mtinst',
    0x34b: 'mtval2',
    # PMP CSRs
    0x3a0: 'pmpcfg0',
    0x3a1: 'pmpcfg1',
    0x3a2: 'pmpcfg2',
    0x3a3: 'pmpcfg3',
    0x3b0: 'pmpaddr0',
    0x3b1: 'pmpaddr1',
    0x3b2: 'pmpaddr2',
    0x3b3: 'pmpaddr3',
    0x3b4: 'pmpaddr4',
    0x3b5: 'pmpaddr5',
    0x3b6: 'pmpaddr6',
    0x3b7: 'pmpaddr7',
    0x3b8: 'pmpaddr8',
    0x3b9: 'pmpaddr9',
    0x3ba: 'pmpaddr10',
    0x3bb: 'pmpaddr11',
    0x3bc: 'pmpaddr12',
    0x3bd: 'pmpaddr13',
    0x3be: 'pmpaddr14',
    0x3bf: 'pmpaddr15',
    # Debug CSRs
    0x7a0: 'tselect',
    0x7a1: 'tdata1',
    0x7a2: 'tdata2',
    0x7a3: 'tdata3',
    0x7b0: 'dcsr',
    0x7b1: 'dpc',
    0x7b2: 'dscratch0',
    0x7b3: 'dscratch1',
    # Machine counters
    0xb00: 'mcycle',
    0xb02: 'minstret',
    0xb80: 'mcycleh',
    0xb82: 'minstreth',
    # User counters
    0xc00: 'cycle',
    0xc01: 'time',
    0xc02: 'instret',
    0xc80: 'cycleh',
    0xc81: 'timeh',
    0xc82: 'instreth',
    # Machine info
    0xf11: 'mvendorid',
    0xf12: 'marchid',
    0xf13: 'mimpid',
    0xf14: 'mhartid',
    0xf15: 'mconfigptr',
}


@dataclass
class Mret:
    """MRET - Machine-mode return.

    Returns from a machine-mode trap handler. Restores PC from mepc and
    privilege mode from mstatus.MPP. In our emulator, we just increment PC.

    Reference: riscv-isa-manual/src/machine.adoc
    """

    def __str__(self):
        return 'mret'

    async def update_state(self, s: 'state.State'):
        s.pc += 4


@dataclass
class Sret:
    """SRET - Supervisor-mode return.

    Returns from a supervisor-mode trap handler. In our emulator, we just increment PC.

    Reference: riscv-isa-manual/src/supervisor.adoc
    """

    def __str__(self):
        return 'sret'

    async def update_state(self, s: 'state.State'):
        s.pc += 4


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


@dataclass
class Csrrwi:
    """CSRRWI - Atomic Read/Write CSR Immediate.

    Similar to CSRRW, but updates CSR with a 5-bit immediate (zero-extended).
    Reads old CSR value, zero-extends to XLEN bits, writes to rd.
    The immediate value (zimm) is written to the CSR.
    If rd=x0, the CSR is not read.

    Reference: riscv-isa-manual/src/zicsr.adoc
    """
    rd: int
    zimm: int
    csr: int

    def __str__(self):
        csr_name = CSR_NAMES.get(self.csr, f'0x{self.csr:x}')
        if self.rd == 0:
            return f'csrwi\t{csr_name},{self.zimm}'
        else:
            return f'csrrwi\t{reg_name(self.rd)},{csr_name},{self.zimm}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [])
        if self.rd != 0:
            csr_bytes = s.scalar.read_csr(self.csr)
            s.scalar.write_reg(self.rd, csr_bytes)
        imm_bytes = self.zimm.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
        s.scalar.write_csr(self.csr, imm_bytes)
        s.pc += 4


@dataclass
class Csrrsi:
    """CSRRSI - Atomic Read and Set Bits in CSR Immediate.

    Similar to CSRRS, but sets bits based on a 5-bit immediate (zero-extended).
    Reads CSR, zero-extends to XLEN bits, writes to rd.
    Bits set in zimm are set in the CSR.
    If zimm=0, CSR is not written.

    Reference: riscv-isa-manual/src/zicsr.adoc
    """
    rd: int
    zimm: int
    csr: int

    def __str__(self):
        csr_name = CSR_NAMES.get(self.csr, f'0x{self.csr:x}')
        if self.rd == 0:
            return f'csrsi\t{csr_name},{self.zimm}'
        else:
            return f'csrrsi\t{reg_name(self.rd)},{csr_name},{self.zimm}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [])
        csr_bytes = s.scalar.read_csr(self.csr)
        csr_val = int.from_bytes(csr_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, csr_bytes)
        if self.zimm != 0:
            new_val = csr_val | self.zimm
            new_bytes = new_val.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
            s.scalar.write_csr(self.csr, new_bytes)
        s.pc += 4


@dataclass
class Csrrci:
    """CSRRCI - Atomic Read and Clear Bits in CSR Immediate.

    Similar to CSRRC, but clears bits based on a 5-bit immediate (zero-extended).
    Reads CSR, zero-extends to XLEN bits, writes to rd.
    Bits set in zimm are cleared in the CSR.
    If zimm=0, CSR is not written.

    Reference: riscv-isa-manual/src/zicsr.adoc
    """
    rd: int
    zimm: int
    csr: int

    def __str__(self):
        csr_name = CSR_NAMES.get(self.csr, f'0x{self.csr:x}')
        if self.rd == 0:
            return f'csrci\t{csr_name},{self.zimm}'
        else:
            return f'csrrci\t{reg_name(self.rd)},{csr_name},{self.zimm}'

    async def update_state(self, s: 'state.State'):
        await s.scalar.wait_all_regs_ready(self.rd, None, [], [])
        csr_bytes = s.scalar.read_csr(self.csr)
        csr_val = int.from_bytes(csr_bytes, byteorder='little', signed=False)
        s.scalar.write_reg(self.rd, csr_bytes)
        if self.zimm != 0:
            new_val = csr_val & ~self.zimm
            new_bytes = new_val.to_bytes(s.params.word_bytes, byteorder='little', signed=False)
            s.scalar.write_csr(self.csr, new_bytes)
        s.pc += 4
