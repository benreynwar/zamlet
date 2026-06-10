"""Cocotb entry point for memlet tests.

Sets up the DUT, AXI4 slave, and CocotbDriver, then runs the
shared test functions from test_write_read.
"""

import json
import logging
from typing import List, Tuple

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from zamlet import test_utils
from zamlet.cocotb.axi_memory import Axi4Signals, AxiMemory
from zamlet.memlet import memlet_coords
from zamlet.memlet_test.cocotb_driver import CocotbDriver
from zamlet.memlet_test import test_write_read
from zamlet.params import ZamletParams

logger = logging.getLogger(__name__)


def initialize_inputs(dut: HierarchyObject, params: ZamletParams, n_routers: int,
                      k_base_x: int, k_base_y: int,
                      router_coords: List[Tuple[int, int]]) -> None:
    """Set all Memlet inputs to safe defaults."""
    dut.io_controlBHo_valid.value = 0
    dut.io_controlBHo_bits_data.value = 0
    dut.io_controlBHo_bits_isHeader.value = 0
    dut.io_controlAHi_ready.value = 1
    for r, (rx, ry) in enumerate(router_coords):
        getattr(dut, f'io_routerCoords_{r}_x').value = rx
        getattr(dut, f'io_routerCoords_{r}_y').value = ry
    local_jamlets = params.j_in_k // n_routers
    for r in range(n_routers):
        for local_j in range(local_jamlets):
            j = r * local_jamlets + local_j
            getattr(dut, f'io_jamletCoords_{r}_{local_j}_x').value = (
                k_base_x + j % params.j_cols)
            getattr(dut, f'io_jamletCoords_{r}_{local_j}_y').value = (
                k_base_y + j // params.j_cols)

    directions = ['N', 'S', 'E', 'W']
    for d in directions:
        for r in range(n_routers):
            for ch in range(1):
                for prefix in ['a', 'b']:
                    getattr(dut, f'io_{prefix}{d}i_{r}_{ch}_valid').value = 0
                    getattr(dut, f'io_{prefix}{d}i_{r}_{ch}_bits_data').value = 0
                    getattr(dut, f'io_{prefix}{d}i_{r}_{ch}_bits_isHeader').value = 0
                    getattr(dut, f'io_{prefix}{d}o_{r}_{ch}_ready').value = 1


@cocotb.test()
async def memlet_write_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    test_params = test_utils.get_test_params()
    with open(test_params['params_file']) as f:
        params = ZamletParams.from_dict(json.load(f))

    router_coords = memlet_coords(params, 0)
    n_routers = len(router_coords)
    k_base_x = params.west_offset
    k_base_y = params.north_offset

    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    initialize_inputs(dut, params, n_routers, k_base_x, k_base_y, router_coords)

    axi = AxiMemory(
        Axi4Signals.from_prefix(dut, "io_axi"),
        dut.clock,
        word_bytes=params.word_bytes)
    axi.start()

    driver = CocotbDriver(dut, params, router_coords=router_coords,
                          k_base_x=k_base_x, k_base_y=k_base_y)
    await driver.reset()
    driver.start()

    await test_write_read.run_write_read(driver)
    await test_write_read.run_multi_address(driver)
    await test_write_read.run_write_write_read_read(driver)
    await test_write_read.run_pipelined(driver)

    axi.aw_p_ready = 0.1
    axi.w_p_ready = 0.1
    await test_write_read.run_slot_exhaustion(driver)
    axi.aw_p_ready = 1.0
    axi.w_p_ready = 1.0

    await test_write_read.run_backpressure(driver)
    await test_write_read.run_write_read_line(driver)
