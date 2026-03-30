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

    # Kamlet is east of the memlet router, so packets arrive from east
    # and responses go east.
    driver = CocotbDriver(dut, params, n_routers=n_routers,
                          send_dir='E', recv_dir='E')
    await driver.reset()
    driver.start()

    # Log coordinates for debugging
    logger.info(f"router_coords={router_coords} k_base=({k_base_x},{k_base_y})")
    from cocotb.triggers import RisingEdge, ReadOnly
    await ReadOnly()
    logger.info(f"DUT routerCoords_0: x={int(dut.io_routerCoords_0_x.value)}"
                f" y={int(dut.io_routerCoords_0_y.value)}")

    # Decode the first header to check target coords
    from zamlet.control_structures import unpack_int_to_fields
    hdr = unpack_int_to_fields(0x1fe00000022008, params.address_header_fields)
    logger.info(f"Header decoded: {hdr}")

    async def probe():
        gs = dut.slices_0.gatherSide
        rtr = dut.slices_0.router
        # Check router position
        await RisingEdge(dut.clock)
        await ReadOnly()
        logger.info(f"router thisX children: {dir(rtr)}")
        for cycle in range(30):
            await RisingEdge(dut.clock)
            await ReadOnly()
            # Check the B channel east input to the router
            bei_v = int(dut.io_bEi_0_0_valid.value)
            bei_r = int(dut.io_bEi_0_0_ready.value)
            if bei_v:
                bei_d = int(dut.io_bEi_0_0_bits_data.value)
                logger.info(f"  cycle {cycle}: bEi valid=1 ready={bei_r} data=0x{bei_d:x}")
            # Check bHo
            bho_v = int(gs.io_bHo_valid.value)
            if bho_v:
                bho_r = int(gs.io_bHo_ready.value)
                logger.info(f"  cycle {cycle}: bHo valid=1 ready={bho_r}")
            # Check if packet went out any other direction
            for d in ['N', 'S', 'E', 'W']:
                sig = f'io_b{d}o_0_0_valid'
                v = int(getattr(dut, sig).value)
                if v:
                    logger.info(f"  cycle {cycle}: {sig}=1")
    cocotb.start_soon(probe())

    await test_write_read.test_write_read(
        driver, params, router_coords, k_base_x, k_base_y)
