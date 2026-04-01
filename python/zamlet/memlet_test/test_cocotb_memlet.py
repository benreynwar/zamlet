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
from zamlet.cocotb.axi_memory import AxiMemory
from zamlet.memlet import memlet_coords
from zamlet.memlet_test.cocotb_driver import CocotbDriver
from zamlet.memlet_test import test_write_read
from zamlet.params import ZamletParams

logger = logging.getLogger(__name__)


def initialize_inputs(dut: HierarchyObject, n_routers: int,
                      k_base_x: int, k_base_y: int,
                      router_coords: List[Tuple[int, int]]) -> None:
    """Set all Memlet inputs to safe defaults."""
    dut.io_kBaseX.value = k_base_x
    dut.io_kBaseY.value = k_base_y
    for r, (rx, ry) in enumerate(router_coords):
        getattr(dut, f'io_routerCoords_{r}_x').value = rx
        getattr(dut, f'io_routerCoords_{r}_y').value = ry

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

    initialize_inputs(dut, n_routers, k_base_x, k_base_y, router_coords)

    axi_signals = {
        'aw_valid': dut.io_axi_aw_valid,
        'aw_ready': dut.io_axi_aw_ready,
        'aw_id': dut.io_axi_aw_bits_id,
        'aw_addr': dut.io_axi_aw_bits_addr,
        'aw_len': dut.io_axi_aw_bits_len,
        'aw_size': dut.io_axi_aw_bits_size,
        'aw_burst': dut.io_axi_aw_bits_burst,
        'w_valid': dut.io_axi_w_valid,
        'w_ready': dut.io_axi_w_ready,
        'w_data': dut.io_axi_w_bits_data,
        'w_last': dut.io_axi_w_bits_last,
        'b_valid': dut.io_axi_b_valid,
        'b_ready': dut.io_axi_b_ready,
        'b_id': dut.io_axi_b_bits_id,
        'b_resp': dut.io_axi_b_bits_resp,
        'ar_valid': dut.io_axi_ar_valid,
        'ar_ready': dut.io_axi_ar_ready,
        'ar_id': dut.io_axi_ar_bits_id,
        'ar_addr': dut.io_axi_ar_bits_addr,
        'ar_len': dut.io_axi_ar_bits_len,
        'ar_size': dut.io_axi_ar_bits_size,
        'ar_burst': dut.io_axi_ar_bits_burst,
        'r_valid': dut.io_axi_r_valid,
        'r_ready': dut.io_axi_r_ready,
        'r_id': dut.io_axi_r_bits_id,
        'r_data': dut.io_axi_r_bits_data,
        'r_resp': dut.io_axi_r_bits_resp,
        'r_last': dut.io_axi_r_bits_last,
    }
    axi = AxiMemory(axi_signals, dut.clock, word_bytes=params.word_bytes)
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
