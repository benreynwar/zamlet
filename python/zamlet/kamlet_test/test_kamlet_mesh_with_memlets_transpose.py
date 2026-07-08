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
    PackedLoadSimple,
    PackedStoreIndexedUnordered,
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


TEST_TIMEOUT_NS = 3_000


logger = logging.getLogger(__name__)


async def monitor_jte_sram_writes(
    driver: KamletMeshWithMemletsDriver,
    stop: dict[str, bool],
    stats: dict[str, int | None],
    log_period_cycles: int,
) -> None:
    counts = {
        (kx, jy): 0
        for kx in range(driver.params.k_cols)
        for jy in range(driver.params.j_rows)
    }
    cycle = 0
    while not stop["done"]:
        await RisingEdge(driver.dut.clock)
        await ReadOnly()
        cycle += 1
        stats["cycles_observed"] = cycle
        for kx in range(driver.params.k_cols):
            kamlet = getattr(driver.dut.mesh, f"kamlets_{kx}_0")
            for jy in range(driver.params.j_rows):
                handler = getattr(kamlet, f"jamlets_{jy}_0").jte.handler
                if (
                    int(handler.io_sramReq_valid.value) == 1
                    and int(handler.io_sramReq_ready.value) == 1
                    and int(handler.io_sramReq_bits_isWrite.value) == 1
                ):
                    counts[(kx, jy)] += 1
                    stats["total_sram_writes"] += 1
                    if stats["first_sram_write_cycle"] is None:
                        stats["first_sram_write_cycle"] = cycle
                    stats["last_sram_write_cycle"] = cycle
        if cycle % log_period_cycles == 0:
            logger.info(
                "measured transpose progress cycles=%d jte_sram_writes=%s total=%d",
                cycle,
                counts,
                sum(counts.values()),
            )
    logger.info(
        "measured transpose final jte_sram_writes=%s total=%d",
        counts,
        sum(counts.values()),
    )


def load_params() -> ZamletParams:
    test_params = test_utils.get_test_params()
    with open(test_params["params_file"]) as f:
        return ZamletParams.from_dict(json.load(f))


def values_to_bytes(params: ZamletParams, values: list[int]) -> bytes:
    data = bytearray(len(values) * params.word_bytes)
    for element_index, value in enumerate(values):
        start = element_index * params.word_bytes
        data[start:start + params.word_bytes] = value.to_bytes(
            params.word_bytes, 'little')
    return bytes(data)


def write_word_values_to_memory(
    driver: KamletMeshWithMemletsDriver,
    params: ZamletParams,
    logical_addr: int,
    values: list[int],
) -> None:
    driver.memory.write_logical_bytes(logical_addr, values_to_bytes(params, values))


