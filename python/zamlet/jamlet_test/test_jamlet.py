import json
from random import Random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import ClockCycles

from zamlet import test_utils
from zamlet.jamlet_test.jamlet_driver import JamletDriver
from zamlet.params import ZamletParams
from zamlet.utils import make_seed


async def timeout_watchdog(driver: JamletDriver, timeout_cycles: int) -> None:
    dut = driver.dut
    await ClockCycles(dut.clock, timeout_cycles)
    raise AssertionError(
        f"test timed out after {timeout_cycles} cycles: {driver.status()}")


@cocotb.test()
async def jamlet_cache_line_roundtrip(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim()
    test_params = test_utils.get_test_params()
    with open(test_params["params_file"]) as f:
        params = ZamletParams.from_dict(json.load(f))

    rng = Random(test_params["seed"])
    this_x = rng.randrange(1 << params.x_pos_width)
    this_y = rng.randrange(1 << params.y_pos_width)
    memlet_x = rng.randrange(1 << params.x_pos_width)
    memlet_y = rng.randrange(1 << params.y_pos_width)
    clock_period_ns = 2
    timeout_cycles = 500
    driver = JamletDriver(
        dut, params, this_x, this_y, memlet_x, memlet_y,
        seed=make_seed(rng))
    cocotb.start_soon(Clock(dut.clock, clock_period_ns, "ns").start())
    cocotb.start_soon(timeout_watchdog(driver, timeout_cycles))
    await driver.reset()
    driver.start()

    slot = 1
    words = [
        rng.getrandbits(8 * params.word_bytes)
        for _ in range(params.cache_slot_words_per_jamlet)
    ]

    await driver.send_read_line_resp(slot, words)
    actual = await driver.send_cache_line(slot)

    assert actual == words
