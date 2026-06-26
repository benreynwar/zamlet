import json
import logging
import random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import ReadOnly, RisingEdge

from zamlet import test_utils
from zamlet.addresses import Ordering
from zamlet.kamlet.kinstructions import (
    KInstrOpcode,
    PackedBinaryOp,
    PackedLoadIndexedUnordered,
    PackedLoadSimple,
    PackedStoreSimple,
    PackedWriteParam,
    base_addr_param_idx,
    end_index_param_idx,
    start_index_param_idx,
)
from zamlet.kamlet_test.kamlet_mesh_with_memlets_driver import (
    KamletMeshWithMemletsDriver,
)
from zamlet.lane_order import LaneOrder
from zamlet.params import ZamletParams
from zamlet.width_codes import ElementWidthCode


TEST_TIMEOUT_NS = 20_000


logger = logging.getLogger(__name__)


def load_params() -> ZamletParams:
    test_params = test_utils.get_test_params()
    with open(test_params["params_file"]) as f:
        return ZamletParams.from_dict(json.load(f))


async def wait_for_cache_line(
    driver: KamletMeshWithMemletsDriver,
    logical_cache_line_addr: int,
    expected: list[int],
    timeout_cycles: int,
) -> list[int | None]:
    for _ in range(timeout_cycles):
        await RisingEdge(driver.dut.clock)
        await ReadOnly()
        actual = driver.memory.read_lamlet_cache_line_from_dut(
            driver.dut, logical_cache_line_addr)
        if actual == expected:
            return actual
    logger.error(
        'destination cache line mismatch logical=0x%x expected_prefix=%s actual_prefix=%s',
        logical_cache_line_addr,
        expected[:32],
        actual[:32],
    )
    driver.log_debug_state()
    driver.memory.log_cache_line_debug(driver.dut, logical_cache_line_addr)
    assert False, f'destination cache line did not match: {actual}'


@cocotb.test(timeout_time=TEST_TIMEOUT_NS, timeout_unit="ns")
async def vector_load_then_vector_store(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim()
    test_params = test_utils.get_test_params()
    params = load_params()
    rng = random.Random(test_params["seed"])

    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())
    driver = KamletMeshWithMemletsDriver(dut, params)
    driver.initialize_inputs()
    await driver.reset()
    driver.start(rng)

    ordering = Ordering(LaneOrder.ROW_MAJOR, 64)
    source_physical_line = 0x10
    dest_physical_line = 0x20
    source_logical_line = 0x100
    dest_logical_line = 0x200
    driver.memory.map_cache_line(source_physical_line, source_logical_line, ordering)
    driver.memory.map_cache_line(dest_physical_line, dest_logical_line, ordering)

    line_bytes = params.cache_slot_words_per_jamlet * params.stripe_bytes
    source_data = bytes((17 * i + 3) & 0xff for i in range(line_bytes))
    driver.memory.write_logical_bytes(source_logical_line * line_bytes, source_data)

    base_ref = 0
    start_ref = 0
    end_ref = 0
    rf_addr = 1
    setup_instrs = [
        PackedWriteParam(
            instr_ident=1,
            param_idx=base_addr_param_idx(params, base_ref),
            data=driver.memory.base_addr_for_cache_line(source_physical_line),
        ).encode(params),
        PackedWriteParam(
            instr_ident=2,
            param_idx=base_addr_param_idx(params, base_ref + 1),
            data=driver.memory.base_addr_for_cache_line(dest_physical_line),
        ).encode(params),
        PackedWriteParam(
            instr_ident=3,
            param_idx=start_index_param_idx(params, start_ref),
            data=0,
        ).encode(params),
        PackedWriteParam(
            instr_ident=4,
            param_idx=end_index_param_idx(params, end_ref),
            data=params.j_in_l,
        ).encode(params),
    ]
    work_instrs = [
        PackedLoadSimple(
            rf_addr=rf_addr,
            base_addr_param_idx=base_ref,
            start_index_param_idx=start_ref,
            end_index_param_idx=end_ref,
            ew=ElementWidthCode.EW64,
            instr_ident=5,
        ).encode(params),
        PackedStoreSimple(
            rf_addr=rf_addr,
            base_addr_param_idx=base_ref + 1,
            start_index_param_idx=start_ref,
            end_index_param_idx=end_ref,
            ew=ElementWidthCode.EW64,
            instr_ident=6,
        ).encode(params),
    ]
    instrs = setup_instrs + work_instrs
    driver.enqueue_instructions(instrs)

    expected = list(bytes(params.stripe_bytes))
    expected[:params.stripe_bytes] = source_data[:params.stripe_bytes]
    expected.extend([0] * (line_bytes - params.stripe_bytes))
    await wait_for_cache_line(driver, dest_logical_line, expected, 2_000)


