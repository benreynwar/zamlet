import json
import random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import ReadOnly
from zamlet import test_utils
from zamlet.maths import segmented_multiplier
from zamlet.params import ZamletParams
from zamlet.test_utils import rising_edge

OP_MUL_LOW = 0
OP_MUL_HIGH = 1
OP_ADD = 2
OP_SUB = 3


def load_params() -> ZamletParams:
    test_params = test_utils.get_test_params()
    with open(test_params["params_file"]) as f:
        return ZamletParams.from_dict(json.load(f))


def local_index_limit(params: ZamletParams, ew_log2: int) -> int:
    elements_per_word = params.word_bytes >> (ew_log2 - 3)
    return params.j_in_l * elements_per_word


def _sign_extend(value: int, width: int) -> int:
    sign_bit = 1 << (width - 1)
    return value - (1 << width) if value & sign_bit else value


def _lanes(word: int, width: int, word_width: int) -> list[int]:
    mask = (1 << width) - 1
    return [(word >> (lane * width)) & mask for lane in range(word_width // width)]


def _pack_lanes(lanes: list[int], width: int, word_mask: int) -> int:
    mask = (1 << width) - 1
    result = 0
    for lane, value in enumerate(lanes):
        result |= (value & mask) << (lane * width)
    return result & word_mask


def expected_data(
    a: int,
    b: int,
    ew_log2: int,
    signed_a: bool,
    signed_b: bool,
    op: int,
    word_width: int,
) -> int:
    element_width = 1 << ew_log2
    lane_mask = (1 << element_width) - 1
    word_mask = (1 << word_width) - 1

    if op in (OP_ADD, OP_SUB):
        result_lanes = []
        for lhs, rhs in zip(_lanes(a, element_width, word_width), _lanes(b, element_width, word_width)):
            value = lhs - rhs if op == OP_SUB else lhs + rhs
            result_lanes.append(value & lane_mask)
        return _pack_lanes(result_lanes, element_width, word_mask)

    product_mask = (1 << (2 * element_width)) - 1
    result_lanes = []
    for lhs_raw, rhs_raw in zip(_lanes(a, element_width, word_width), _lanes(b, element_width, word_width)):
        lhs = _sign_extend(lhs_raw, element_width) if signed_a else lhs_raw
        rhs = _sign_extend(rhs_raw, element_width) if signed_b else rhs_raw
        product = (lhs * rhs) & product_mask
        if op == OP_MUL_HIGH:
            result_lanes.append((product >> element_width) & lane_mask)
        else:
            result_lanes.append(product & lane_mask)
    return _pack_lanes(result_lanes, element_width, word_mask)


def expected_mask(
    in_m: int,
    ew_log2: int,
    wf_log2: int,
    start_index: int,
    end_index: int,
    lane_index: int,
    word_bytes: int,
    j_in_l: int,
) -> int:
    bit_mask = 0
    elements_per_wf_log2 = max(wf_log2 - ew_log2, 0)
    wf_element_stride = (1 << elements_per_wf_log2) * j_in_l

    for byte in range(word_bytes):
        local_element_slot = byte >> (ew_log2 - 3)
        wf_group = local_element_slot >> elements_per_wf_log2
        element_in_wf = local_element_slot - (wf_group << elements_per_wf_log2)
        element_index = lane_index + wf_group * wf_element_stride + element_in_wf
        in_bounds = start_index <= element_index < end_index
        mask_bit = (in_m >> local_element_slot) & 1
        if in_bounds and mask_bit:
            bit_mask |= 0xff << (byte * 8)

    return bit_mask & ((1 << (word_bytes * 8)) - 1)


async def reset_dut(dut: HierarchyObject) -> None:
    cocotb.start_soon(Clock(dut.clock, 2, "ns").start())
    dut.reset.value = 1
    dut.io_input_valid.value = 0
    dut.io_input_bits_inA.value = 0
    dut.io_input_bits_inB.value = 0
    dut.io_input_bits_inM.value = 0
    dut.io_input_bits_ew.value = 3
    dut.io_input_bits_wf.value = 3
    dut.io_input_bits_startIndex.value = 0
    dut.io_input_bits_endIndex.value = 0
    dut.io_input_bits_laneIndex.value = 0
    dut.io_input_bits_isSignedA.value = 0
    dut.io_input_bits_isSignedB.value = 0
    dut.io_input_bits_op.value = 0
    dut.io_input_bits_useUpper.value = 0
    await rising_edge(dut.clock)
    dut.reset.value = 0
    await rising_edge(dut.clock)


def make_case(
    a: int,
    b: int,
    ew_log2: int,
    op: int,
    signed_a: bool = False,
    signed_b: bool = False,
    wf_log2: int | None = None,
    in_m: int = 0xff,
    start_index: int = 0,
    end_index: int | None = None,
    lane_index: int = 0,
    params: ZamletParams | None = None,
) -> tuple[int, int, int, int, int, int, int, int, bool, bool, int]:
    word_width = params.word_width if params is not None else 64
    word_mask = (1 << word_width) - 1
    default_end_index = local_index_limit(params, ew_log2) if params is not None else None
    return (
        a & word_mask,
        b & word_mask,
        in_m & word_mask,
        ew_log2,
        ew_log2 if wf_log2 is None else wf_log2,
        start_index,
        default_end_index if end_index is None else end_index,
        lane_index,
        signed_a,
        signed_b,
        op,
    )


async def run_cases(
    dut: HierarchyObject,
    params: ZamletParams,
    cases: list[tuple[int, int, int, int, int, int, int, int, bool, bool, int]],
) -> None:
    history = []
    word_mask = (1 << params.word_width) - 1
    latency = segmented_multiplier.latency(params.word_width)

    for cycle in range(len(cases) + latency):
        if cycle < len(cases):
            a, b, in_m, ew_log2, wf_log2, start_index, end_index, lane_index, signed_a, signed_b, op = cases[cycle]
            dut.io_input_valid.value = 1
            dut.io_input_bits_inA.value = a
            dut.io_input_bits_inB.value = b
            dut.io_input_bits_inM.value = in_m
            dut.io_input_bits_ew.value = ew_log2
            dut.io_input_bits_wf.value = wf_log2
            dut.io_input_bits_startIndex.value = start_index
            dut.io_input_bits_endIndex.value = end_index
            dut.io_input_bits_laneIndex.value = lane_index
            dut.io_input_bits_isSignedA.value = int(signed_a)
            dut.io_input_bits_isSignedB.value = int(signed_b)
            dut.io_input_bits_op.value = op
            dut.io_input_bits_useUpper.value = 0
            history.append(cases[cycle])
        else:
            dut.io_input_valid.value = 0

        await ReadOnly()
        if cycle >= latency:
            assert int(dut.io_output_valid.value) == 1
            a, b, in_m, ew_log2, wf_log2, start_index, end_index, lane_index, signed_a, signed_b, op = history[
                cycle - latency
            ]
            expected = expected_data(a, b, ew_log2, signed_a, signed_b, op, params.word_width)
            expected_enable = expected_mask(
                in_m,
                ew_log2,
                wf_log2,
                start_index,
                end_index,
                lane_index,
                params.word_bytes,
                params.j_in_l,
            )
            actual = int(dut.io_output_bits_data.value) & word_mask
            actual_enable = int(dut.io_output_bits_mask.value) & word_mask
            assert actual == expected, (
                f"cycle={cycle} op={op} ew={1 << ew_log2} "
                f"a=0x{a:016x} b=0x{b:016x} actual=0x{actual:016x} expected=0x{expected:016x}"
            )
            assert actual_enable == expected_enable, (
                f"cycle={cycle} ew={1 << ew_log2} wf={1 << wf_log2} "
                f"mask actual=0x{actual_enable:016x} expected=0x{expected_enable:016x}"
            )
            assert int(dut.io_errors_unsupportedEw.value) == 0
            assert int(dut.io_errors_unsupportedWf.value) == 0
            assert int(dut.io_errors_unsupportedEwWfRatio.value) == 0

        await rising_edge(dut.clock)


@cocotb.test()
async def jamlet_alu_edges(dut: HierarchyObject) -> None:
    params = load_params()
    await reset_dut(dut)

    cases = []
    edge_pairs = [
        (0x0000000000000000, 0x0000000000000001),
        (0xffffffffffffffff, 0x0000000000000001),
        (0x0102030405060708, 0x0807060504030201),
        (0x7f807fff80000001, 0x0202ffff00010003),
    ]
    for ew_log2 in (3, 4, 5, 6):
        for a, b in edge_pairs:
            cases.append(make_case(a, b, ew_log2, OP_ADD, params=params))
            cases.append(make_case(a, b, ew_log2, OP_SUB, params=params))
            for signed_a in (False, True):
                for signed_b in (False, True):
                    cases.append(make_case(a, b, ew_log2, OP_MUL_LOW, signed_a, signed_b, params=params))
                    cases.append(make_case(a, b, ew_log2, OP_MUL_HIGH, signed_a, signed_b, params=params))

    cases.append(make_case(
        0x0102030405060708,
        0x0807060504030201,
        3,
        OP_ADD,
        wf_log2=4,
        in_m=0b1010_1101,
        start_index=1,
        end_index=6,
        params=params,
    ))

    await run_cases(dut, params, cases)


@cocotb.test()
async def jamlet_alu_random(dut: HierarchyObject) -> None:
    params = load_params()
    await reset_dut(dut)
    rng = random.Random(0xA10)

    cases = []
    for _ in range(200):
        ew_log2 = rng.choice((3, 4, 5, 6))
        wf_log2 = rng.choice(tuple(range(ew_log2, 7)))
        index_limit = local_index_limit(params, ew_log2)
        start_index = rng.randrange(index_limit)
        end_index = rng.randrange(start_index + 1, index_limit + 1)
        cases.append(make_case(
            rng.getrandbits(params.word_width),
            rng.getrandbits(params.word_width),
            ew_log2,
            rng.choice((OP_ADD, OP_SUB, OP_MUL_LOW, OP_MUL_HIGH)),
            bool(rng.randrange(2)),
            bool(rng.randrange(2)),
            wf_log2=wf_log2,
            in_m=rng.getrandbits(8),
            start_index=start_index,
            end_index=end_index,
            lane_index=rng.randrange(params.j_in_l),
            params=params,
        ))

    await run_cases(dut, params, cases)
