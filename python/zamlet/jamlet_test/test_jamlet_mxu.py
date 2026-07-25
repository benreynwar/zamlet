import json
import random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import Event, ReadOnly
from zamlet import test_utils
from zamlet.matrix_test_utils import (
    UINT32_MASK,
    SkewedControlDriver,
    int8_bits,
    matrix_product,
    random_matrix,
)
from zamlet.test_utils import PowerMeasurementWindow, next_drive_phase

TEST_PARAMS = test_utils.get_test_params()
with open(TEST_PARAMS["params_file"]) as f:
    CONFIG = json.load(f)

GRID_ROWS = int(CONFIG["gridRows"])
GRID_COLS = int(CONFIG["gridCols"])
MXU_N = int(CONFIG["mxuN"])
assert GRID_ROWS == GRID_COLS

REGISTER_BC = bool(CONFIG["registerBC"])
PRODUCT_LATENCY = int(REGISTER_BC)
REGISTER_BACKWARD_OUTPUT = bool(CONFIG["registerBackwardOutput"])
INTER_MXU_LATENCY = int(REGISTER_BACKWARD_OUTPUT)
SPLIT_C_DRAIN = bool(CONFIG["splitCDrain"])
RESET_GROUP_SIZE = int(CONFIG["resetGroupSize"])
CLOCK_PERIOD_NS = float(CONFIG["clockPeriodNs"])
CONTROL_INPUT_LATENCY = 1

BlockLanes = list[list[list[int | bool]]]


ControlDriver = SkewedControlDriver


def set_boundary(dut: HierarchyObject, name: str, values: list[list[int]]) -> None:
    for outer, row in enumerate(values):
        for inner, value in enumerate(row):
            getattr(dut, f"io_{name}_{outer}_{inner}").value = value


def set_loop_control(dut: HierarchyObject, name: str, values: list[int]) -> None:
    for index, value in enumerate(values):
        getattr(dut, f"io_{name}_{index}").value = value


def edge_controls(size: int) -> list[int]:
    return [int(index == 0 or index == size - 1) for index in range(size)]


def tile_edge_controls(grid_size: int, tile_size: int) -> list[int]:
    return [
        int(index % tile_size == 0 or index % tile_size == tile_size - 1)
        for index in range(grid_size)
    ]


