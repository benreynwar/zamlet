"""Unified memlet write/read tests.

Tests run against both cocotb (RTL) and the Python model via the MemletDriver abstraction.
"""

import logging
from random import Random

from zamlet.memlet_test.memlet_driver import MemletDriver

logger = logging.getLogger(__name__)


def random_cache_line(driver: MemletDriver, rng: Random) -> bytes:
    """Generate a random cache line."""
    n_bytes = (driver.params.cache_slot_words_per_jamlet
               * driver.params.j_in_k * driver.params.word_bytes)
    return rng.randbytes(n_bytes)


async def run_write_read(driver: MemletDriver, timeout: int = 1000) -> None:
    """Write a cache line, read it back, and verify data matches."""
    rng = Random(0)
    data = random_cache_line(driver, rng)

    async def watchdog():
        for _ in range(timeout):
            await driver.tick()
        raise TimeoutError(f"run_write_read timed out after {timeout} cycles")

    wd = driver.start_soon(watchdog())

    await driver.write_cache_line(ident=1, mem_addr=0x1000, data=data)
    read_data = await driver.read_cache_line(ident=2, mem_addr=0x1000, sram_addr=0)
    assert read_data == data

    wd.cancel()
    logger.info("run_write_read passed")


async def run_multi_address(driver: MemletDriver, timeout: int = 3000) -> None:
    """Write and read back multiple cache lines at different addresses."""
    rng = Random(1)
    spacing = driver.params.cache_line_bytes

    async def watchdog():
        for _ in range(timeout):
            await driver.tick()
        raise TimeoutError(f"run_multi_address timed out after {timeout} cycles")

    wd = driver.start_soon(watchdog())

    ident = 1
    for i in range(4):
        mem_addr = spacing * i
        data = random_cache_line(driver, rng)
        await driver.write_cache_line(ident=ident, mem_addr=mem_addr, data=data)
        ident += 1
        read_data = await driver.read_cache_line(ident=ident, mem_addr=mem_addr, sram_addr=i)
        assert read_data == data
        ident += 1

    wd.cancel()
    logger.info("run_multi_address passed")


async def run_write_write_read_read(driver: MemletDriver, timeout: int = 3000) -> None:
    """Write two cache lines, then read both back without interleaving."""
    rng = Random(2)
    spacing = driver.params.cache_line_bytes
    data_a = random_cache_line(driver, rng)
    data_b = random_cache_line(driver, rng)

    async def watchdog():
        for _ in range(timeout):
            await driver.tick()
        raise TimeoutError(f"run_write_write_read_read timed out after {timeout} cycles")

    wd = driver.start_soon(watchdog())

    await driver.write_cache_line(ident=1, mem_addr=0, data=data_a)
    await driver.write_cache_line(ident=2, mem_addr=spacing, data=data_b)

    assert await driver.read_cache_line(ident=3, mem_addr=0, sram_addr=0) == data_a
    assert await driver.read_cache_line(ident=4, mem_addr=spacing, sram_addr=1) == data_b

    wd.cancel()
    logger.info("run_write_write_read_read passed")


async def run_pipelined(driver: MemletDriver, timeout: int = 5000) -> None:
    """Fire off several writes concurrently, read each back as it completes."""
    rng = Random(3)
    spacing = driver.params.cache_line_bytes

    async def watchdog():
        for _ in range(timeout):
            await driver.tick()
        raise TimeoutError(f"run_pipelined timed out after {timeout} cycles")

    wd = driver.start_soon(watchdog())

    ident = 1
    write_tasks = []
    for i in range(4):
        mem_addr = spacing * i
        data = random_cache_line(driver, rng)
        task = driver.start_soon(
            driver.write_cache_line(ident=ident, mem_addr=mem_addr, data=data))
        write_tasks.append((task, mem_addr, i, data))
        ident += 1

    read_tasks = []
    pending_writes = list(write_tasks)
    while pending_writes or read_tasks:
        await driver.tick()

        still_pending = []
        for task, mem_addr, sram_addr, data in pending_writes:
            if task.done():
                rt = driver.start_soon(
                    driver.read_cache_line(ident=ident, mem_addr=mem_addr,
                                           sram_addr=sram_addr))
                read_tasks.append((rt, data))
                ident += 1
            else:
                still_pending.append((task, mem_addr, sram_addr, data))
        pending_writes = still_pending

        still_reading = []
        for rt, expected in read_tasks:
            if rt.done():
                assert rt.result() == expected
            else:
                still_reading.append((rt, expected))
        read_tasks = still_reading

    wd.cancel()
    logger.info("run_pipelined passed")