@cocotb.test(timeout_time=TEST_TIMEOUT_NS, timeout_unit="ns")
async def vector_load_load_add_checks_dest_register(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim()
    test_params = test_utils.get_test_params()
    params = load_params()
    rng = random.Random(test_params["seed"])

    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())
    driver = KamletMeshWithMemletsDriver(dut, params)
    driver.initialize_inputs()
    await driver.reset()
    driver.start(rng)

    ordering = Ordering(LaneOrder.ROW_MAJOR, 64)
    a_physical_line = 0x30
    b_physical_line = 0x40
    a_logical_line = 0x300
    b_logical_line = 0x400
    driver.memory.map_cache_line(a_physical_line, a_logical_line, ordering)
    driver.memory.map_cache_line(b_physical_line, b_logical_line, ordering)

    line_bytes = params.cache_slot_words_per_jamlet * params.stripe_bytes
    a_values = [0x1000 + 3 * i for i in range(params.j_in_l)]
    b_values = [0x2000 + 5 * i for i in range(params.j_in_l)]
    a_data = bytearray(line_bytes)
    b_data = bytearray(line_bytes)
    for index, value in enumerate(a_values):
        start = index * params.word_bytes
        a_data[start:start + params.word_bytes] = value.to_bytes(
            params.word_bytes, 'little')
    for index, value in enumerate(b_values):
        start = index * params.word_bytes
        b_data[start:start + params.word_bytes] = value.to_bytes(
            params.word_bytes, 'little')
    driver.memory.write_logical_bytes(a_logical_line * line_bytes, bytes(a_data))
    driver.memory.write_logical_bytes(b_logical_line * line_bytes, bytes(b_data))

    a_base_ref = 0
    b_base_ref = 1
    start_ref = 0
    end_ref = 0
    rf_a = 1
    rf_b = 2
    rf_dst = 3
    setup_instrs = [
        PackedWriteParam(
            instr_ident=10,
            param_idx=base_addr_param_idx(params, a_base_ref),
            data=driver.memory.base_addr_for_cache_line(a_physical_line),
        ).encode(params),
        PackedWriteParam(
            instr_ident=11,
            param_idx=base_addr_param_idx(params, b_base_ref),
            data=driver.memory.base_addr_for_cache_line(b_physical_line),
        ).encode(params),
        PackedWriteParam(
            instr_ident=12,
            param_idx=start_index_param_idx(params, start_ref),
            data=0,
        ).encode(params),
        PackedWriteParam(
            instr_ident=13,
            param_idx=end_index_param_idx(params, end_ref),
            data=params.j_in_l,
        ).encode(params),
    ]
    work_instrs = [
        PackedLoadSimple(
            rf_addr=rf_a,
            base_addr_param_idx=a_base_ref,
            start_index_param_idx=start_ref,
            end_index_param_idx=end_ref,
            ew=ElementWidthCode.EW64,
            instr_ident=14,
        ).encode(params),
        PackedLoadSimple(
            rf_addr=rf_b,
            base_addr_param_idx=b_base_ref,
            start_index_param_idx=start_ref,
            end_index_param_idx=end_ref,
            ew=ElementWidthCode.EW64,
            instr_ident=15,
        ).encode(params),
        PackedBinaryOp(
            opcode=KInstrOpcode.ADD,
            dst_reg=rf_dst,
            src_a_reg=rf_a,
            src_b_reg=rf_b,
            start_index_param_idx=start_ref,
            end_index_param_idx=end_ref,
            ew=ElementWidthCode.EW64,
            instr_ident=16,
        ).encode(params),
    ]
    instrs = setup_instrs + work_instrs
    driver.enqueue_instructions(instrs)

    expected = [
        (a + b) & ((1 << 64) - 1)
        for a, b in zip(a_values, b_values)
    ]
    await driver.wait_for_rf_elements(rf_dst, ordering, expected, 2_000)


