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
    PackedStoreIndexedUnordered,
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


def write_indexed_load_permutation_inputs(
    driver: KamletMeshWithMemletsDriver,
    params: ZamletParams,
    data_logical_line: int,
    index_logical_lines: list[int],
    source_values: list[int],
    permutation: list[int],
    line_bytes: int,
) -> None:
    data = bytearray(line_bytes)
    for element_index, value in enumerate(source_values):
        start = element_index * params.word_bytes
        data[start:start + params.word_bytes] = value.to_bytes(
            params.word_bytes, 'little')
    driver.memory.write_logical_bytes(
        data_logical_line * line_bytes, bytes(data))

    for op_index, logical_line in enumerate(index_logical_lines):
        index_data = bytearray(line_bytes)
        start_element = op_index * params.j_in_l
        for lane_index in range(params.j_in_l):
            byte_offset = permutation[start_element + lane_index] * params.word_bytes
            start = lane_index * params.word_bytes
            index_data[start:start + params.word_bytes] = byte_offset.to_bytes(
                params.word_bytes, 'little')
        driver.memory.write_logical_bytes(
            logical_line * line_bytes, bytes(index_data))


async def load_indexed_load_offsets(
    driver: KamletMeshWithMemletsDriver,
    params: ZamletParams,
    ordering: Ordering,
    index_physical_lines: list[int],
    data_logical_line: int,
    index_base_refs: list[int],
    data_base_ref: int,
    start_ref: int,
    end_ref: int,
    rf_indexes: list[int],
    permutation: list[int],
    line_bytes: int,
    instr_ident_base: int,
) -> None:
    setup_instrs = [
        PackedWriteParam(
            instr_ident=instr_ident_base + index,
            param_idx=base_addr_param_idx(params, base_ref),
            data=driver.memory.base_addr_for_cache_line(physical_line),
        ).encode(params)
        for index, (base_ref, physical_line) in enumerate(
            zip(index_base_refs, index_physical_lines))
    ] + [
        PackedWriteParam(
            instr_ident=instr_ident_base + 3,
            param_idx=base_addr_param_idx(params, data_base_ref),
            data=data_logical_line * line_bytes,
        ).encode(params),
        PackedWriteParam(
            instr_ident=instr_ident_base + 4,
            param_idx=start_index_param_idx(params, start_ref),
            data=0,
        ).encode(params),
        PackedWriteParam(
            instr_ident=instr_ident_base + 5,
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
            instr_ident=instr_ident_base + 6 + index,
        ).encode(params)
        for index, (rf_index, index_base_ref) in enumerate(
            zip(rf_indexes, index_base_refs))
    ]
    driver.enqueue_instructions(setup_instrs + load_index_instrs)
    for op_index, rf_index in enumerate(rf_indexes):
        start = op_index * params.j_in_l
        offsets = [
            permutation[element_index] * params.word_bytes
            for element_index in range(start, start + params.j_in_l)
        ]
        await driver.wait_for_rf_elements(rf_index, ordering, offsets, 2_000)


def enqueue_parallel_indexed_loads(
    driver: KamletMeshWithMemletsDriver,
    params: ZamletParams,
    rf_indexes: list[int],
    rf_dsts: list[int],
    data_base_ref: int,
    start_ref: int,
    end_ref: int,
    instr_ident_base: int,
) -> None:
    indexed_load_instrs = [
        PackedLoadIndexedUnordered(
            reg=rf_dst,
            index_reg=rf_index,
            fault_sync_ident=index + 1,
            completion_sync_ident=index + 4,
            base_addr_param_idx=data_base_ref,
            start_index_param_idx=start_ref,
            end_index_param_idx=end_ref,
            rf_ew=ElementWidthCode.EW64,
            index_ew=ElementWidthCode.EW64,
            instr_ident=instr_ident_base + index,
        ).encode(params)
        for index, (rf_dst, rf_index) in enumerate(zip(rf_dsts, rf_indexes))
    ]
    driver.enqueue_instructions(indexed_load_instrs)


