"""Run the unified memlet write/read test against the Python model."""

import asyncio
import logging

from zamlet.memlet import memlet_coords
from zamlet.memlet_test.model_driver import ModelDriver
from zamlet.memlet_test.test_write_read import run_write_read
from zamlet.params import ZamletParams

logger = logging.getLogger(__name__)


async def main():
    params = ZamletParams()
    driver = ModelDriver(params, kamlet_index=0)

    router_coords = memlet_coords(params, 0)
    k_base_x = params.west_offset
    k_base_y = params.north_offset

    driver.clock.register_main()
    driver.clock.create_task(driver.clock.clock_driver())

    await driver.reset()
    driver.start()

    await run_write_read(driver, params, router_coords, k_base_x, k_base_y)
    driver.clock.running = False


def test_memlet_model():
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(main())


if __name__ == '__main__':
    test_memlet_model()
