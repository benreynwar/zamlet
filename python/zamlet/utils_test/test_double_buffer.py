"""Test DoubleBuffer by streaming random data with random valid/ready."""

import logging
from collections import deque
from random import Random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, ReadOnly

from zamlet import test_utils
from zamlet.utils import make_seed


logger = logging.getLogger(__name__)


async def driver(dut: HierarchyObject, rng: Random, items: list[int]) -> None:
    """Drive items into io_i with random valid gaps."""
    p_valid = 0.7
    for item in items:
        while rng.random() > p_valid:
            dut.io_i_valid.value = 0
            dut.io_i_bits.value = rng.getrandbits(len(dut.io_i_bits.value))
            await RisingEdge(dut.clock)
        dut.io_i_valid.value = 1
        dut.io_i_bits.value = item
        await ReadOnly()
        while int(dut.io_i_ready.value) == 0:
            await RisingEdge(dut.clock)
            await ReadOnly()
        await RisingEdge(dut.clock)
        dut.io_i_valid.value = 1
    dut.io_i_valid.value = 0


async def monitor(dut: HierarchyObject, rng: Random,
                  expected: list[int]) -> None:
    """Check items from io_o with random ready gaps."""
    idx = 0
    p_ready = 0.7
    while idx < len(expected):
        dut.io_o_ready.value = 1 if rng.random() < p_ready else 0
        await ReadOnly()
        if int(dut.io_o_valid.value) == 1 and int(dut.io_o_ready.value) == 1:
            got = int(dut.io_o_bits.value)
            assert got == expected[idx], (
                f"Item {idx}: expected {expected[idx]:#x}, got {got:#x}"
            )
            idx += 1
        await RisingEdge(dut.clock)
    dut.io_o_ready.value = 0


@cocotb.test()
async def test_random_stream(dut: HierarchyObject) -> None:
    """Stream random data through DoubleBuffer with random backpressure."""
    test_utils.configure_logging_sim("DEBUG")

    n_items = 100
    data_width = len(dut.io_i_bits.value)

    rng = Random(42)
    items = [rng.getrandbits(data_width) for _ in range(n_items)]

    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    dut.io_i_valid.value = 0
    dut.io_o_ready.value = 0
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)

    drv = cocotb.start_soon(driver(dut, Random(make_seed(rng)), items))
    mon = cocotb.start_soon(monitor(dut, Random(make_seed(rng)), items))

    await drv
    await mon

    logger.info(f"Streamed {n_items} items through DoubleBuffer successfully")