def indexed_load_expected_values(
    params: ZamletParams,
    source_values: list[int],
    permutation: list[int],
    op_index: int,
) -> list[int]:
    start = op_index * params.j_in_l
    return [
        source_values[permutation[element_index]]
        for element_index in range(start, start + params.j_in_l)
    ]


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
    n_indexed_loads = 3
    n_permutations = 3
    vector_len = n_indexed_loads * params.j_in_l
    line_bytes = params.cache_slot_words_per_jamlet * params.stripe_bytes
    assert vector_len * params.word_bytes <= line_bytes
    assert 2 * n_indexed_loads <= params.max_concurrent_syncs

    index_base_refs = list(range(n_indexed_loads))
    data_base_ref = n_indexed_loads
    start_ref = 0
    end_ref = 0
    rf_indexes = [
        4 + index
        for index in range(n_indexed_loads)
    ]
    rf_dsts = [
        8 + index
        for index in range(n_indexed_loads)
    ]

    for permutation_index in range(n_permutations):
        line_base = permutation_index * 0x30
        ident_base = 20 + permutation_index * 40
        index_physical_lines = [
            0x50 + line_base + index
            for index in range(n_indexed_loads)
        ]
        data_physical_line = 0x60 + line_base
        index_logical_lines = [
            0x500 + line_base + index
            for index in range(n_indexed_loads)
        ]
        data_logical_line = 0x600 + line_base
        for physical_line, logical_line in zip(
            index_physical_lines, index_logical_lines):
            driver.memory.map_cache_line(physical_line, logical_line, ordering)
        driver.memory.map_cache_line(data_physical_line, data_logical_line, ordering)

        source_values = [
            rng.getrandbits(params.word_width)
            for _ in range(vector_len)
        ]
        permutation = list(range(vector_len))
        rng.shuffle(permutation)
        write_indexed_load_permutation_inputs(
            driver,
            params,
            data_logical_line,
            index_logical_lines,
            source_values,
            permutation,
            line_bytes,
        )

        await load_indexed_load_offsets(
            driver,
            params,
            ordering,
            index_physical_lines,
            data_logical_line,
            index_base_refs,
            data_base_ref,
            start_ref,
            end_ref,
            rf_indexes,
            permutation,
            line_bytes,
            ident_base,
        )
        enqueue_parallel_indexed_loads(
            driver,
            params,
            rf_indexes,
            rf_dsts,
            data_base_ref,
            start_ref,
            end_ref,
            ident_base + 20,
        )
        for op_index, rf_dst in enumerate(rf_dsts):
            expected = indexed_load_expected_values(
                params, source_values, permutation, op_index)
            await driver.wait_for_rf_elements(rf_dst, ordering, expected, 4_000)


def write_indexed_store_permutation_inputs(
    driver: KamletMeshWithMemletsDriver,
    params: ZamletParams,
    source_logical_lines: list[int],
    index_logical_lines: list[int],
    source_values: list[int],
    permutation: list[int],
    line_bytes: int,
) -> None:
    for op_index, logical_line in enumerate(source_logical_lines):
        source_data = bytearray(line_bytes)
        start_element = op_index * params.j_in_l
        for lane_index in range(params.j_in_l):
            value = source_values[start_element + lane_index]
            start = lane_index * params.word_bytes
            source_data[start:start + params.word_bytes] = value.to_bytes(
                params.word_bytes, 'little')
        driver.memory.write_logical_bytes(
            logical_line * line_bytes, bytes(source_data))

    for op_index, logical_line in enumerate(index_logical_lines):
        index_data = bytearray(line_bytes)
        start_element = op_index * params.j_in_l
        for lane_index in range(params.j_in_l):
            byte_offset = permutation[start_element + lane_index] * params.word_bytes
            start = lane_index * params.word_bytes
            index_data[start:start + params.word_bytes] = byte_offset.to_bytes(
                params.word_bytes, 'little')
        driver.memory.write_logical_bytes(
            logical_line * line_bytes, bytes(index_data))


