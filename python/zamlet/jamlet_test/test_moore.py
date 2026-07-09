import logging
from typing import Tuple, List

import cocotb
from cocotb import clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, ReadOnly

from zamlet import test_utils
from zamlet.params import ZamletParams


logger = logging.getLogger(__name__)


@cocotb.test()
async def indextocoordswithreg_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")

    # Load params
    test_params = test_utils.get_test_params()
    params = ZamletParams.from_file(test_params['params_file'])

    cocotb.start_soon(clock.Clock(dut.clock, 2, 'ns').start())

    n_lanes = params.k_cols * params.j_cols * params.k_rows * params.j_rows
    index_list = list(range(n_lanes)) + [0, 0]
    await RisingEdge(dut.clock)
    coords = []
    for index in index_list:
        dut.io_index.value = index
        await ReadOnly()
        x = int(dut.io_x.value)
        y = int(dut.io_y.value)
        coords.append((x, y))
        await RisingEdge(dut.clock)
    coords = coords[2:]
    assert len(coords) == n_lanes
    assert len(set(coords)) == n_lanes
    assert all(0 <= x < params.k_cols * params.j_cols for x, y in coords)
    assert all(0 <= y < params.k_rows * params.j_rows for x, y in coords)
    last_coord = None
    for coord in coords:
        if last_coord is not None:
            dist = abs(coord[0] - last_coord[0]) + abs(coord[1] - last_coord[1])
            assert dist == 1
        last_coord = coord


@cocotb.test()
async def coordstoindexwithreg_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")

    # Load params
    test_params = test_utils.get_test_params()
    params = ZamletParams.from_file(test_params['params_file'])

    cocotb.start_soon(clock.Clock(dut.clock, 2, 'ns').start())

    n_cols = params.k_cols * params.j_cols
    n_rows = params.k_rows * params.j_rows
    n_lanes = n_cols * n_rows
    coords: List[Tuple[int, int]|None] = [None] * n_lanes
    await RisingEdge(dut.clock)
    for x in range(n_cols):
        for y in range(n_rows):
            dut.io_x.value = x
            dut.io_y.value = y
            await RisingEdge(dut.clock)
            await RisingEdge(dut.clock)
            await ReadOnly()
            index = int(dut.io_index.value)
            await RisingEdge(dut.clock)
            coords[index] = (x, y)
    await RisingEdge(dut.clock)
    assert len(coords) == n_lanes
    assert len(set(coords)) == n_lanes
    assert all(xy is not None and 0 <= xy[0] < n_cols for xy in coords)
    assert all(xy is not None and 0 <= xy[1] < n_rows for xy in coords)
    last_coord = None
    for coord in coords:
        if last_coord is not None:
            dist = abs(coord[0] - last_coord[0]) + abs(coord[1] - last_coord[1])
            assert dist == 1
        last_coord = coord
