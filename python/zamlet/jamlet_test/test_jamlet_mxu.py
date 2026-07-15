import json
import random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import ReadOnly, RisingEdge

from zamlet import test_utils


INT8_MIN = -128
INT8_MAX = 127
UINT32_MASK = (1 << 32) - 1


TEST_PARAMS = test_utils.get_test_params()
with open(TEST_PARAMS["params_file"]) as f:
    CONFIG = json.load(f)

GRID_ROWS = int(CONFIG["gridRows"])
GRID_COLS = int(CONFIG["gridCols"])
MXU_N = int(CONFIG["mxuN"])
N = GRID_ROWS * MXU_N
assert GRID_ROWS == GRID_COLS
assert N == GRID_COLS * MXU_N

BC_BUFFER = bool(CONFIG["bcBuffer"])
PRODUCT_LATENCY = int(BC_BUFFER)

BlockLanes = list[list[list[int | bool]]]


class ControlWaveDriver:
    def __init__(self, dut: HierarchyObject, signal_name: str):
        self.dut = dut
        self.signal_name = signal_name
        self.cycle = 0
        self.n_cycles = 0
        self.just_set = False
        self.next_n_cycles: None | int = None
        self.history = [False for _ in range(MXU_N - 1)]

    def request(self, cycles: int) -> None:
        # We are in the Writeable phase.
        assert self.n_cycles == 0
        if cycles > 0:
            self._drive([True] + self.history)
            assert not self.just_set
            self.just_set = True
            self.next_n_cycles = cycles - 1

    async def run(self) -> None:
        while True:
            await RisingEdge(self.dut.clock)
            lane0 = self.just_set or self.n_cycles > 0
            lanes = [lane0] + self.history
            if not self.just_set:
                self._drive(lanes)
            await ReadOnly()
            # Recalculate lane0 since self.just_set may have changed.
            lane0 = self.just_set or self.n_cycles > 0
            lanes[0] = lane0
            if self.n_cycles > 0:
                self.n_cycles -= 1
            self.history = lanes[:MXU_N - 1]
            if self.just_set:
                self.just_set = False
                assert self.next_n_cycles is not None
                self.n_cycles = self.next_n_cycles
            self.cycle += 1

    def _drive(self, lanes: list[bool]) -> None:
        for block_row in range(GRID_ROWS):
            for block_col in range(GRID_COLS):
                for lane, value in enumerate(lanes):
                    getattr(self.dut, f"io_{self.signal_name}_{block_row}_{block_col}_{lane}").value = int(value)


def set_boundary(dut: HierarchyObject, name: str, values: list[list[int]]) -> None:
    for outer, row in enumerate(values):
        for inner, value in enumerate(row):
            getattr(dut, f"io_{name}_{outer}_{inner}").value = value


def set_loop_control(dut: HierarchyObject, name: str, values: list[int]) -> None:
    for index, value in enumerate(values):
        getattr(dut, f"io_{name}_{index}").value = value


def zero_inputs(dut: HierarchyObject) -> None:
    for block_row in range(GRID_ROWS):
        for block_col in range(GRID_COLS):
            for lane in range(MXU_N):
                dut_signal = f"io_ewFromMemory_{block_row}_{block_col}_{lane}"
                getattr(dut, dut_signal).value = 0
                dut_signal = f"io_nsFromMemory_{block_row}_{block_col}_{lane}"
                getattr(dut, dut_signal).value = 0
                dut_signal = f"io_stepIn_{block_row}_{block_col}_{lane}"
                getattr(dut, dut_signal).value = 0
                dut_signal = f"io_completeIn_{block_row}_{block_col}_{lane}"
                getattr(dut, dut_signal).value = 0
                dut_signal = f"io_init_{block_row}_{block_col}_{lane}"
                getattr(dut, dut_signal).value = 0


def matrix_product(a: list[list[int]], b: list[list[int]]) -> list[list[int]]:
    return [
        [sum(a[row][k] * b[k][col] for k in range(N)) for col in range(N)]
        for row in range(N)
    ]


def int8_bits(value: int) -> int:
    assert INT8_MIN <= value <= INT8_MAX
    if value < 0:
        return value + 256
    return value


