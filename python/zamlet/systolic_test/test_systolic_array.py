import json
import random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import ReadOnly, RisingEdge

from zamlet import test_utils
from zamlet.matrix_test_utils import (
    UINT32_MASK,
    SkewedControlDriver,
    int8_bits,
    matrix_product,
    random_matrix,
)


TEST_PARAMS = test_utils.get_test_params()
with open(TEST_PARAMS["params_file"]) as f:
    CONFIG = json.load(f)

N = int(CONFIG["n"])


def set_vector(dut: HierarchyObject, name: str, values: list[int]) -> None:
    assert len(values) == N
    for index, value in enumerate(values):
        getattr(dut, f"io_{name}_{index}").value = value


def drive_control(dut: HierarchyObject, name: str, lanes: list[bool]) -> None:
    set_vector(dut, name, [int(value) for value in lanes])


def zero_inputs(dut: HierarchyObject) -> None:
    for name in ["inputIn", "weightLoadIn", "sumIn", "loadWeightIn", "startIn", "stepIn"]:
        set_vector(dut, name, [0 for _ in range(N)])


async def reset_dut(dut: HierarchyObject) -> None:
    cocotb.start_soon(Clock(dut.clock, 2, "ns").start())
    dut.reset.value = 1
    zero_inputs(dut)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)


async def wait_cycles(dut: HierarchyObject, cycles: int) -> None:
    for _ in range(cycles):
        await RisingEdge(dut.clock)


async def load_weights(
    dut: HierarchyObject,
    load_weight_driver: SkewedControlDriver,
    weights: list[list[int]],
) -> None:
    load_weight_driver.request(N)
    for local_cycle in range(N):
        row = N - 1 - local_cycle
        set_vector(dut, "weightLoadIn", [int8_bits(weights[row][col]) for col in range(N)])
        await RisingEdge(dut.clock)

    set_vector(dut, "weightLoadIn", [0 for _ in range(N)])
    while load_weight_driver.cycle < 2 * N:
        await RisingEdge(dut.clock)


async def start_weights(dut: HierarchyObject, start_driver: SkewedControlDriver) -> None:
    start_driver.request(1)
    while start_driver.cycle < 2 * N:
        await RisingEdge(dut.clock)


def drive_inputs_and_sums(
    dut: HierarchyObject,
    inputs: list[list[int]],
    local_cycle: int,
) -> None:
    input_values = []
    for row in range(N):
        output_row = local_cycle - row
        if 0 <= output_row < N:
            input_values.append(int8_bits(inputs[output_row][row]))
        else:
            input_values.append(0)

    set_vector(dut, "inputIn", input_values)
    set_vector(dut, "sumIn", [0 for _ in range(N)])


def capture_outputs(
    dut: HierarchyObject,
    captured: list[list[int | None]],
    local_cycle: int,
) -> None:
    for col in range(N):
        row = local_cycle - N - col
        if 0 <= row < N:
            captured[row][col] = int(getattr(dut, f"io_sumOut_{col}").value)


async def matrix_multiply(
    dut: HierarchyObject,
    load_weight_driver: SkewedControlDriver,
    start_driver: SkewedControlDriver,
    step_driver: SkewedControlDriver,
    inputs: list[list[int]],
    weights: list[list[int]],
) -> None:
    expected = [[value & UINT32_MASK for value in row] for row in matrix_product(inputs, weights)]

    await load_weights(dut, load_weight_driver, weights)
    await start_weights(dut, start_driver)

    start_cycle = step_driver.cycle
    step_driver.request(N)
    captured: list[list[int | None]] = [[None for _ in range(N)] for _ in range(N)]
    last_cycle = N + (N - 1) + (N - 1)

    for local_cycle in range(last_cycle + 1):
        drive_inputs_and_sums(dut, inputs, local_cycle)
        await RisingEdge(dut.clock)
        await ReadOnly()
        capture_outputs(dut, captured, local_cycle)

    zero_inputs(dut)
    assert captured == expected, (
        f"inputs={inputs} weights={weights} captured={captured} expected={expected}"
    )


@cocotb.test()
async def test_matrix_multiply(dut: HierarchyObject) -> None:
    rng = random.Random(TEST_PARAMS["seed"])
    await reset_dut(dut)

    load_weight_driver = SkewedControlDriver(
        N,
        lambda lanes: drive_control(dut, "loadWeightIn", lanes),
    )
    start_driver = SkewedControlDriver(
        N,
        lambda lanes: drive_control(dut, "startIn", lanes),
    )
    step_driver = SkewedControlDriver(
        N,
        lambda lanes: drive_control(dut, "stepIn", lanes),
    )
    cocotb.start_soon(load_weight_driver.run(dut.clock))
    cocotb.start_soon(start_driver.run(dut.clock))
    cocotb.start_soon(step_driver.run(dut.clock))

    await RisingEdge(dut.clock)

    for _ in range(4):
        await matrix_multiply(
            dut,
            load_weight_driver,
            start_driver,
            step_driver,
            random_matrix(rng, N),
            random_matrix(rng, N),
        )
        await wait_cycles(dut, N)