@cocotb.test(timeout_time=TEST_TIMEOUT_NS, timeout_unit="ns")
async def indexed_load_gathers_from_loaded_offsets(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim()
    test_params = test_utils.get_test_params()
    params = load_params()
    rng = random.Random(test_params["seed"])

    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())
    driver = KamletMeshWithMemletsDriver(dut, params)
    driver.initialize_inputs()
    await driver.reset()
    driver.start(rng)

    ordering = Ordering(LaneOrder.ROW_MAJOR, 64)
    index_physical_line = 0x50
    data_physical_line = 0x60
    index_logical_line = 0x500
    data_logical_line = 0x600
    driver.memory.map_cache_line(index_physical_line, index_logical_line, ordering)
    driver.memory.map_cache_line(data_physical_line, data_logical_line, ordering)

    line_bytes = params.cache_slot_words_per_jamlet * params.stripe_bytes
    gather_order = list(range(params.j_in_l))
    rng.shuffle(gather_order)
    offsets = [index * params.word_bytes for index in gather_order]
    source_values = [
        0x3000_0000_0000_0000 + 0x101 * index
        for index in range(params.j_in_l)
    ]

    index_data = bytearray(line_bytes)
    data = bytearray(line_bytes)
    for element_index, offset in enumerate(offsets):
        start = element_index * params.word_bytes
        index_data[start:start + params.word_bytes] = offset.to_bytes(
            params.word_bytes, 'little')
    for element_index, value in enumerate(source_values):
        start = element_index * params.word_bytes
        data[start:start + params.word_bytes] = value.to_bytes(
            params.word_bytes, 'little')
    driver.memory.write_logical_bytes(
        index_logical_line * line_bytes, bytes(index_data))
    driver.memory.write_logical_bytes(
        data_logical_line * line_bytes, bytes(data))

    index_base_ref = 0
    data_base_ref = 1
    start_ref = 0
    end_ref = 0
    rf_index = 4
    rf_dst = 5
    setup_instrs = [
        PackedWriteParam(
            instr_ident=20,
            param_idx=base_addr_param_idx(params, index_base_ref),
            data=driver.memory.base_addr_for_cache_line(index_physical_line),
        ).encode(params),
        PackedWriteParam(
            instr_ident=21,
            param_idx=base_addr_param_idx(params, data_base_ref),
            data=data_logical_line * line_bytes,
        ).encode(params),
        PackedWriteParam(
            instr_ident=22,
            param_idx=start_index_param_idx(params, start_ref),
            data=0,
        ).encode(params),
        PackedWriteParam(
            instr_ident=23,
            param_idx=end_index_param_idx(params, end_ref),
            data=params.j_in_l,
        ).encode(params),
    ]
    load_index_instrs = [
        PackedLoadSimple(
            rf_addr=rf_index,
            base_addr_param_idx=index_base_ref,
            start_index_param_idx=start_ref,
            end_index_param_idx=end_ref,
            ew=ElementWidthCode.EW64,
            instr_ident=24,
        ).encode(params),
    ]
    driver.enqueue_instructions(setup_instrs + load_index_instrs)
    await driver.wait_for_rf_elements(rf_index, ordering, offsets, 2_000)

    indexed_load_instrs = [
        PackedLoadIndexedUnordered(
            reg=rf_dst,
            index_reg=rf_index,
            fault_sync_ident=1,
            completion_sync_ident=2,
            base_addr_param_idx=data_base_ref,
            start_index_param_idx=start_ref,
            end_index_param_idx=end_ref,
            rf_ew=ElementWidthCode.EW64,
            index_ew=ElementWidthCode.EW64,
            instr_ident=25,
        ).encode(params),
    ]
    driver.enqueue_instructions(indexed_load_instrs)

    expected = [source_values[index] for index in gather_order]
    await driver.wait_for_rf_elements(rf_dst, ordering, expected, 4_000)
