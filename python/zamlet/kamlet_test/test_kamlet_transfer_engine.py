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

    await driver.wait_for_sync_local_event(sync_ident=2, timeout_cycles=200)
    await driver.wait_for_jte_clear(te_index=0, timeout_cycles=200)


@cocotb.test()
async def indexed_store_transfer_happy_path(dut: HierarchyObject) -> None:
    """Put one indexed store transfer into KTE and let all Jamlets complete it."""
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
        instr_ident=6,
        sync_ident=3,
        is_store=True,
        base_addr=0x2000,
        start_index=4,
        end_index=12,
        data_reg=5,
        index_reg=6,
    )

    await driver.wait_for_sync_local_event(sync_ident=3, timeout_cycles=200)
    await driver.wait_for_jte_clear(te_index=0, timeout_cycles=200)


@cocotb.test()
async def multiple_indexed_transfers_clear(dut: HierarchyObject) -> None:
    """Queue several indexed transfers and wait for every allocated TE entry to clear."""
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
    transfers = [
        {"instr_ident": 10, "sync_ident": 1, "is_store": False},
        {"instr_ident": 11, "sync_ident": 2, "is_store": True},
        {"instr_ident": 12, "sync_ident": 3, "is_store": False},
    ]
    for index, transfer in enumerate(transfers):
        driver.append_indexed_transfer(
            params,
            instr_ident=transfer["instr_ident"],
            sync_ident=transfer["sync_ident"],
            is_store=transfer["is_store"],
            base_addr=0x3000 + index * 0x100,
            start_index=index * 4,
            end_index=index * 4 + 8,
            data_reg=3 + index,
            index_reg=8 + index,
        )

    for te_index in range(len(transfers)):
        await driver.wait_for_jte_clear(te_index=te_index, timeout_cycles=300)


@cocotb.test()
async def indexed_transfers_reuse_full_table(dut: HierarchyObject) -> None:
    """Queue more transfers than fit in the KTE table and require entry reuse."""
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
    n_transfers = params.witem_table_depth + 3
    for index in range(n_transfers):
        driver.append_indexed_transfer(
            params,
            instr_ident=20 + index,
            sync_ident=index % params.max_concurrent_syncs,
            is_store=bool(index % 2),
            base_addr=0x4000 + index * 0x40,
            start_index=index,
            end_index=index + 8,
            data_reg=4 + (index % 8),
            index_reg=16 + (index % 8),
        )

    await driver.wait_for_total_jte_clears(
        expected_clears=n_transfers,
        timeout_cycles=1200,
    )


@cocotb.test()
async def transfer_waits_for_sync_result(dut: HierarchyObject) -> None:
    """Delay sync results and check the transfer does not clear until sync completes."""
    test_params = test_utils.get_test_params()
    params = load_params(test_params)
    rng = Random(test_params["seed"])
    driver = KteDriver(
        dut,
        j_in_k=params.j_in_k,
        te_depth=params.witem_table_depth,
        sync_result_probability=0.0,
    )
    driver.start(rng)
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    await driver.reset()
    driver.append_indexed_transfer(
        params,
        instr_ident=50,
        sync_ident=4,
        is_store=False,
        base_addr=0x5000,
        start_index=0,
        end_index=8,
        data_reg=7,
        index_reg=8,
    )

    await driver.wait_for_sync_local_event(sync_ident=4, timeout_cycles=200)
    await driver.idle(20)
    for jamlet in driver.jamlets:
        assert 0 not in jamlet.state.cleared_entries

    driver.sync_result_probability = 1.0
    await driver.wait_for_jte_clear(te_index=0, timeout_cycles=100)


@cocotb.test()
async def cache_wait_replays_after_slot_available(dut: HierarchyObject) -> None:
    """Cache-wait local ops must not replay until the allocated slot is available."""
    test_params = test_utils.get_test_params()
    params = load_params(test_params)
    rng = Random(test_params["seed"])
    driver = KteDriver(
        dut,
        j_in_k=params.j_in_k,
        te_depth=params.witem_table_depth,
        n_cache_slots=params.n_cache_slots,
        slot_status_available_probability=0.0,
        requested_slot_available_probability=0.0,
        unrequested_slot_available_probability=0.0,
    )
    driver.start(rng)
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    await driver.reset()
    kinstr = 0x12345
    cache_slot = 3
    submitted = driver.append_cache_wait_local(
        kinstr=kinstr,
        cache_slot=cache_slot,
        will_write=True,
    )
    await submitted
    await driver.idle(20)
    assert not driver.local_replays
    assert not driver.cache_slot_releases

    driver.pulse_slot_available(cache_slot)
    replay = await driver.wait_for_local_replay(timeout_cycles=100)
    assert replay["kinstr"] == kinstr
    assert replay["cacheSlot"] == cache_slot
    await driver.wait_for_cache_slot_release(
        slot=cache_slot,
        timeout_cycles=100,
    )


@cocotb.test()
async def cache_wait_replays_immediately_when_slot_present(dut: HierarchyObject) -> None:
    """Cache-wait local ops replay when the allocated slot is reported present."""
    test_params = test_utils.get_test_params()
    params = load_params(test_params)
    rng = Random(test_params["seed"])
    driver = KteDriver(
        dut,
        j_in_k=params.j_in_k,
        te_depth=params.witem_table_depth,
        n_cache_slots=params.n_cache_slots,
        slot_status_available_probability=1.0,
        requested_slot_available_probability=0.0,
        unrequested_slot_available_probability=0.0,
    )
    driver.start(rng)
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    await driver.reset()
    kinstr = 0x6789a
    cache_slot = 5
    submitted = driver.append_cache_wait_local(
        kinstr=kinstr,
        cache_slot=cache_slot,
        will_write=False,
    )
    await submitted
    replay = await driver.wait_for_local_replay(timeout_cycles=100)
    assert replay["kinstr"] == kinstr
    assert replay["cacheSlot"] == cache_slot
    await driver.wait_for_cache_slot_release(
        slot=cache_slot,
        timeout_cycles=100,
    )