def drive_ab_for_cycle(
    dut: HierarchyObject,
    a: list[list[int]],
    b: list[list[int]],
    local_cycle: int,
) -> None:
    for block_row in range(GRID_ROWS):
        for block_col in range(GRID_COLS):
            shared_block = (block_row + block_col) % GRID_COLS
            for local_row in range(MXU_N):
                row = block_row * MXU_N + local_row
                k = local_cycle - local_row
                if 0 <= k < MXU_N:
                    col = shared_block * MXU_N + k
                    signal = f"io_ewFromMemory_{block_row}_{block_col}_{local_row}"
                    getattr(dut, signal).value = int8_bits(a[row][col])

            for local_col in range(MXU_N):
                col = block_col * MXU_N + local_col
                k = local_cycle - local_col
                if 0 <= k < MXU_N:
                    row = shared_block * MXU_N + k
                    signal = f"io_nsFromMemory_{block_row}_{block_col}_{local_col}"
                    getattr(dut, signal).value = int8_bits(b[row][col])


async def reset_dut(dut: HierarchyObject) -> None:
    cocotb.start_soon(Clock(dut.clock, 2, "ns").start())
    dut.reset.value = 1
    set_loop_control(dut, "ewLoop", [0 for _ in range(GRID_COLS)])
    set_loop_control(dut, "nsLoop", [0 for _ in range(GRID_ROWS)])
    zero_inputs(dut)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)


async def wait_cycles(dut: HierarchyObject, cycles: int) -> None:
    for _ in range(cycles):
        await RisingEdge(dut.clock)


def read_expected_c_half(
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
    init_driver: ControlWaveDriver,
    step_driver: ControlWaveDriver,
    complete_driver: ControlWaveDriver,
    a: list[list[int]],
    b: list[list[int]],
) -> None:

    start_cycle = step_driver.cycle
    init_driver.request(MXU_N)
    step_driver.request(N)
    for local_cycle in range(2 * MXU_N - 1):
        drive_ab_for_cycle(dut, a, b, local_cycle)
        await RisingEdge(dut.clock)

    while step_driver.cycle < start_cycle + N - 1:
        await RisingEdge(dut.clock)
    complete_driver.request(1)

    dumped = [[0 for _ in range(N)] for _ in range(N)]
    last_cycle = start_cycle + N + (MXU_N - 1) + PRODUCT_LATENCY + 2 + (2 * (MXU_N - 1)) + 1

    while step_driver.cycle <= last_cycle:
        await ReadOnly()
        for block_row in range(GRID_ROWS):
            for block_col in range(GRID_COLS):
                for local_row in range(MXU_N):
                    base_cycle = start_cycle + N + local_row + PRODUCT_LATENCY + 2
                    offset = step_driver.cycle - base_cycle
                    if 0 <= offset < 2 * MXU_N:
                        local_col = offset // 2
                        upper = offset % 2
                        value = read_expected_c_half(dut, block_row, block_col, local_row)
                        row = block_row * MXU_N + local_row
                        col = block_col * MXU_N + local_col
                        if upper:
                            dumped[row][col] |= value << 16
                        else:
                            dumped[row][col] |= value
        await RisingEdge(dut.clock)

    expected = [[value & UINT32_MASK for value in row] for row in matrix_product(a, b)]
    assert dumped == expected, f"a={a} b={b} dumped={dumped} expected={expected}"


def random_matrix(rng: random.Random) -> list[list[int]]:
    return [[rng.randint(INT8_MIN, INT8_MAX) for _ in range(N)] for _ in range(N)]


@cocotb.test()
async def test_4x4_matrix_multiply_on_2x2_mxu_grid(dut: HierarchyObject) -> None:
    rng = random.Random(TEST_PARAMS["seed"])
    await reset_dut(dut)
    step_driver = ControlWaveDriver(dut, "stepIn")
    complete_driver = ControlWaveDriver(dut, "completeIn")
    init_driver = ControlWaveDriver(dut, "init")
    cocotb.start_soon(step_driver.run())
    cocotb.start_soon(complete_driver.run())
    cocotb.start_soon(init_driver.run())
    set_loop_control(dut, "ewLoop", [1 for _ in range(GRID_COLS)])
    set_loop_control(dut, "nsLoop", [1 for _ in range(GRID_ROWS)])

    await RisingEdge(dut.clock)

    tasks = []
    for _ in range(4):
        tasks.append(cocotb.start_soon(
            matrix_multiply(
                dut,
                init_driver,
                step_driver,
                complete_driver,
                random_matrix(rng),
                random_matrix(rng),
            )
        ))
        await wait_cycles(dut, N)

    for task in tasks:
        await task
