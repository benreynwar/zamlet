"""Run the unified memlet write/read test against the Python model."""

import asyncio
import logging

from zamlet.memlet_test.model_driver import ModelDriver
from zamlet.memlet_test.test_write_read import (
    run_write_read, run_multi_address, run_write_write_read_read,
    run_pipelined, run_slot_exhaustion, run_backpressure,
    run_write_read_line,
)
from zamlet.params import ZamletParams

logger = logging.getLogger(__name__)


async def main():
    driver = ModelDriver(ZamletParams(), kamlet_index=0)

    driver.clock.register_main()
    driver.clock.create_task(driver.clock.clock_driver())

    await driver.reset()
    driver.start()

    await run_write_read(driver)
    await run_multi_address(driver)
    await run_write_write_read_read(driver)
    await run_pipelined(driver)
    await run_slot_exhaustion(driver)
    await run_backpressure(driver)
    await run_write_read_line(driver)
    driver.clock.running = False


def test_memlet_model():
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(main())


if __name__ == '__main__':
    test_memlet_model()
