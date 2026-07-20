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
RESET_GROUP_SIZE = int(CONFIG["resetGroupSize"])


def set_vector(dut: HierarchyObject, name: str, values: list[int]) -> None:
    assert len(values) == N
    for index, value in enumerate(values):
        getattr(dut, f"io_{name}_{index}").value = value


def zero_inputs(dut: HierarchyObject) -> None:
    for name in ["inputIn", "weightLoadIn", "sumIn"]:
        set_vector(dut, name, [0 for _ in range(N)])
    dut.io_loadWeightIn.value = 0
    dut.io_stepIn.value = 0


async def reset_dut(dut: HierarchyObject) -> None:
    cocotb.start_soon(Clock(dut.clock, 2, "ns").start())
    dut.reset.value = 1
    zero_inputs(dut)
    await wait_cycles(dut, 4)
    dut.reset.value = 0
    await wait_cycles(dut, 1 + int(RESET_GROUP_SIZE > 0))


async def wait_cycles(dut: HierarchyObject, cycles: int) -> None:
    for _ in range(cycles):
        await RisingEdge(dut.clock)


def drive_weights(
    dut: HierarchyObject,
    weights: list[list[int]],
    local_cycle: int,
) -> None:
    for col in range(N):
        row = local_cycle - col
        if 0 <= row < N:
            getattr(dut, f"io_weightLoadIn_{col}").value = int8_bits(weights[row][col])


async def feed_weights(
    dut: HierarchyObject,
    weights: list[list[int]],
) -> None:
    for local_cycle in range(2 * N - 1):
        drive_weights(dut, weights, local_cycle)
        await RisingEdge(dut.clock)


def drive_inputs_and_sums(
    dut: HierarchyObject,
    inputs: list[list[int]],
    local_cycle: int,
) -> None:
    for row in range(N):
        k = local_cycle - row
        if 0 <= k < N:
            getattr(dut, f"io_inputIn_{row}").value = int8_bits(inputs[k][row])


async def feed_inputs_and_sums(
    dut: HierarchyObject,
    inputs: list[list[int]],
) -> None:
    for local_cycle in range(2 * N - 1):
        drive_inputs_and_sums(dut, inputs, local_cycle)
        await RisingEdge(dut.clock)


def capture_outputs(
    dut: HierarchyObject,
    captured: list[list[int | None]],
    local_cycle: int,
) -> None:
    for col in range(N):
        row = local_cycle - N - col - 1
        if 0 <= row < N:
            captured[row][col] = int(getattr(dut, f"io_sumOut_{col}").value)


async def matrix_multiply(
    dut: HierarchyObject,
    load_weight_driver: SkewedControlDriver,
    step_driver: SkewedControlDriver,
    inputs: list[list[int]],
    weights: list[list[int]],
) -> None:
    expected = [[value & UINT32_MASK for value in row] for row in matrix_product(inputs, weights)]

    # The one-cycle load pulse moves diagonally with the first step. Each A-to-B
    # boundary replaces the weight as it captures the first input of the new sum.
    load_weight_driver.request(1)
    step_driver.request(N)
    await RisingEdge(dut.clock)
    cocotb.start_soon(feed_weights(dut, weights))
    cocotb.start_soon(feed_inputs_and_sums(dut, inputs))
    captured: list[list[int | None]] = [[None for _ in range(N)] for _ in range(N)]
    last_cycle = N + (N - 1) + (N - 1) + 1

    for local_cycle in range(last_cycle + 1):
        await RisingEdge(dut.clock)
        await ReadOnly()
        capture_outputs(dut, captured, local_cycle)

    assert captured == expected, (
        f"inputs={inputs} weights={weights} captured={captured} expected={expected}"
    )


@cocotb.test()
async def test_matrix_multiply(dut: HierarchyObject) -> None:
    rng = random.Random(TEST_PARAMS["seed"])
    await reset_dut(dut)

    load_weight_driver = SkewedControlDriver(dut, "loadWeightIn")
    step_driver = SkewedControlDriver(dut, "stepIn")
    cocotb.start_soon(load_weight_driver.run())
    cocotb.start_soon(step_driver.run())

    await RisingEdge(dut.clock)

    tasks = []
    for _ in range(4):
        tasks.append(cocotb.start_soon(
            matrix_multiply(
                dut,
                load_weight_driver,
                step_driver,
                random_matrix(rng, N),
                random_matrix(rng, N),
            )
        ))
        await wait_cycles(dut, N)

    for task in tasks:
        await task
