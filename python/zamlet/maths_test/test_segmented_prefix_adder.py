import json
import logging
from random import Random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import ReadOnly
from zamlet import test_utils
from zamlet.test_utils import rising_edge

logger = logging.getLogger(__name__)


TEST_PARAMS = test_utils.get_test_params()
with open(TEST_PARAMS["params_file"]) as f:
    CONFIG = json.load(f)

WIDTH = CONFIG["width"]
LATENCY = (
    int(CONFIG["registerInput"]) +
    int(CONFIG["registerMiddle"]) +
    int(CONFIG["registerOutput"])
)
MASK = (1 << WIDTH) - 1


def expected_sum(a: int, b: int, element_width: int, subtract: bool) -> int:
    lane_mask = (1 << element_width) - 1
    lanes = WIDTH // element_width
    result = 0

    for lane in range(lanes):
        shift = lane * element_width
        a_lane = (a >> shift) & lane_mask
        b_lane = (b >> shift) & lane_mask
        if subtract:
            lane_result = (a_lane - b_lane) & lane_mask
        else:
            lane_result = (a_lane + b_lane) & lane_mask
        result |= lane_result << shift

    return result & MASK


async def reset(dut: HierarchyObject) -> None:
    dut.io_input_valid.value = 0
    dut.io_input_bits_a.value = 0
    dut.io_input_bits_b.value = 0
    dut.io_input_bits_subtract.value = 0
    dut.io_input_bits_elementWidthLog2.value = 3
    dut.reset.value = 1
    await rising_edge(dut.clock)
    dut.reset.value = 0
    await rising_edge(dut.clock)


async def run_cases(dut: HierarchyObject, cases: list[tuple[int, int, int, bool]]) -> None:
    history = []

    for cycle in range(len(cases) + LATENCY):
        if cycle < len(cases):
            a, b, element_width, subtract = cases[cycle]
            dut.io_input_valid.value = 1
            dut.io_input_bits_a.value = a
            dut.io_input_bits_b.value = b
            dut.io_input_bits_subtract.value = int(subtract)
            dut.io_input_bits_elementWidthLog2.value = element_width.bit_length() - 1
            history.append((a, b, element_width, subtract))
        else:
            dut.io_input_valid.value = 0

        await ReadOnly()
        if cycle >= LATENCY:
            assert int(dut.io_output_valid.value) == 1
            case = history[cycle - LATENCY]
            actual = int(dut.io_output_bits_sum.value) & MASK
            expected = expected_sum(*case)
            assert actual == expected, (
                f"cycle={cycle} a=0x{case[0]:016x} b=0x{case[1]:016x} "
                f"ew={case[2]} subtract={case[3]} "
                f"actual=0x{actual:016x} expected=0x{expected:016x}"
            )

        await rising_edge(dut.clock)


@cocotb.test()
async def segmented_prefix_adder_edges(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())
    await reset(dut)

    cases = []
    edge_pairs = [
        (0x0000000000000000, 0x0000000000000000),
        (0xffffffffffffffff, 0x0000000000000001),
        (0x0102030405060708, 0x0807060504030201),
        (0x7f807fff80000001, 0x0202ffff00010003),
        (0x8000000000000000, 0xffffffffffffffff),
    ]

    for element_width in (8, 16, 32, 64):
        for a, b in edge_pairs:
            for subtract in (False, True):
                cases.append((a, b, element_width, subtract))

    await run_cases(dut, cases)
    logger.info("PASS: segmented prefix adder edge cases")


@cocotb.test()
async def segmented_prefix_adder_random(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())
    await reset(dut)

    rng = Random(0xADD5E6)
    cases = []
    for _ in range(500):
        cases.append((
            rng.getrandbits(WIDTH),
            rng.getrandbits(WIDTH),
            rng.choice((8, 16, 32, 64)),
            bool(rng.randrange(2)),
        ))

    await run_cases(dut, cases)
    logger.info("PASS: segmented prefix adder random cases")
