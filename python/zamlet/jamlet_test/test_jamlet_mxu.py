import json
import random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import ReadOnly, RisingEdge

from zamlet import test_utils


GRID_N = 2
MXU_N = 2
N = GRID_N * MXU_N
INT8_MIN = -128
INT8_MAX = 127
UINT8_MASK = (1 << 8) - 1
UINT32_MASK = (1 << 32) - 1


TEST_PARAMS = test_utils.get_test_params()
with open(TEST_PARAMS["params_file"]) as f:
    CONFIG = json.load(f)

PRODUCT_LATENCY = int(CONFIG["registerProduct"])
CONTROL_INPUT_LATENCY = 2


class CycleDriver:
    def __init__(self, dut: HierarchyObject, signal_name: str):
        self.dut = dut
        self.signal = getattr(dut, signal_name)
        self.n_cycles = 0
        self.just_set = False
        self.next_n_cycles : None|int = None

    def request(self, cycles: int) -> None:
        # We are in the Writeable phase.
        assert self.n_cycles == 0
        if cycles > 0:
            # Set the value to 1
            self.signal.value = 1
            assert not self.just_set
            self.just_set = True
            self.next_n_cycles = cycles - 1

    async def run(self) -> None:
        while True:
            await RisingEdge(self.dut.clock)
            if not self.just_set:
                self.signal.value = int(self.n_cycles > 0)
            await ReadOnly()
            if self.n_cycles > 0:
                self.n_cycles -= 1
            if self.just_set:
                self.just_set = False
                assert self.next_n_cycles is not None
                self.n_cycles = self.next_n_cycles


def set_boundary(dut: HierarchyObject, name: str, values: list[list[int]]) -> None:
    for outer, row in enumerate(values):
        for inner, value in enumerate(row):
            getattr(dut, f"io_{name}_{outer}_{inner}").value = value


def set_block_lanes(
    dut: HierarchyObject,
    name: str,
    values: list[list[list[int]]],
) -> None:
    for block_row in range(GRID_N):
        for block_col in range(GRID_N):
            for lane, value in enumerate(values[block_row][block_col]):
                getattr(dut, f"io_{name}_{block_row}_{block_col}_{lane}").value = value


def zero_inputs(dut: HierarchyObject) -> None:
    set_boundary(dut, "aWestIn", [[0 for _ in range(MXU_N)] for _ in range(GRID_N)])
    set_boundary(dut, "bNorthIn", [[0 for _ in range(MXU_N)] for _ in range(GRID_N)])
    zeros = [[[0 for _ in range(MXU_N)] for _ in range(GRID_N)] for _ in range(GRID_N)]
    set_block_lanes(dut, "aStoreNorthIn", zeros)
    set_block_lanes(dut, "bStoreNorthIn", zeros)
    set_block_lanes(dut, "cEastIn", zeros)


def matrix_product(a: list[list[int]], b: list[list[int]]) -> list[list[int]]:
    return [
        [sum(a[row][k] * b[k][col] for k in range(N)) for col in range(N)]
        for row in range(N)
    ]


def make_initial_stores(
    a: list[list[int]],
    b: list[list[int]],
) -> tuple[list[list[list[list[int]]]], list[list[list[list[int]]]]]:
    a_store = [
        [[[0 for _ in range(MXU_N)] for _ in range(MXU_N)] for _ in range(GRID_N)]
        for _ in range(GRID_N)
    ]
    b_store = [
        [[[0 for _ in range(MXU_N)] for _ in range(MXU_N)] for _ in range(GRID_N)]
        for _ in range(GRID_N)
    ]
    for row in range(N):
        for col in range(N):
            k = (row + col) % N
            block_row = row // MXU_N
            block_col = col // MXU_N
            local_row = row % MXU_N
            local_col = col % MXU_N
            a_store[block_row][block_col][local_row][local_col] = a[row][k] & UINT8_MASK
            b_store[block_row][block_col][local_row][local_col] = b[k][col] & UINT8_MASK
    return a_store, b_store


