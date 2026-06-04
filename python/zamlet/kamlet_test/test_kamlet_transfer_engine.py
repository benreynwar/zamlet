import json
from random import Random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from zamlet import test_utils
from zamlet.kamlet_test.kte_driver import KteDriver
from zamlet.params import ZamletParams


def load_params(test_params: dict) -> ZamletParams:
    with open(test_params["params_file"]) as f:
        return ZamletParams.from_dict(json.load(f))


@cocotb.test()
async def smoke_build_and_reset(dut: HierarchyObject) -> None:
    """Minimal pipeline-cleaner test: build, reset, and run idle."""
    test_params = test_utils.get_test_params()
    rng = Random(test_params["seed"])
    driver = KteDriver(dut)
    driver.start(rng)
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    await driver.reset()
    await driver.idle(5)


@cocotb.test()
async def indexed_load_transfer_happy_path(dut: HierarchyObject) -> None:
    """Put one indexed load transfer into KTE and let all Jamlets complete it."""
    test_params = test_utils.get_test_params()
    params = load_params(test_params)
    rng = Random(test_params["seed"])
    driver = KteDriver(
        dut,
        j_in_k=params.j_in_k,
        te_depth=params.witem_table_depth,
    )
    driver.start(rng)
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    await driver.reset()
    driver.append_indexed_transfer(
        params,
        instr_ident=5,
        sync_ident=2,
        is_store=False,
        base_addr=0x1000,
        start_index=0,
        end_index=8,
        data_reg=3,
        index_reg=4,
    )

    await driver.wait_for_jte_clear(te_index=0, timeout_cycles=200)
