import json
import os
import sys
import logging
from random import Random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, ReadOnly

from zamlet import test_utils


logger = logging.getLogger(__name__)


def wallace_stage_output_count(n: int) -> int:
    """Number of outputs after one Wallace reduction stage."""
    return (n // 3) * 2 + (n % 3)


def wallace_stage_sizes(num_inputs: int) -> list[int]:
    """Compute sequence of input counts for each stage."""
    sizes = [num_inputs]
    n = num_inputs
    while n > 2:
        n = wallace_stage_output_count(n)
        sizes.append(n)
    return sizes


def compute_wallace_mult_latency(config: dict) -> int:
    """Compute pipeline latency from WallaceMult config."""
    latency = 0

    if config.get("registerInput", False):
        latency += 1

    y_bits = config["yBits"]
    num_inputs = y_bits
    sizes = wallace_stage_sizes(num_inputs)
    num_stages = len(sizes) - 1

    reg_every_n = config.get("regEveryNStages")
    if reg_every_n and reg_every_n > 0:
        for stage_idx in range(num_stages - 1):
            if (stage_idx + 1) % reg_every_n == 0:
                latency += 1

    if config.get("regBeforeFinalAdd", False):
        latency += 1
    elif reg_every_n and reg_every_n > 0:
        if (num_stages) % reg_every_n == 0:
            latency += 1

    if config.get("finalAdderRegAfterSectionCalc", False):
        latency += 1

    if config.get("finalAdderRegAfterCarryCalc", False):
        latency += 1

    if config.get("registerOutput", False):
        latency += 1

    return latency


async def reset(dut: HierarchyObject) -> None:
    """Reset the module."""
    dut.io_x.value = 0
    dut.io_y.value = 0
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    dut.reset.value = 0


@cocotb.test()
async def wallace_mult_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")

    test_params = test_utils.get_test_params()
    with open(test_params['params_file']) as f:
        config = json.load(f)

    x_bits = config["xBits"]
    y_bits = config["yBits"]
    latency = compute_wallace_mult_latency(config)
    logger.info(f"Config: {x_bits}x{y_bits}, pipeline latency: {latency} cycles")

    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    await reset(dut)

    rng = Random(test_params['seed'])
    num_tests = 1000

    input_history = []

    for cycle in range(num_tests + latency):
        if cycle < num_tests:
            x = rng.randint(0, (1 << x_bits) - 1)
            y = rng.randint(0, (1 << y_bits) - 1)
            dut.io_x.value = x
            dut.io_y.value = y
            input_history.append((x, y))
        await ReadOnly()
        if cycle >= latency:
            idx = cycle - latency
            x, y = input_history[idx]
            expected = x * y
            result = int(dut.io_out.value)
            assert result == expected, \
                f"Cycle {cycle}, input {idx}: {x:#x} * {y:#x} = {result:#x}, expected {expected:#x}"
        await RisingEdge(dut.clock)


    logger.info(f"PASS: {num_tests} random multiplications verified")