async def load_indexed_store_operands(
    driver: KamletMeshWithMemletsDriver,
    params: ZamletParams,
    ordering: Ordering,
    source_physical_lines: list[int],
    index_physical_lines: list[int],
    dest_logical_line: int,
    source_base_refs: list[int],
    index_base_refs: list[int],
    dest_base_ref: int,
    start_ref: int,
    end_ref: int,
    rf_sources: list[int],
    rf_indexes: list[int],
    source_values: list[int],
    permutation: list[int],
    line_bytes: int,
    instr_ident_base: int,
) -> None:
    setup_instrs = [
        PackedWriteParam(
            instr_ident=instr_ident_base + index,
            param_idx=base_addr_param_idx(params, base_ref),
            data=driver.memory.base_addr_for_cache_line(physical_line),
        ).encode(params)
        for index, (base_ref, physical_line) in enumerate(
            zip(source_base_refs, source_physical_lines))
    ] + [
        PackedWriteParam(
            instr_ident=instr_ident_base + 3 + index,
            param_idx=base_addr_param_idx(params, base_ref),
            data=driver.memory.base_addr_for_cache_line(physical_line),
        ).encode(params)
        for index, (base_ref, physical_line) in enumerate(
            zip(index_base_refs, index_physical_lines))
    ] + [
        PackedWriteParam(
            instr_ident=instr_ident_base + 6,
            param_idx=base_addr_param_idx(params, dest_base_ref),
            data=dest_logical_line * line_bytes,
        ).encode(params),
        PackedWriteParam(
            instr_ident=instr_ident_base + 7,
            param_idx=start_index_param_idx(params, start_ref),
            data=0,
        ).encode(params),
        PackedWriteParam(
            instr_ident=instr_ident_base + 8,
            param_idx=end_index_param_idx(params, end_ref),
            data=params.j_in_l,
        ).encode(params),
    ]
    load_source_instrs = [
        PackedLoadSimple(
            rf_addr=rf_source,
            base_addr_param_idx=source_base_ref,
            start_index_param_idx=start_ref,
            end_index_param_idx=end_ref,
            ew=ElementWidthCode.EW64,
            instr_ident=instr_ident_base + 9 + index,
        ).encode(params)
        for index, (rf_source, source_base_ref) in enumerate(
            zip(rf_sources, source_base_refs))
    ]
    load_index_instrs = [
        PackedLoadSimple(
            rf_addr=rf_index,
            base_addr_param_idx=index_base_ref,
            start_index_param_idx=start_ref,
            end_index_param_idx=end_ref,
            ew=ElementWidthCode.EW64,
            instr_ident=instr_ident_base + 12 + index,
        ).encode(params)
        for index, (rf_index, index_base_ref) in enumerate(
            zip(rf_indexes, index_base_refs))
    ]
    driver.enqueue_instructions(setup_instrs + load_source_instrs + load_index_instrs)

    for op_index, rf_source in enumerate(rf_sources):
        start = op_index * params.j_in_l
        await driver.wait_for_rf_elements(
            rf_source,
            ordering,
            source_values[start:start + params.j_in_l],
            2_000,
        )
    for op_index, rf_index in enumerate(rf_indexes):
        start = op_index * params.j_in_l
        offsets = [
            permutation[element_index] * params.word_bytes
            for element_index in range(start, start + params.j_in_l)
        ]
        await driver.wait_for_rf_elements(rf_index, ordering, offsets, 2_000)


def enqueue_parallel_indexed_stores(
    driver: KamletMeshWithMemletsDriver,
    params: ZamletParams,
    rf_sources: list[int],
    rf_indexes: list[int],
    dest_base_ref: int,
    start_ref: int,
    end_ref: int,
    instr_ident_base: int,
) -> None:
    indexed_store_instrs = [
        PackedStoreIndexedUnordered(
            reg=rf_source,
            index_reg=rf_index,
            fault_sync_ident=index + 1,
            completion_sync_ident=index + 4,
            base_addr_param_idx=dest_base_ref,
            start_index_param_idx=start_ref,
            end_index_param_idx=end_ref,
            rf_ew=ElementWidthCode.EW64,
            index_ew=ElementWidthCode.EW64,
            instr_ident=instr_ident_base + index,
        ).encode(params)
        for index, (rf_source, rf_index) in enumerate(zip(rf_sources, rf_indexes))
    ]
    driver.enqueue_instructions(indexed_store_instrs)


