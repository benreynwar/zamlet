"""Trap delivery: CSR addresses, cause codes, mstatus bit layout, helpers.

RISC-V privileged spec reference: riscv-isa-manual/src/machine.adoc.
"""

from zamlet.addresses import TLBFaultType


# Trap CSR addresses (subset of CSR_NAMES in instructions/system.py)
CSR_MSTATUS = 0x300
CSR_MTVEC   = 0x305
CSR_MEPC    = 0x341
CSR_MCAUSE  = 0x342
CSR_MTVAL   = 0x343


# Exception cause codes (mcause, non-interrupt).
# Names match kernel_tests/common/encoding.h so test C code and the model agree.
CAUSE_MISALIGNED_FETCH    = 0x0
CAUSE_FETCH_ACCESS        = 0x1
CAUSE_ILLEGAL_INSTRUCTION = 0x2
CAUSE_BREAKPOINT          = 0x3
CAUSE_MISALIGNED_LOAD     = 0x4
CAUSE_LOAD_ACCESS         = 0x5
CAUSE_MISALIGNED_STORE    = 0x6
CAUSE_STORE_ACCESS        = 0x7
CAUSE_USER_ECALL          = 0x8
CAUSE_SUPERVISOR_ECALL    = 0x9
CAUSE_MACHINE_ECALL       = 0xb
CAUSE_FETCH_PAGE_FAULT    = 0xc
CAUSE_LOAD_PAGE_FAULT     = 0xd
CAUSE_STORE_PAGE_FAULT    = 0xf


# mstatus bit layout (machine-mode fields only — supervisor/user deferred)
MSTATUS_MIE_BIT   = 3           # Machine Interrupt Enable
MSTATUS_MPIE_BIT  = 7           # Previous MIE
MSTATUS_MPP_SHIFT = 11          # Previous privilege (2 bits)
MSTATUS_MPP_MASK  = 0b11 << MSTATUS_MPP_SHIFT

PRIV_MACHINE = 3  # Written to MPP on trap entry since we don't model lower privilege


def cause_for_fault(fault_type: TLBFaultType, is_store: bool) -> int:
    """Map a TLB fault to the RISC-V mcause code."""
    if fault_type == TLBFaultType.PAGE_FAULT:
        return CAUSE_STORE_PAGE_FAULT if is_store else CAUSE_LOAD_PAGE_FAULT
    if fault_type == TLBFaultType.WRITE_FAULT:
        return CAUSE_STORE_ACCESS
    if fault_type == TLBFaultType.READ_FAULT:
        return CAUSE_LOAD_ACCESS
    assert False, f'cause_for_fault: unexpected fault_type={fault_type}'