def vector_transpose_offsets(params: ZamletParams) -> list[int]:
    rows = params.k_rows * params.j_rows
    cols = params.k_cols * params.j_cols
    assert rows * cols == params.j_in_l
    return [
        (((source_index % cols) * rows) + (source_index // cols))
        * params.word_bytes
        for source_index in range(params.j_in_l)
    ]


def transpose_vector_values(params: ZamletParams, values: list[int]) -> list[int]:
    result = [0 for _ in values]
    for source_index, value in enumerate(values):
        result[vector_transpose_offsets(params)[source_index] // params.word_bytes] = (
            value
        )
    return result


def repeated_vector_transpose_expected_bytes(
    params: ZamletParams,
    source_chunks: list[list[int]],
    region_bytes: int,
) -> list[int]:
    expected_values = []
    for chunk in source_chunks:
        expected_values.extend(transpose_vector_values(params, chunk))

    expected_data = bytearray(region_bytes)
    expected_data[:len(expected_values) * params.word_bytes] = values_to_bytes(
        params, expected_values)
    return list(expected_data)


async def wait_for_logical_region(
    driver: KamletMeshWithMemletsDriver,
    logical_cache_line_addr: int,
    n_lines: int,
    expected: list[int],
    timeout_cycles: int,
) -> int:
    actual: list[int | None] = []
    for cycle in range(timeout_cycles):
        await RisingEdge(driver.dut.clock)
        await ReadOnly()
        actual = []
        for line_offset in range(n_lines):
            actual.extend(driver.memory.read_lamlet_cache_line_coherent_from_dut(
                driver.dut, logical_cache_line_addr + line_offset))
        if actual == expected:
            return cycle + 1

    for line_offset in range(n_lines):
        driver.memory.log_cache_line_debug(
            driver.dut, logical_cache_line_addr + line_offset)
    logger.error(
        'transpose destination mismatch expected_prefix=%s actual_prefix=%s',
        expected[:64],
        actual[:64],
    )
    driver.log_debug_state()
    assert False, 'transpose destination region did not match'


async def load_vectors_from_cache_lines(
    driver: KamletMeshWithMemletsDriver,
    params: ZamletParams,
    ordering: Ordering,
    physical_lines: list[int],
    expected_values: list[list[int]],
    rf_addrs: list[int],
    start_ref: int,
    end_ref: int,
    instr_ident_base: int,
) -> None:
    param_ref_count = 1 << params.param_ref_idx_width
    for batch_start in range(0, len(rf_addrs), param_ref_count):
        batch_index = batch_start // param_ref_count
        batch_ident_base = instr_ident_base + batch_index * 40
        batch_stop = min(batch_start + param_ref_count, len(rf_addrs))
        batch_refs = list(range(batch_stop - batch_start))
        setup_instrs = [
            PackedWriteParam(
                instr_ident=batch_ident_base + index,
                param_idx=base_addr_param_idx(params, base_ref),
                data=driver.memory.base_addr_for_cache_line(physical_line),
            ).encode(params)
            for index, (base_ref, physical_line) in enumerate(zip(
                batch_refs, physical_lines[batch_start:batch_stop]))
        ] + [
            PackedWriteParam(
                instr_ident=batch_ident_base + 20,
                param_idx=start_index_param_idx(params, start_ref),
                data=0,
            ).encode(params),
            PackedWriteParam(
                instr_ident=batch_ident_base + 21,
                param_idx=end_index_param_idx(params, end_ref),
                data=params.j_in_l,
            ).encode(params),
        ]
        load_instrs = [
            PackedLoadSimple(
                rf_addr=rf_addr,
                base_addr_param_idx=base_ref,
                start_index_param_idx=start_ref,
                end_index_param_idx=end_ref,
                ew=ElementWidthCode.EW64,
                instr_ident=batch_ident_base + 30 + index,
            ).encode(params)
            for index, (rf_addr, base_ref) in enumerate(zip(
                rf_addrs[batch_start:batch_stop], batch_refs))
        ]
        driver.enqueue_instructions(setup_instrs + load_instrs)

        for rf_addr, values in zip(
            rf_addrs[batch_start:batch_stop],
            expected_values[batch_start:batch_stop],
        ):
            await driver.wait_for_rf_elements(rf_addr, ordering, values, 2_000)


async def load_vectors_from_memory_chunk(
    driver: KamletMeshWithMemletsDriver,
    params: ZamletParams,
    ordering: Ordering,
    first_physical_line: int,
    expected_values: list[list[int]],
    rf_addrs: list[int],
    start_ref: int,
    end_ref: int,
    instr_ident_base: int,
) -> None:
    param_ref_count = 1 << params.param_ref_idx_width
    assert len(expected_values) == len(rf_addrs)
    for batch_start in range(0, len(rf_addrs), param_ref_count):
        batch_index = batch_start // param_ref_count
        batch_ident_base = instr_ident_base + batch_index * 40
        batch_stop = min(batch_start + param_ref_count, len(rf_addrs))
        batch_refs = list(range(batch_stop - batch_start))
        setup_instrs = []
        for index, base_ref in enumerate(batch_refs):
            vector_index = batch_start + index
            physical_line = (
                first_physical_line
                + vector_index // params.cache_slot_words_per_jamlet
            )
            word_index = vector_index % params.cache_slot_words_per_jamlet
            setup_instrs.append(PackedWriteParam(
                instr_ident=batch_ident_base + index,
                param_idx=base_addr_param_idx(params, base_ref),
                data=driver.memory.base_addr_for_cache_line(
                    physical_line, word_index),
            ).encode(params))
        setup_instrs.extend([
            PackedWriteParam(
                instr_ident=batch_ident_base + 20,
                param_idx=start_index_param_idx(params, start_ref),
                data=0,
            ).encode(params),
            PackedWriteParam(
                instr_ident=batch_ident_base + 21,
                param_idx=end_index_param_idx(params, end_ref),
                data=params.j_in_l,
            ).encode(params),
        ])
        load_instrs = [
            PackedLoadSimple(
                rf_addr=rf_addr,
                base_addr_param_idx=base_ref,
                start_index_param_idx=start_ref,
                end_index_param_idx=end_ref,
                ew=ElementWidthCode.EW64,
                instr_ident=batch_ident_base + 30 + index,
            ).encode(params)
            for index, (rf_addr, base_ref) in enumerate(zip(
                rf_addrs[batch_start:batch_stop], batch_refs))
        ]
        driver.enqueue_instructions(setup_instrs + load_instrs)

        for rf_addr, values in zip(
            rf_addrs[batch_start:batch_stop],
            expected_values[batch_start:batch_stop],
        ):
            await driver.wait_for_rf_elements(rf_addr, ordering, values, 2_000)


def enqueue_repeated_vector_transpose_stores(
    driver: KamletMeshWithMemletsDriver,
    params: ZamletParams,
    rf_sources: list[int],
    rf_index: int,
    dest_base_logical_addr: int,
    start_ref: int,
    end_ref: int,
    completion_sync_ident: int,
    writeset: int,
    n_repeats: int,
) -> int:
    param_ref_count = 1 << params.param_ref_idx_width
    store_instrs = []
    group_instr_ident = 0
    n_stores = 0
    for repeat in range(n_repeats):
        for batch_start in range(0, len(rf_sources), param_ref_count):
            batch_stop = min(batch_start + param_ref_count, len(rf_sources))
            batch_sources = rf_sources[batch_start:batch_stop]
            for index in range(len(batch_sources)):
                vector_index = batch_start + index
                store_instrs.append(PackedWriteParam(
                    instr_ident=240 + index,
                    param_idx=base_addr_param_idx(params, index),
                    data=dest_base_logical_addr + vector_index * params.stripe_bytes,
                ).encode(params))
            for index, rf_source in enumerate(batch_sources):
                last_store = (
                    repeat == n_repeats - 1
                    and batch_start + index == len(rf_sources) - 1
                )
                store_instrs.append(PackedStoreIndexedUnordered(
                    reg=rf_source,
                    index_reg=rf_index,
                    fault_sync_ident=0,
                    completion_sync_ident=completion_sync_ident,
                    base_addr_param_idx=index,
                    start_index_param_idx=start_ref,
                    end_index_param_idx=end_ref,
                    rf_ew=ElementWidthCode.EW64,
                    index_ew=ElementWidthCode.EW64,
                    writeset_valid=True,
                    writeset=writeset,
                    grouped_completion=True,
                    grouped_completion_close=last_store,
                    instr_ident=group_instr_ident,
                ).encode(params))
                n_stores += 1
    driver.enqueue_instructions(store_instrs)
    return n_stores


@cocotb.test(timeout_time=TEST_TIMEOUT_NS, timeout_unit="ns")
async def grouped_indexed_store_transposes_row_major_grid(
    dut: HierarchyObject,
) -> None:
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
    n_vectors = 16
    n_repeats = 16
    vector_len = n_vectors * params.j_in_l
    n_chunks = vector_len // params.j_in_l
    assert n_chunks == n_vectors

    rf_sources = [8 + index for index in range(n_chunks)]
    rf_index = 24
    rf_dest_warm = [32 + index for index in range(n_chunks)]
    assert max(rf_dest_warm) < params.rf_slice_words

    line_bytes = params.cache_slot_words_per_jamlet * params.stripe_bytes
    region_lines = (
        (vector_len * params.word_bytes) + line_bytes - 1
    ) // line_bytes
    region_bytes = region_lines * line_bytes
    assert region_lines <= params.n_cache_slots

    source_physical_line = 0x300
    source_logical_line = 0x1300
    index_physical_line = 0x400
    index_logical_line = 0x1400
    dest_physical_line = 0x500
    dest_logical_line = 0x1500

    for line_offset in range(region_lines):
        driver.memory.map_cache_line(
            source_physical_line + line_offset,
            source_logical_line + line_offset,
            ordering,
        )
    driver.memory.map_cache_line(
        index_physical_line,
        index_logical_line,
        ordering,
    )
    for line_offset in range(region_lines):
        driver.memory.map_cache_line(
            dest_physical_line + line_offset,
            dest_logical_line + line_offset,
            ordering,
        )

    source_values = [rng.getrandbits(params.word_width) for _ in range(vector_len)]
    dest_values = [rng.getrandbits(params.word_width) for _ in range(vector_len)]
    source_chunks = [
        source_values[index * params.j_in_l:(index + 1) * params.j_in_l]
        for index in range(n_chunks)
    ]
    dest_chunks = [
        dest_values[index * params.j_in_l:(index + 1) * params.j_in_l]
        for index in range(n_chunks)
    ]
    index_values = vector_transpose_offsets(params)
    write_word_values_to_memory(
        driver, params, source_logical_line * line_bytes, source_values)
    write_word_values_to_memory(
        driver, params, index_logical_line * line_bytes, index_values)
    write_word_values_to_memory(
        driver, params, dest_logical_line * line_bytes, dest_values)

    start_ref = 0
    end_ref = 0
    await load_vectors_from_memory_chunk(
        driver,
        params,
        ordering,
        source_physical_line,
        source_chunks,
        rf_sources,
        start_ref,
        end_ref,
        1,
    )
    await load_vectors_from_memory_chunk(
        driver,
        params,
        ordering,
        index_physical_line,
        [index_values],
        [rf_index],
        start_ref,
        end_ref,
        90,
    )
    await load_vectors_from_memory_chunk(
        driver,
        params,
        ordering,
        dest_physical_line,
        dest_chunks,
        rf_dest_warm,
        start_ref,
        end_ref,
        130,
    )

    await RisingEdge(driver.dut.clock)

    n_stores = enqueue_repeated_vector_transpose_stores(
        driver,
        params,
        rf_sources,
        rf_index,
        dest_logical_line * line_bytes,
        start_ref,
        end_ref,
        completion_sync_ident=2,
        writeset=1,
        n_repeats=n_repeats,
    )
    logger.info(
        "measured transpose enqueued stores=%d expected_sram_writes=%d",
        n_stores,
        n_stores * params.j_in_l,
    )
    sram_monitor_stop = {"done": False}
    sram_monitor_stats = {
        "first_sram_write_cycle": None,
        "last_sram_write_cycle": None,
        "total_sram_writes": 0,
        "cycles_observed": 0,
    }
    sram_monitor = cocotb.start_soon(monitor_jte_sram_writes(
        driver,
        sram_monitor_stop,
        sram_monitor_stats,
        log_period_cycles=500,
    ))
    _, sync_cycles = await driver.wait_for_sync_result_cycles(
        sync_ident=2, timeout_cycles=20_000)
    sram_monitor_stop["done"] = True
    await sram_monitor
    first_write_cycle = sram_monitor_stats["first_sram_write_cycle"]
    last_write_cycle = sram_monitor_stats["last_sram_write_cycle"]
    sram_write_span = (
        None
        if first_write_cycle is None or last_write_cycle is None
        else last_write_cycle - first_write_cycle + 1
    )
    logger.info(
        (
            "measured transpose throughput enqueue_cycle=0 "
            "first_sram_write_cycle=%s last_sram_write_cycle=%s "
            "sync_complete_cycle=%d sram_write_span_cycles=%s "
            "observed_sram_writes=%d expected_sram_writes=%d"
        ),
        first_write_cycle,
        last_write_cycle,
        sync_cycles,
        sram_write_span,
        sram_monitor_stats["total_sram_writes"],
        n_stores * params.j_in_l,
    )
    visible_cycles = await wait_for_logical_region(
        driver,
        dest_logical_line,
        region_lines,
        repeated_vector_transpose_expected_bytes(
            params, source_chunks, region_bytes),
        8_000,
    )
    logger.info(
        (
            'transpose vectors=%d elements=%d '
            'repeats=%d stores=%d sync_cycles=%d visible_cycles=%d '
            'stores_per_sync_cycle=%.2f'
        ),
        n_chunks,
        vector_len,
        n_repeats,
        n_stores,
        sync_cycles,
        visible_cycles,
        n_stores / sync_cycles,
    )