def indexed_store_expected_data(
    params: ZamletParams,
    source_values: list[int],
    permutation: list[int],
    line_bytes: int,
) -> list[int]:
    expected_values = [0 for _ in source_values]
    for source_index, dest_index in enumerate(permutation):
        expected_values[dest_index] = source_values[source_index]

    expected_data = bytearray(line_bytes)
    for element_index, value in enumerate(expected_values):
        start = element_index * params.word_bytes
        expected_data[start:start + params.word_bytes] = value.to_bytes(
            params.word_bytes, 'little')
    return list(expected_data)


@cocotb.test(timeout_time=TEST_TIMEOUT_NS, timeout_unit="ns")
async def indexed_store_scatters_large_permutation(dut: HierarchyObject) -> None:
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
    n_indexed_stores = 3
    n_permutations = 3
    vector_len = n_indexed_stores * params.j_in_l
    line_bytes = params.cache_slot_words_per_jamlet * params.stripe_bytes
    assert vector_len * params.word_bytes <= line_bytes
    assert 2 * n_indexed_stores <= params.max_concurrent_syncs

    source_base_refs = list(range(n_indexed_stores))
    index_base_refs = [
        n_indexed_stores + index
        for index in range(n_indexed_stores)
    ]
    dest_base_ref = 2 * n_indexed_stores
    start_ref = 0
    end_ref = 0
    rf_sources = [
        8 + index
        for index in range(n_indexed_stores)
    ]
    rf_indexes = [
        12 + index
        for index in range(n_indexed_stores)
    ]

    for permutation_index in range(n_permutations):
        line_base = permutation_index * 0x30
        ident_base = 40 + permutation_index * 40
        source_physical_lines = [
            0x70 + line_base + index
            for index in range(n_indexed_stores)
        ]
        index_physical_lines = [
            0x80 + line_base + index
            for index in range(n_indexed_stores)
        ]
        dest_physical_line = 0x90 + line_base
        source_logical_lines = [
            0x700 + line_base + index
            for index in range(n_indexed_stores)
        ]
        index_logical_lines = [
            0x800 + line_base + index
            for index in range(n_indexed_stores)
        ]
        dest_logical_line = 0x900 + line_base
        for physical_line, logical_line in zip(
            source_physical_lines, source_logical_lines):
            driver.memory.map_cache_line(physical_line, logical_line, ordering)
        for physical_line, logical_line in zip(
            index_physical_lines, index_logical_lines):
            driver.memory.map_cache_line(physical_line, logical_line, ordering)
        driver.memory.map_cache_line(dest_physical_line, dest_logical_line, ordering)

        source_values = [
            rng.getrandbits(params.word_width)
            for _ in range(vector_len)
        ]
        permutation = list(range(vector_len))
        rng.shuffle(permutation)
        write_indexed_store_permutation_inputs(
            driver,
            params,
            source_logical_lines,
            index_logical_lines,
            source_values,
            permutation,
            line_bytes,
        )

        await load_indexed_store_operands(
            driver,
            params,
            ordering,
            source_physical_lines,
            index_physical_lines,
            dest_logical_line,
            source_base_refs,
            index_base_refs,
            dest_base_ref,
            start_ref,
            end_ref,
            rf_sources,
            rf_indexes,
            source_values,
            permutation,
            line_bytes,
            ident_base,
        )
        enqueue_parallel_indexed_stores(
            driver,
            params,
            rf_sources,
            rf_indexes,
            dest_base_ref,
            start_ref,
            end_ref,
            ident_base + 20,
        )
        await wait_for_cache_line(
            driver,
            dest_logical_line,
            indexed_store_expected_data(
                params, source_values, permutation, line_bytes),
            4_000,
        )
