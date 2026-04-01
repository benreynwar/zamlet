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


async def run_slot_exhaustion(driver: MemletDriver, timeout: int = 10000) -> None:
    """Fire more concurrent writes than gathering slots to force drops and retries."""
    rng = Random(4)
    spacing = driver.params.cache_line_bytes
    n_writes = driver.params.n_memlet_gathering_slots * 3

    async def watchdog():
        for _ in range(timeout):
            await driver.tick()
        raise TimeoutError(f"run_slot_exhaustion timed out after {timeout} cycles")

    wd = driver.start_soon(watchdog())
    driver.reset_drop_count()

    ident = 1
    write_tasks = []
    for i in range(n_writes):
        mem_addr = spacing * i
        data = random_cache_line(driver, rng)
        task = driver.start_soon(
            driver.write_cache_line(ident=ident, mem_addr=mem_addr, data=data))
        write_tasks.append((task, mem_addr, i, data))
        ident += 1

    for task, mem_addr, sram_addr, data in write_tasks:
        while not task.done():
            await driver.tick()

    read_rng = Random(4)
    for i in range(n_writes):
        mem_addr = spacing * i
        data = random_cache_line(driver, read_rng)
        read_data = await driver.read_cache_line(
            ident=ident, mem_addr=mem_addr, sram_addr=i)
        assert read_data == data
        ident += 1

    drops = driver.reset_drop_count()
    assert drops > 0, "Expected drops from slot exhaustion but got none"
    logger.info(f"run_slot_exhaustion passed ({drops} drops)")

    wd.cancel()


async def run_backpressure(driver: MemletDriver, timeout: int = 10000) -> None:
    """Stop consuming responses so backpressure propagates through the network.

    Writes several cache lines with consume_responses=False, letting a_queues
    fill up and block the routers. Then re-enables consumption and reads back.
    """
    rng = Random(5)
    spacing = driver.params.cache_line_bytes
    n_writes = 4

    async def watchdog():
        for _ in range(timeout):
            await driver.tick()
        raise TimeoutError(f"run_backpressure timed out after {timeout} cycles")

    wd = driver.start_soon(watchdog())

    driver.consume_responses = False

    ident = 1
    write_data = []
    write_tasks = []
    for i in range(n_writes):
        mem_addr = spacing * i
        data = random_cache_line(driver, rng)
        task = driver.start_soon(
            driver.write_cache_line(ident=ident, mem_addr=mem_addr, data=data))
        write_tasks.append(task)
        write_data.append((mem_addr, i, data))
        ident += 1

    # Let writes proceed with backpressure for a while.
    await driver.tick(200)

    driver.consume_responses = True

    for task in write_tasks:
        while not task.done():
            await driver.tick()

    for mem_addr, sram_addr, data in write_data:
        read_data = await driver.read_cache_line(
            ident=ident, mem_addr=mem_addr, sram_addr=sram_addr)
        assert read_data == data
        ident += 1

    wd.cancel()
    logger.info("run_backpressure passed")


async def run_write_read_line(driver: MemletDriver, timeout: int = 5000) -> None:
    """Test atomic write-line-read-line (WLRL) operations.

    First writes cache lines normally, then uses WLRL to atomically write
    new data while reading back old data from a different address.
    """
    rng = Random(6)
    spacing = driver.params.cache_line_bytes

    async def watchdog():
        for _ in range(timeout):
            await driver.tick()
        raise TimeoutError(f"run_write_read_line timed out after {timeout} cycles")

    wd = driver.start_soon(watchdog())

    ident = 1

    # Write initial data to two addresses.
    data_a = random_cache_line(driver, rng)
    data_b = random_cache_line(driver, rng)
    await driver.write_cache_line(ident=ident, mem_addr=0, data=data_a)
    ident += 1
    await driver.write_cache_line(ident=ident, mem_addr=spacing, data=data_b)
    ident += 1

    # WLRL: write new data to addr 0, read back from addr 1.
    data_c = random_cache_line(driver, rng)
    read_back = await driver.write_read_cache_line(
        ident=ident, write_mem_addr=0, read_mem_addr=spacing,
        sram_addr=0, data=data_c)
    assert read_back == data_b
    ident += 1

    # Verify the write landed by reading addr 0 back.
    read_back = await driver.read_cache_line(ident=ident, mem_addr=0, sram_addr=0)
    assert read_back == data_c

    wd.cancel()
    logger.info("run_write_read_line passed")