def route_position(index: int, size: int) -> int:
    assert size % 2 == 0
    if index % 2 == 0:
        return index // 2
    return size - ((index + 1) // 2)


def matrix_block_sizes() -> list[int]:
    size = 2
    sizes = []
    while size <= GRID_ROWS:
        sizes.append(size)
        size *= 2
    return sizes


def mxu_grid_cycles(matrix_blocks: int) -> int:
    return (MXU_N + INTER_MXU_LATENCY) * matrix_blocks


def zero_inputs(dut: HierarchyObject) -> None:
    for block_row in range(GRID_ROWS):
        for block_col in range(GRID_COLS):
            for lane in range(MXU_N):
                dut_signal = f"io_ewFromMemory_{block_row}_{block_col}_{lane}"
                getattr(dut, dut_signal).value = 0
                dut_signal = f"io_nsFromMemory_{block_row}_{block_col}_{lane}"
                getattr(dut, dut_signal).value = 0
    dut.io_stepIn.value = 0
    dut.io_completeIn.value = 0
    dut.io_init.value = 0


def drive_ab_for_cycle(
    dut: HierarchyObject,
    tile_block_row: int,
    tile_block_col: int,
    matrix_blocks: int,
    a: list[list[int]],
    b: list[list[int]],
    local_cycle: int,
) -> None:
    for local_block_row in range(matrix_blocks):
        for local_block_col in range(matrix_blocks):
            block_row = tile_block_row + local_block_row
            block_col = tile_block_col + local_block_col
            shared_block = (
                route_position(local_block_row, matrix_blocks)
                + route_position(local_block_col, matrix_blocks)
            ) % matrix_blocks
            for local_row in range(MXU_N):
                row = local_block_row * MXU_N + local_row
                k = local_cycle - local_row
                if 0 <= k < MXU_N:
                    col = shared_block * MXU_N + k
                    signal = f"io_ewFromMemory_{block_row}_{block_col}_{local_row}"
                    getattr(dut, signal).value = int8_bits(a[row][col])

            for local_col in range(MXU_N):
                col = local_block_col * MXU_N + local_col
                k = local_cycle - local_col
                if 0 <= k < MXU_N:
                    row = shared_block * MXU_N + k
                    signal = f"io_nsFromMemory_{block_row}_{block_col}_{local_col}"
                    getattr(dut, signal).value = int8_bits(b[row][col])


async def reset_dut(dut: HierarchyObject) -> None:
    if hasattr(dut, "VPWR"):
        dut.VPWR.value = 1
    if hasattr(dut, "VGND"):
        dut.VGND.value = 0
    if hasattr(dut, "powerDumpEnable"):
        dut.powerDumpEnable.value = 0
    cocotb.start_soon(Clock(dut.clock, CLOCK_PERIOD_NS, "ns").start())
    dut.reset.value = 1
    set_loop_control(dut, "ewUseBackward", [0 for _ in range(GRID_COLS)])
    set_loop_control(dut, "nsUseBackward", [0 for _ in range(GRID_ROWS)])
    zero_inputs(dut)
    await wait_cycles(dut, 3 + int(RESET_GROUP_SIZE > 0))
    dut.reset.value = 0
    await wait_cycles(dut, 1 + int(RESET_GROUP_SIZE > 0))


async def wait_cycles(dut: HierarchyObject, cycles: int) -> None:
    for _ in range(cycles):
        await next_drive_phase(dut.clock)


async def send_step_wave(
    dut: HierarchyObject,
    step_driver: ControlDriver,
    matrix_blocks: int,
    start_cycle: int,
) -> None:
    step_driver.request(MXU_N)
    for block_index in range(1, matrix_blocks):
        target_cycle = start_cycle + block_index * (MXU_N + INTER_MXU_LATENCY)
        while step_driver.cycle < target_cycle:
            await next_drive_phase(dut.clock)
        step_driver.request(MXU_N)


async def send_complete_pulse(
    dut: HierarchyObject,
    complete_driver: ControlDriver,
    target_cycle: int,
) -> None:
    while complete_driver.cycle < target_cycle:
        await next_drive_phase(dut.clock)
    complete_driver.request(1)


async def feed_ab(
    dut: HierarchyObject,
    tile_inputs: dict[tuple[int, int], tuple[list[list[int]], list[list[int]]]],
    matrix_blocks: int,
    sent: Event,
) -> None:
    for local_cycle in range(2 * MXU_N - 1):
        for (tile_block_row, tile_block_col), (a, b) in tile_inputs.items():
            drive_ab_for_cycle(
                dut,
                tile_block_row,
                tile_block_col,
                matrix_blocks,
                a,
                b,
                local_cycle,
            )
        await next_drive_phase(dut.clock)
    sent.set()


def read_expected_c(
    dut: HierarchyObject,
    block_row: int,
    block_col: int,
    local_row: int,
) -> int:
    valid = int(getattr(dut, f"io_cToMemoryValid_{block_row}_{block_col}_{local_row}").value)
    assert valid == 1
    return int(getattr(dut, f"io_cToMemory_{block_row}_{block_col}_{local_row}").value)


async def matrix_multiply(
    dut: HierarchyObject,
    init_driver: ControlDriver,
    step_driver: ControlDriver,
    complete_driver: ControlDriver,
    matrix_blocks: int,
    tile_inputs: dict[tuple[int, int], tuple[list[list[int]], list[list[int]]]],
    sent: Event,
) -> None:

    matrix_n = matrix_blocks * MXU_N
    driver_start_cycle = step_driver.cycle
    start_cycle = driver_start_cycle + CONTROL_INPUT_LATENCY
    init_driver.request(MXU_N)
    cocotb.start_soon(send_step_wave(dut, step_driver, matrix_blocks, driver_start_cycle))
    cocotb.start_soon(send_complete_pulse(
        dut,
        complete_driver,
        start_cycle + mxu_grid_cycles(matrix_blocks) - 1 - CONTROL_INPUT_LATENCY,
    ))
    await wait_cycles(dut, CONTROL_INPUT_LATENCY)
    await feed_ab(dut, tile_inputs, matrix_blocks, sent)

    dumped = {
        tile: [[0 for _ in range(matrix_n)] for _ in range(matrix_n)]
        for tile in tile_inputs
    }
    output_fixed_latency = PRODUCT_LATENCY + 2 + int(SPLIT_C_DRAIN)
    last_cycle = start_cycle + mxu_grid_cycles(matrix_blocks) + (MXU_N - 1) + output_fixed_latency + (2 * (MXU_N - 1)) + 1

    while step_driver.cycle <= last_cycle:
        await ReadOnly()
        for tile_block_row, tile_block_col in tile_inputs:
            for local_block_row in range(matrix_blocks):
                for local_block_col in range(matrix_blocks):
                    block_row = tile_block_row + local_block_row
                    block_col = tile_block_col + local_block_col
                    for local_row in range(MXU_N):
                        base_cycle = start_cycle + mxu_grid_cycles(matrix_blocks) + local_row + output_fixed_latency
                        offset = step_driver.cycle - base_cycle
                        if 0 <= offset < MXU_N:
                            local_col = offset
                            value = read_expected_c(dut, block_row, block_col, local_row)
                            row = local_block_row * MXU_N + local_row
                            col = local_block_col * MXU_N + local_col
                            dumped[(tile_block_row, tile_block_col)][row][col] = value
        await next_drive_phase(dut.clock)

    for tile, (a, b) in tile_inputs.items():
        expected = [[value & UINT32_MASK for value in row] for row in matrix_product(a, b)]
        assert dumped[tile] == expected, f"tile={tile} a={a} b={b} dumped={dumped[tile]} expected={expected}"


async def record_power_window(dut: HierarchyObject, sent: list[Event]) -> None:
    power_window = PowerMeasurementWindow(dut)
    await sent[1].wait()
    power_window.start()
    await sent[-1].wait()
    power_window.stop()


def random_tile_inputs(
    rng: random.Random,
    matrix_blocks: int,
) -> dict[tuple[int, int], tuple[list[list[int]], list[list[int]]]]:
    matrix_n = matrix_blocks * MXU_N
    return {
        (tile_block_row, tile_block_col): (
            random_matrix(rng, matrix_n),
            random_matrix(rng, matrix_n),
        )
        for tile_block_row in range(0, GRID_ROWS, matrix_blocks)
        for tile_block_col in range(0, GRID_COLS, matrix_blocks)
    }


@cocotb.test()
async def test_4x4_matrix_multiply_on_2x2_mxu_grid(dut: HierarchyObject) -> None:
    rng = random.Random(TEST_PARAMS["seed"])
    await reset_dut(dut)
    step_driver = ControlDriver(dut, "stepIn")
    complete_driver = ControlDriver(dut, "completeIn")
    init_driver = ControlDriver(dut, "init")
    cocotb.start_soon(step_driver.run())
    cocotb.start_soon(complete_driver.run())
    cocotb.start_soon(init_driver.run())

    await next_drive_phase(dut.clock)

    for matrix_blocks in matrix_block_sizes():
        set_loop_control(dut, "ewUseBackward", tile_edge_controls(GRID_COLS, matrix_blocks))
        set_loop_control(dut, "nsUseBackward", tile_edge_controls(GRID_ROWS, matrix_blocks))

        sent = [Event() for _ in range(4)]
        power_task = cocotb.start_soon(record_power_window(dut, sent))
        tasks = []
        for matrix_index in range(4):
            tasks.append(cocotb.start_soon(
                matrix_multiply(
                    dut,
                    init_driver,
                    step_driver,
                    complete_driver,
                    matrix_blocks,
                    random_tile_inputs(rng, matrix_blocks),
                    sent[matrix_index],
                )
            ))
            await wait_cycles(dut, mxu_grid_cycles(matrix_blocks))

        for task in tasks:
            await task
        await power_task
