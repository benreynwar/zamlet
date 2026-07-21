from random import Random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from zamlet import test_utils
from zamlet.kamlet_test.tag_table_driver import (
    TagState,
    TagTableDriver,
)
from zamlet.test_utils import rising_edge


async def reservation_worker(
    driver: TagTableDriver,
    rng: Random,
    tag: int,
) -> int:
    resp = await driver.alloc(tag, will_write=rng.choice([False, True]))
    slot = resp.slot
    await driver.wait_for_fill_complete(slot)

    for _ in range(rng.randrange(8)):
        await rising_edge(driver.clock)
    await driver.release(slot)
    return slot


@cocotb.test()
async def alloc_fill_happy_path(dut: HierarchyObject) -> None:
    test_params = test_utils.get_test_params()
    rng = Random(test_params["seed"])
    driver = TagTableDriver(dut)

    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())
    await driver.reset()
    driver.start(rng)
    cocotb.start_soon(driver.check_errors())

    tag = 1
    resp = await driver.alloc(tag)
    slot = resp.slot
    await driver.wait_for_fill_complete(slot)

    await driver.release(slot)

    resp = await driver.claim(tag)
    assert resp.has_slot == 1
    assert resp.slot == slot
    assert resp.state == TagState.PRESENT_CLEAN
    assert resp.did_claim == 1
    await driver.release(slot)


@cocotb.test()
async def parallel_alloc_claim_release(dut: HierarchyObject) -> None:
    test_params = test_utils.get_test_params()
    rng = Random(test_params["seed"])
    driver = TagTableDriver(dut)

    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())
    await driver.reset()
    driver.start(rng)
    cocotb.start_soon(driver.check_errors())

    tasks = [
        cocotb.start_soon(reservation_worker(driver, rng, tag))
        for tag in range(16)
    ]
    for task in tasks:
        await task