async def reset_dut(dut: HierarchyObject) -> None:
    cocotb.start_soon(Clock(dut.clock, 2, "ns").start())
    dut.reset.value = 1
    dut.io_initialize.value = 0
    dut.io_storeAccumulator.value = 0
    dut.io_step.value = 0
    dut.io_load.value = 0
    dut.io_dump.value = 0
    dut.io_westLoop.value = 0
    dut.io_northLoop.value = 0
    zero_inputs(dut)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)


async def load_storage(
    dut: HierarchyObject,
    load_driver: CycleDriver,
    a_store: list[list[list[list[int]]]],
    b_store: list[list[list[list[int]]]],
) -> None:
    for local_row in reversed(range(MXU_N)):
        a_lanes = [[a_store[br][bc][local_row] for bc in range(GRID_N)] for br in range(GRID_N)]
        b_lanes = [[b_store[br][bc][local_row] for bc in range(GRID_N)] for br in range(GRID_N)]
        set_block_lanes(dut, "aStoreNorthIn", a_lanes)
        set_block_lanes(dut, "bStoreNorthIn", b_lanes)
        await RisingEdge(dut.clock)


async def wait_cycles(dut: HierarchyObject, cycles: int) -> None:
    for _ in range(cycles):
        await RisingEdge(dut.clock)


def sample_c_west(dut: HierarchyObject, local_col: int) -> list[tuple[int, int, int]]:
    samples = []
    for block_row in range(GRID_N):
        for block_col in range(GRID_N):
            for local_row in range(MXU_N):
                row = block_row * MXU_N + local_row
                col = block_col * MXU_N + local_col
                value = int(getattr(dut, f"io_cWestOut_{block_row}_{block_col}_{local_row}").value) & UINT32_MASK
                samples.append((row, col, value))
    return samples


async def matrix_multiply(
    dut: HierarchyObject,
    load_driver: CycleDriver,
    step_driver: CycleDriver,
    dump_driver: CycleDriver,
    a: list[list[int]],
    b: list[list[int]],
) -> None:

    # Drive the data in
    load_driver.request(MXU_N)
    await wait_cycles(dut, CONTROL_INPUT_LATENCY)
    a_store, b_store = make_initial_stores(a, b)
    cocotb.start_soon(load_storage(dut, load_driver, a_store, b_store))

    await wait_cycles(dut, MXU_N - CONTROL_INPUT_LATENCY)
    dut.io_initialize.value = 1
    await RisingEdge(dut.clock)
    step_driver.request(N)
    dut.io_initialize.value = 0

    await wait_cycles(dut, N + PRODUCT_LATENCY)

    dut.io_storeAccumulator.value = 1
    await RisingEdge(dut.clock)
    dut.io_storeAccumulator.value = 0
    dumped = [[0 for _ in range(N)] for _ in range(N)]
    dump_driver.request(MXU_N)

    await wait_cycles(dut, CONTROL_INPUT_LATENCY)
    for local_col in range(MXU_N):
        await ReadOnly()
        for row, col, value in sample_c_west(dut, local_col):
            dumped[row][col] = value
        await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)

    expected = [[value & UINT32_MASK for value in row] for row in matrix_product(a, b)]
    assert dumped == expected, f"a={a} b={b} dumped={dumped} expected={expected}"


def random_matrix(rng: random.Random) -> list[list[int]]:
    return [[rng.randint(INT8_MIN, INT8_MAX) for _ in range(N)] for _ in range(N)]


@cocotb.test()
async def test_4x4_matrix_multiply_on_2x2_mxu_grid(dut: HierarchyObject) -> None:
    rng = random.Random(TEST_PARAMS["seed"])
    await reset_dut(dut)
    load_driver = CycleDriver(dut, "io_load")
    step_driver = CycleDriver(dut, "io_step")
    dump_driver = CycleDriver(dut, "io_dump")
    cocotb.start_soon(load_driver.run())
    cocotb.start_soon(step_driver.run())
    cocotb.start_soon(dump_driver.run())
    dut.io_westLoop.value = 1
    dut.io_northLoop.value = 1

    await RisingEdge(dut.clock)

    tasks = []
    for _ in range(4):
        tasks.append(cocotb.start_soon(
            matrix_multiply(
                dut,
                load_driver,
                step_driver,
                dump_driver,
                random_matrix(rng),
                random_matrix(rng),
            )
        ))
        await wait_cycles(dut, N)

    for task in tasks:
        await task
