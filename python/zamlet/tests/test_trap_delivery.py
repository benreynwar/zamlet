import asyncio

import pytest

from zamlet.addresses import GlobalAddress, MemoryType, Ordering
from zamlet.geometries import SMALL_GEOMETRIES
from zamlet.instructions.memory import Lw, Sw
from zamlet.instructions.system import Mret
from zamlet.instructions.vector import VIndexedLoad, VleV, VlseV
from zamlet.monitor import CompletionType, SpanType
from zamlet.params import ZamletParams
from zamlet.runner import Clock
from zamlet.tests.test_utils import pack_elements, setup_lamlet, unpack_elements
from zamlet.trap import (
    CAUSE_LOAD_ACCESS,
    CAUSE_LOAD_PAGE_FAULT,
    CAUSE_STORE_PAGE_FAULT,
    CSR_MCAUSE,
    CSR_MEPC,
    CSR_MSTATUS,
    CSR_MTVAL,
    CSR_MTVEC,
    MSTATUS_MIE_BIT,
    MSTATUS_MPIE_BIT,
)


PC = 0x8000
HANDLER_PC = 0x1000
BASE = 0x90000000
DEST = 0x91000000


def _csr_int(lamlet, csr):
    return int.from_bytes(lamlet.scalar.read_csr(csr), "little", signed=False)


def _write_csr(lamlet, csr, value):
    lamlet.scalar.write_csr(
        csr, value.to_bytes(lamlet.params.word_bytes, "little", signed=False))


def _write_x(lamlet, reg, value):
    lamlet.scalar.write_reg(
        reg, value.to_bytes(lamlet.params.word_bytes, "little", signed=False),
        lamlet._setup_span_id)


def _alloc(lamlet, addr, pages=1, memory_type=MemoryType.VPU,
           readable=True, writable=True):
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=addr * 8, params=lamlet.params),
        pages * lamlet.params.page_bytes,
        memory_type=memory_type,
        readable=readable,
        writable=writable,
    )


def _install_handler(lamlet):
    _write_csr(lamlet, CSR_MTVEC, HANDLER_PC)


async def _run(params: ZamletParams, body, max_cycles=100000):
    clock = Clock(max_cycles=max_cycles)

    async def main():
        clock.register_main()
        clock.create_task(clock.clock_driver())
        lamlet = await setup_lamlet(clock, params)
        try:
            await body(clock, lamlet)
        finally:
            clock.running = False

    await main()


def run_model_test(params: ZamletParams, body, max_cycles=100000):
    asyncio.run(_run(params, body, max_cycles=max_cycles))


