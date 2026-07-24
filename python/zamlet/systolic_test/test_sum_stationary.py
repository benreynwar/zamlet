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

N = int(CONFIG["n"])
REGISTER_BC = bool(CONFIG["registerBC"])
REGISTER_DE = bool(CONFIG["registerDE"])
SPLIT_C_DRAIN = bool(CONFIG["splitCDrain"])
RESET_GROUP_SIZE = int(CONFIG["resetGroupSize"])
CLOCK_PERIOD_NS = float(CONFIG["clockPeriodNs"])

# Fixed latency from the final A/B feed edge for a dot product to observing the
# selected sum at cOut. The top-level scalar control delay is not included here
# because the test waits one cycle after requesting first before it starts
# feed_ab.
# 1. optional BC register captures the final product.
# 2. compulsory CD accumulator register captures the completed sum.
# 3. optional DE drain register captures the selected drain value.
# 4. The normal drain has one cOut register. The split drain has either its
#    middle or upper-merge register followed by the cOut register.
OUTPUT_FIXED_LATENCY = 2 + int(REGISTER_BC) + int(REGISTER_DE) + int(SPLIT_C_DRAIN)


def set_vector(dut: HierarchyObject, name: str, values: list[int]) -> None:
    assert len(values) == N
    for index, value in enumerate(values):
        getattr(dut, f"io_{name}_{index}").value = value


def zero_inputs(dut: HierarchyObject) -> None:
    set_vector(dut, "aIn", [0 for _ in range(N)])
    set_vector(dut, "bIn", [0 for _ in range(N)])
    dut.io_firstIn.value = 0
    dut.io_finalIn.value = 0


async def wait_cycles(dut: HierarchyObject, cycles: int) -> None:
    for _ in range(cycles):
        await next_drive_phase(dut.clock)


async def reset_dut(dut: HierarchyObject) -> None:
    if hasattr(dut, "VPWR"):
        dut.VPWR.value = 1
    if hasattr(dut, "VGND"):
        dut.VGND.value = 0
    if hasattr(dut, "powerDumpEnable"):
        dut.powerDumpEnable.value = 0
    cocotb.start_soon(Clock(dut.clock, CLOCK_PERIOD_NS, "ns").start())
    dut.reset.value = 1
    zero_inputs(dut)
    await wait_cycles(dut, 4)
    dut.reset.value = 0
    await wait_cycles(dut, 1 + int(RESET_GROUP_SIZE > 0))


def drive_ab_for_cycle(
    dut: HierarchyObject,
    a: list[list[int]],
    b: list[list[int]],
    local_cycle: int,
) -> None:
    for row in range(N):
        k = local_cycle - row
        if 0 <= k < N:
            getattr(dut, f"io_aIn_{row}").value = int8_bits(a[row][k])

    for col in range(N):
        k = local_cycle - col
        if 0 <= k < N:
            getattr(dut, f"io_bIn_{col}").value = int8_bits(b[k][col])


async def feed_ab(
    dut: HierarchyObject,
    a: list[list[int]],
    b: list[list[int]],
    sent: Event,
) -> None:
    for local_cycle in range(2 * N - 1):
        drive_ab_for_cycle(dut, a, b, local_cycle)
        await next_drive_phase(dut.clock)
    sent.set()


def capture_outputs(
    dut: HierarchyObject,
    captured: list[list[int | None]],
    local_cycle: int,
) -> None:
    for col in range(N):
        row = local_cycle - (N - 1) - col - OUTPUT_FIXED_LATENCY
        if 0 <= row < N:
            captured[row][col] = int(getattr(dut, f"io_cOut_{col}").value)


async def request_final(
    dut: HierarchyObject,
    final_driver: SkewedControlDriver,
    target_cycle: int,
) -> None:
    while final_driver.cycle < target_cycle:
        await next_drive_phase(dut.clock)
    final_driver.request(1)


async def matrix_multiply(
    dut: HierarchyObject,
    first_driver: SkewedControlDriver,
    final_driver: SkewedControlDriver,
    a: list[list[int]],
    b: list[list[int]],
    sent: Event,
) -> None:
    expected = [[value & UINT32_MASK for value in row] for row in matrix_product(a, b)]
    captured: list[list[int | None]] = [[None for _ in range(N)] for _ in range(N)]

    start_cycle = first_driver.cycle
    first_driver.request(1)
    cocotb.start_soon(request_final(dut, final_driver, start_cycle + N - 1))
    await next_drive_phase(dut.clock)
    cocotb.start_soon(feed_ab(dut, a, b, sent))

    last_cycle = 3 * (N - 1) + OUTPUT_FIXED_LATENCY
    for local_cycle in range(last_cycle + 1):
        await next_drive_phase(dut.clock)
        await ReadOnly()
        capture_outputs(dut, captured, local_cycle)

    assert captured == expected, f"a={a} b={b} captured={captured} expected={expected}"


async def record_power_window(dut: HierarchyObject, sent: list[Event]) -> None:
    power_window = PowerMeasurementWindow(dut)
    await sent[1].wait()
    power_window.start()
    await sent[-1].wait()
    power_window.stop()


@cocotb.test()
async def test_matrix_multiply(dut: HierarchyObject) -> None:
    rng = random.Random(TEST_PARAMS["seed"])
    await reset_dut(dut)

    first_driver = SkewedControlDriver(dut, "firstIn")
    final_driver = SkewedControlDriver(dut, "finalIn")
    cocotb.start_soon(first_driver.run())
    cocotb.start_soon(final_driver.run())

    await next_drive_phase(dut.clock)

    sent = [Event() for _ in range(4)]
    power_task = cocotb.start_soon(record_power_window(dut, sent))
    tasks = []
    for matrix_index in range(4):
        tasks.append(cocotb.start_soon(
            matrix_multiply(
                dut,
                first_driver,
                final_driver,
                random_matrix(rng, N),
                random_matrix(rng, N),
                sent[matrix_index],
            )
        ))
        await wait_cycles(dut, N)

    for task in tasks:
        await task
    await power_task
