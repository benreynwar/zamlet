import logging
from random import Random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import ReadOnly
from zamlet import test_utils
from zamlet.maths import segmented_multiplier
from zamlet.test_utils import next_drive_phase

logger = logging.getLogger(__name__)


WIDTH = 64
MIN_WIDTH = 8
LATENCY = segmented_multiplier.latency(WIDTH, min_width=MIN_WIDTH)
PRODUCT_MASK = (1 << (2 * WIDTH)) - 1


def sign_extend(value: int, width: int) -> int:
    sign_bit = 1 << (width - 1)
    return value - (1 << width) if value & sign_bit else value


def expected_segmented_product(
    a: int,
    b: int,
    element_width: int,
    signed_a: bool,
    signed_b: bool,
) -> int:
    lane_mask = (1 << element_width) - 1
    product_mask = (1 << (2 * element_width)) - 1
    lanes = WIDTH // element_width
    product = 0

    for lane in range(lanes):
        a_lane = (a >> (lane * element_width)) & lane_mask
        b_lane = (b >> (lane * element_width)) & lane_mask
        lhs = sign_extend(a_lane, element_width) if signed_a else a_lane
        rhs = sign_extend(b_lane, element_width) if signed_b else b_lane
        lane_product = (lhs * rhs) & product_mask
        product |= lane_product << (lane * 2 * element_width)

    return product & PRODUCT_MASK


async def reset(dut: HierarchyObject) -> None:
    dut.io_input_valid.value = 0
    dut.io_input_bits_a.value = 0
    dut.io_input_bits_b.value = 0
    dut.io_input_bits_signedA.value = 0
    dut.io_input_bits_signedB.value = 0
    dut.io_input_bits_elementWidthLog2.value = 3
    dut.reset.value = 1
    await next_drive_phase(dut.clock)
    dut.reset.value = 0
    await next_drive_phase(dut.clock)


async def run_cases(dut: HierarchyObject, cases: list[tuple[int, int, int, bool, bool]]) -> None:
    history = []

    for cycle in range(len(cases) + LATENCY):
        if cycle < len(cases):
            a, b, element_width, signed_a, signed_b = cases[cycle]
            dut.io_input_valid.value = 1
            dut.io_input_bits_a.value = a
            dut.io_input_bits_b.value = b
            dut.io_input_bits_signedA.value = int(signed_a)
            dut.io_input_bits_signedB.value = int(signed_b)
            dut.io_input_bits_elementWidthLog2.value = element_width.bit_length() - 1
            history.append((a, b, element_width, signed_a, signed_b))
        else:
            dut.io_input_valid.value = 0

        await ReadOnly()
        if cycle >= LATENCY:
            assert int(dut.io_output_valid.value) == 1
            case = history[cycle - LATENCY]
            expected = expected_segmented_product(*case)
            actual = int(dut.io_output_bits_product.value) & PRODUCT_MASK
            assert actual == expected, (
                f"cycle={cycle} a=0x{case[0]:016x} b=0x{case[1]:016x} "
                f"ew={case[2]} signed=({case[3]},{case[4]}) "
                f"actual=0x{actual:032x} expected=0x{expected:032x}"
            )

        await next_drive_phase(dut.clock)


@cocotb.test()
async def segmented_multiplier_edges(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())
    await reset(dut)

    cases = []
    edge_pairs = [
        (0x0000000000000000, 0xffffffffffffffff),
        (0x0102030405060708, 0x0807060504030201),
        (0x7f807fff80000001, 0x0202ffff00010003),
        (0x8000000000000000, 0xffffffffffffffff),
        (0xffffffffffffffff, 0xffffffffffffffff),
    ]

    for element_width in (8, 16, 32, 64):
        for a, b in edge_pairs:
            for signed_a in (False, True):
                for signed_b in (False, True):
                    cases.append((a, b, element_width, signed_a, signed_b))

    await run_cases(dut, cases)
    logger.info("PASS: segmented multiplier edge cases")


@cocotb.test()
async def segmented_multiplier_random(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())
    await reset(dut)

    rng = Random(0x5E6A117ED)
    cases = []
    for _ in range(500):
        cases.append((
            rng.getrandbits(WIDTH),
            rng.getrandbits(WIDTH),
            rng.choice((8, 16, 32, 64)),
            bool(rng.randrange(2)),
            bool(rng.randrange(2)),
        ))

    await run_cases(dut, cases)
    logger.info("PASS: segmented multiplier random cases")