async def _read_vector(clock, lamlet, reg, n_elements, ew, addr=DEST):
    size = max(lamlet.params.page_bytes, n_elements * (ew // 8))
    _alloc(lamlet, addr, (size + lamlet.params.page_bytes - 1) // lamlet.params.page_bytes)
    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR,
        component="test",
        completion_type=CompletionType.FIRE_AND_FORGET,
    )
    await lamlet.vstore(
        vs=reg,
        addr=addr,
        ordering=Ordering(lamlet.word_order, ew),
        n_elements=n_elements,
        mask_reg=None,
        start_index=0,
        parent_span_id=span_id,
    )
    lamlet.monitor.finalize_children(span_id)
    data = await lamlet.get_memory_blocking(addr, n_elements * (ew // 8))
    return unpack_elements(data, ew)


async def _load_vector(lamlet, reg, values, ew, addr):
    size = max(lamlet.params.page_bytes, len(values) * (ew // 8))
    _alloc(lamlet, addr, (size + lamlet.params.page_bytes - 1) // lamlet.params.page_bytes)
    lamlet.directly_set_memory(addr, pack_elements(values, ew), Ordering(lamlet.word_order, ew))
    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR,
        component="test",
        completion_type=CompletionType.FIRE_AND_FORGET,
    )
    result = await lamlet.vload(
        vd=reg,
        addr=addr,
        ordering=Ordering(lamlet.word_order, ew),
        n_elements=len(values),
        mask_reg=None,
        start_index=0,
        parent_span_id=span_id,
    )
    assert result.success
    lamlet.monitor.finalize_children(span_id)


async def _assert_trap(lamlet, cause, mtval, mepc=PC, vstart=None):
    assert lamlet.pc == HANDLER_PC
    assert _csr_int(lamlet, CSR_MCAUSE) == cause
    assert _csr_int(lamlet, CSR_MTVAL) == mtval
    assert _csr_int(lamlet, CSR_MEPC) == mepc
    if vstart is not None:
        assert lamlet.vstart == vstart


@pytest.fixture(params=[next(iter(SMALL_GEOMETRIES.values()))])
def params(request):
    return request.param


def test_no_handler_vector_load_fault_asserts(params):
    async def body(clock, lamlet):
        page_bytes = lamlet.params.page_bytes
        source_addr = BASE + page_bytes - 4
        _alloc(lamlet, BASE, memory_type=MemoryType.VPU)
        lamlet.pc = PC
        lamlet.vl = 2
        lamlet.set_vtype(32, 1)
        _write_x(lamlet, 1, source_addr)

        with pytest.raises(AssertionError, match="mtvec=0"):
            await VleV(vd=1, rs1=1, vm=1, element_width=32).update_state(lamlet)

    run_model_test(params, body)


def test_scalar_load_and_store_page_faults_set_trap_csrs(params):
    async def body(clock, lamlet):
        _install_handler(lamlet)
        _write_x(lamlet, 1, BASE)

        lamlet.pc = PC
        await Lw(rd=2, rs1=1, imm=0).update_state(lamlet)
        await _assert_trap(lamlet, CAUSE_LOAD_PAGE_FAULT, BASE)
        assert lamlet.scalar.read_reg(2) == bytes(lamlet.params.word_bytes)

        lamlet.pc = PC + 4
        _write_x(lamlet, 3, 0x12345678)
        await Sw(rs1=1, rs2=3, imm=4).update_state(lamlet)
        await _assert_trap(lamlet, CAUSE_STORE_PAGE_FAULT, BASE + 4, mepc=PC + 4)

    run_model_test(params, body)


def test_scalar_store_straddling_page_boundary_reports_faulting_page(params):
    """Sw straddling a page boundary where only the second page is unmapped.

    mtval must point into the faulting page, not at the access start (which
    lies in a perfectly-mapped page).
    """
    async def body(clock, lamlet):
        page_bytes = lamlet.params.page_bytes
        _alloc(lamlet, BASE, memory_type=MemoryType.SCALAR_IDEMPOTENT)
        addr = BASE + page_bytes - 2

        _install_handler(lamlet)
        lamlet.pc = PC
        _write_x(lamlet, 1, addr)
        _write_x(lamlet, 2, 0xDEADBEEF)
        await Sw(rs1=1, rs2=2, imm=0).update_state(lamlet)

        await _assert_trap(lamlet, CAUSE_STORE_PAGE_FAULT, BASE + page_bytes)

    run_model_test(params, body)


def test_scalar_permission_fault_uses_access_fault_cause(params):
    async def body(clock, lamlet):
        _install_handler(lamlet)
        _alloc(
            lamlet, BASE, memory_type=MemoryType.SCALAR_IDEMPOTENT,
            readable=False, writable=True)
        _write_x(lamlet, 1, BASE)

        lamlet.pc = PC
        await Lw(rd=2, rs1=1, imm=0).update_state(lamlet)
        await _assert_trap(lamlet, CAUSE_LOAD_ACCESS, BASE)

    run_model_test(params, body)


def test_mret_restores_pc_and_interrupt_enable(params):
    async def body(clock, lamlet):
        _write_csr(lamlet, CSR_MEPC, PC)
        _write_csr(lamlet, CSR_MSTATUS, 1 << MSTATUS_MPIE_BIT)
        lamlet.pc = HANDLER_PC

        await Mret().update_state(lamlet)

        assert lamlet.pc == PC
        assert (_csr_int(lamlet, CSR_MSTATUS) >> MSTATUS_MIE_BIT) & 1 == 1
        assert (_csr_int(lamlet, CSR_MSTATUS) >> MSTATUS_MPIE_BIT) & 1 == 1

    run_model_test(params, body)


def test_vector_unit_stride_load_fault_is_precise_and_preserves_tail(params):
    async def body(clock, lamlet):
        page_bytes = lamlet.params.page_bytes
        ew = 32
        element_bytes = ew // 8
        fault_index = 2
        vl = fault_index + 2
        source_addr = BASE + page_bytes - fault_index * element_bytes
        initial = [0xaaaa0000 + i for i in range(vl)]
        loaded = [0x11110000 + i for i in range(fault_index)]

        _install_handler(lamlet)
        lamlet.pc = PC
        lamlet.vl = vl
        lamlet.set_vtype(ew, 1)
        _write_x(lamlet, 1, source_addr)
        await _load_vector(lamlet, 2, initial, ew, BASE + 4 * page_bytes)
        _alloc(lamlet, BASE, memory_type=MemoryType.VPU)
        lamlet.directly_set_memory(
            source_addr, pack_elements(loaded, ew),
            Ordering(lamlet.word_order, ew))
        # Only the first source page is allocated. The first element in the next
        # page must trap before modifying that element or any later element.

        await VleV(vd=2, rs1=1, vm=1, element_width=ew).update_state(lamlet)

        await _assert_trap(
            lamlet, CAUSE_LOAD_PAGE_FAULT, BASE + page_bytes,
            vstart=fault_index)
        actual = await _read_vector(clock, lamlet, 2, vl, ew)
        assert actual[:fault_index] == loaded
        assert actual[fault_index:] == initial[fault_index:]

    run_model_test(params, body)


def test_vector_strided_load_fault_reports_faulting_element_address(params):
    async def body(clock, lamlet):
        page_bytes = lamlet.params.page_bytes
        ew = 32
        stride = page_bytes
        vl = 3
        initial = [0xaaaa0000 + i for i in range(vl)]

        _install_handler(lamlet)
        lamlet.pc = PC
        lamlet.vl = vl
        lamlet.set_vtype(ew, 1)
        _write_x(lamlet, 1, BASE)
        _write_x(lamlet, 2, stride)
        await _load_vector(lamlet, 3, initial, ew, BASE + 4 * page_bytes)
        _alloc(lamlet, BASE, memory_type=MemoryType.VPU)
        lamlet.directly_set_memory(BASE, pack_elements([0x12345678], ew), Ordering(lamlet.word_order, ew))

        await VlseV(vd=3, rs1=1, rs2=2, vm=1, element_width=ew).update_state(lamlet)

        await _assert_trap(
            lamlet, CAUSE_LOAD_PAGE_FAULT, BASE + page_bytes,
            vstart=1)
        actual = await _read_vector(clock, lamlet, 3, vl, ew)
        assert actual[0] == 0x12345678
        assert actual[1:] == initial[1:]

    run_model_test(params, body)


def test_indexed_load_fault_reports_effective_element_address(params):
    async def body(clock, lamlet):
        page_bytes = lamlet.params.page_bytes
        ew = 32
        indexes = [0, 2 * page_bytes, page_bytes]
        vl = len(indexes)

        _install_handler(lamlet)
        lamlet.pc = PC
        lamlet.vl = vl
        lamlet.set_vtype(ew, 1)
        _write_x(lamlet, 1, BASE)
        _alloc(lamlet, BASE, memory_type=MemoryType.VPU)
        _alloc(lamlet, BASE + 2 * page_bytes, memory_type=MemoryType.VPU)
        lamlet.directly_set_memory(BASE, pack_elements([0x11111111], ew), Ordering(lamlet.word_order, ew))
        lamlet.directly_set_memory(
            BASE + 2 * page_bytes, pack_elements([0x22222222], ew),
            Ordering(lamlet.word_order, ew))
        await _load_vector(lamlet, 2, indexes, ew, BASE + 4 * page_bytes)

        await VIndexedLoad(
            vd=3, rs1=1, vs2=2, vm=1, index_width=ew, ordered=True
        ).update_state(lamlet)

        await _assert_trap(
            lamlet, CAUSE_LOAD_PAGE_FAULT, BASE + page_bytes,
            vstart=2)

    run_model_test(params, body)


def test_mret_resume_completes_vector_instruction_and_clears_vstart(params):
    async def body(clock, lamlet):
        page_bytes = lamlet.params.page_bytes
        ew = 32
        element_bytes = ew // 8
        fault_index = 2
        vl = fault_index + 2
        source_addr = BASE + page_bytes - fault_index * element_bytes
        values = [0x55550000 + i for i in range(vl)]

        _install_handler(lamlet)
        lamlet.pc = PC
        lamlet.vl = vl
        lamlet.set_vtype(ew, 1)
        _write_x(lamlet, 1, source_addr)
        _alloc(lamlet, BASE, memory_type=MemoryType.VPU)
        lamlet.directly_set_memory(
            source_addr, pack_elements(values[:fault_index], ew),
            Ordering(lamlet.word_order, ew))

        instr = VleV(vd=2, rs1=1, vm=1, element_width=ew)
        await instr.update_state(lamlet)
        await _assert_trap(
            lamlet, CAUSE_LOAD_PAGE_FAULT, BASE + page_bytes,
            vstart=fault_index)

        _alloc(lamlet, BASE + page_bytes, memory_type=MemoryType.VPU)
        lamlet.directly_set_memory(
            BASE + page_bytes, pack_elements(values[fault_index:], ew),
            Ordering(lamlet.word_order, ew))
        await Mret().update_state(lamlet)
        assert lamlet.pc == PC

        await instr.update_state(lamlet)

        assert lamlet.pc == PC + 4
        assert lamlet.vstart == 0
        assert await _read_vector(clock, lamlet, 2, vl, ew) == values

    run_model_test(params, body)
