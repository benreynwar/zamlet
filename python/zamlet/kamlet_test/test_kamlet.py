"""Test 0: KamletMesh instruction receive path + sync network aggregation.

Tests the sync network MIN aggregation across kamlets:
1. Send SyncTrigger with value 3 to kamlet 0
2. Send SyncTrigger with value 5 to kamlet 1
3. Both kamlets should output sync result = MIN(3, 5) = 3
"""

import json
import logging
from typing import List

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, ReadOnly

from zamlet import test_utils
from zamlet.params import ZamletParams
from zamlet.message import Header, MessageType, SendType
from zamlet.kamlet.kinstructions import SyncTrigger
from zamlet.transactions.ident_query import IdentQuery


logger = logging.getLogger(__name__)


def initialize_inputs(dut: HierarchyObject, params: ZamletParams) -> None:
    """Set all KamletMesh inputs to safe defaults."""
    n_channels = params.n_a_channels + params.n_b_channels

    # Network channel inputs: (prefix, outer_dim, inner_dim)
    edge_specs = [
        ('n', params.k_cols, params.j_cols),
        ('s', params.k_cols, params.j_cols),
        ('e', params.k_rows, params.j_rows),
        ('w', params.k_rows, params.j_rows),
    ]
    for prefix, outer, inner in edge_specs:
        for i in range(outer):
            for j in range(inner):
                for ch in range(n_channels):
                    getattr(dut, f'io_{prefix}ChannelsIn_{i}_{j}_{ch}_valid').value = 0
                    getattr(dut, f'io_{prefix}ChannelsIn_{i}_{j}_{ch}_bits_data').value = 0
                    sig = f'io_{prefix}ChannelsIn_{i}_{j}_{ch}_bits_isHeader'
                    getattr(dut, sig).value = 0

    # Sync network inputs
    sync_specs = [
        ('nSyncN', params.k_cols), ('nSyncNE', params.k_cols),
        ('nSyncNW', params.k_cols),
        ('sSyncS', params.k_cols), ('sSyncSE', params.k_cols),
        ('sSyncSW', params.k_cols),
        ('eSyncE', params.k_rows),
        ('eSyncNE', params.k_rows - 1), ('eSyncSE', params.k_rows - 1),
        ('wSyncW', params.k_rows),
        ('wSyncNW', params.k_rows - 1), ('wSyncSW', params.k_rows - 1),
    ]
    for name, count in sync_specs:
        for i in range(count):
            getattr(dut, f'io_{name}_{i}_in_valid').value = 0
            getattr(dut, f'io_{name}_{i}_in_bits').value = 0


async def monitor_errors(dut: HierarchyObject, params: ZamletParams) -> None:
    """Monitor error wires on all kamlets every cycle. Asserts on any error."""
    error_signals = []
    for kx in range(params.k_cols):
        for ky in range(params.k_rows):
            kamlet = getattr(dut, f'kamlets_{kx}_{ky}')
            error_signals.extend([
                (f'kamlet({kx},{ky}) instrQueue unexpectedHeader',
                 kamlet.io_errors_instrQueue_unexpectedHeader),
                (f'kamlet({kx},{ky}) instrQueue unexpectedData',
                 kamlet.io_errors_instrQueue_unexpectedData),
            ])

    while True:
        await RisingEdge(dut.clock)
        await ReadOnly()
        for name, sig in error_signals:
            if int(sig.value) != 0:
                # Let sim run a few more cycles for waveform context
                for _ in range(3):
                    await RisingEdge(dut.clock)
                assert False, f"Error: {name} went high"


async def reset(dut: HierarchyObject) -> None:
    """Reset the module."""
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)


async def send_word_to_kamlet(dut: HierarchyObject, kx: int, word: int, is_header: bool) -> None:
    valid_sig = getattr(dut, f'io_nChannelsIn_{kx}_0_0_valid')
    data_sig = getattr(dut, f'io_nChannelsIn_{kx}_0_0_bits_data')
    header_sig = getattr(dut, f'io_nChannelsIn_{kx}_0_0_bits_isHeader')
    ready_sig = getattr(dut, f'io_nChannelsIn_{kx}_0_0_ready')
    valid_sig.value = 1
    data_sig.value = word
    header_sig.value = 1 if is_header else 0
    await ReadOnly()
    while int(ready_sig.value) != 1:
        await RisingEdge(dut.clock)
        await ReadOnly()
    await RisingEdge(dut.clock)
    valid_sig.value = 0


async def send_packet_to_kamlet(params: ZamletParams, dut: HierarchyObject, kx: int, packet) -> None:
    """Send a full packet (header + payload words) to a kamlet via its north port."""

    header = packet[0]
    assert isinstance(header, Header)
    header_as_int = header.encode(params)
    assert header.length+1 == len(packet)

    await send_word_to_kamlet(dut, kx, header_as_int, True)
    for word in packet[1:]:
        await send_word_to_kamlet(dut, kx, word, False)


async def send_sync_trigger_to_kamlet(dut: HierarchyObject, params: ZamletParams,
                                      kx: int, sync_ident: int, value: int) -> None:
    """Send a SyncTrigger instruction packet to a kamlet."""
    j_x = kx * params.j_cols
    header = Header(
        target_x=j_x,
        target_y=0,
        source_x=j_x,
        source_y=255,
        length=1,
        message_type=MessageType.INSTRUCTIONS,
        send_type=SendType.SINGLE
    )
    kinstr = SyncTrigger(sync_ident=sync_ident, value=value)

    logger.info(
        f"Sending SyncTrigger to kamlet {kx}: sync_ident={sync_ident}, value={value}"
    )
    logger.info(f"  header={hex(header.encode(params))}, kinstr={hex(kinstr.encode())}")
    await send_packet_to_kamlet(params, dut, kx, [header, kinstr.encode()])


async def wait_for_sync_results(dut: HierarchyObject, params: ZamletParams,
                                timeout_cycles: int = 500):
    """Wait for sync results from both kamlets. Returns dict of results or None."""
    results = {}

    for _ in range(timeout_cycles):
        await RisingEdge(dut.clock)
        await ReadOnly()

        for kx in range(params.k_cols):
            for ky in range(params.k_rows):
                k_idx = kx * params.k_rows + ky
                if k_idx in results:
                    continue
                kamlet = getattr(dut, f'kamlets_{kx}_{ky}')
                valid = int(kamlet.synchronizer.io_result_valid.value)
                if valid == 1:
                    ident = int(
                        kamlet.synchronizer.io_result_bits_syncIdent.value
                    )
                    value = int(kamlet.synchronizer.io_result_bits_value.value)
                    results[k_idx] = (ident, value)
                    logger.info(
                        f"Kamlet ({kx},{ky}) sync result: "
                        f"ident={ident}, value={value}"
                    )

        if len(results) == params.k_cols * params.k_rows:
            return results

    return results if results else None


async def test_sync_aggregation(dut: HierarchyObject,
                                params: ZamletParams) -> None:
    """Test sync MIN aggregation across two kamlets."""
    sync_ident = 0

    await send_sync_trigger_to_kamlet(dut, params, kx=0,
                                      sync_ident=sync_ident, value=3)
    await send_sync_trigger_to_kamlet(dut, params, kx=1,
                                      sync_ident=sync_ident, value=5)

    logger.info("Sent SyncTrigger to both kamlets, waiting for sync results...")

    results = await wait_for_sync_results(dut, params, timeout_cycles=500)

    assert results is not None, "No sync results received within timeout"
    n_kamlets = params.k_cols * params.k_rows
    assert len(results) == n_kamlets, (
        f"Expected results from {n_kamlets} kamlets, got {len(results)}"
    )

    expected_min = 3
    for k_idx, (ident, value) in results.items():
        assert ident == sync_ident, (
            f"Kamlet {k_idx}: expected ident {sync_ident}, got {ident}"
        )
        assert value == expected_min, (
            f"Kamlet {k_idx}: expected MIN value {expected_min}, got {value}"
        )

    logger.info(
        f"test_sync_aggregation passed: all kamlets returned value={expected_min}"
    )


async def send_ident_query_to_kamlet(dut: HierarchyObject, params: ZamletParams,
                                     kx: int, sync_ident: int,
                                     baseline: int) -> None:
    """Send an IdentQuery instruction packet to a kamlet."""
    j_x = kx * params.j_cols
    header = Header(
        target_x=j_x,
        target_y=0,
        source_x=j_x,
        source_y=255,
        length=1,
        message_type=MessageType.INSTRUCTIONS,
        send_type=SendType.SINGLE
    )
    kinstr = IdentQuery(instr_ident=sync_ident, baseline=baseline)

    logger.info(
        f"Sending IdentQuery to kamlet {kx}: "
        f"sync_ident={sync_ident}, baseline={baseline}"
    )
    logger.info(f"  header={hex(header.encode(params))}, kinstr={hex(kinstr.encode())}")
    await send_packet_to_kamlet(params, dut, kx, [header, kinstr.encode()])


async def test_ident_query(dut: HierarchyObject, params: ZamletParams) -> None:
    """Test IdentQuery instruction decoding and sync network.

    Sends IdentQuery to both kamlets. Since no instructions are active,
    both should report max distance (128 = all idents free).
    """
    sync_ident = 1
    baseline = 50

    await send_ident_query_to_kamlet(dut, params, kx=0,
                                     sync_ident=sync_ident, baseline=baseline)
    await send_ident_query_to_kamlet(dut, params, kx=1,
                                     sync_ident=sync_ident, baseline=baseline)

    logger.info("Sent IdentQuery to both kamlets, waiting for sync results...")

    results = await wait_for_sync_results(dut, params, timeout_cycles=500)

    assert results is not None, "No sync results received within timeout"
    n_kamlets = params.k_cols * params.k_rows
    assert len(results) == n_kamlets, (
        f"Expected results from {n_kamlets} kamlets, got {len(results)}"
    )

    expected_value = 128  # params.maxResponseTags
    for k_idx, (ident, value) in results.items():
        assert ident == sync_ident, (
            f"Kamlet {k_idx}: expected ident {sync_ident}, got {ident}"
        )
        assert value == expected_value, (
            f"Kamlet {k_idx}: expected value {expected_value}, got {value}"
        )

    logger.info(
        f"test_ident_query passed: all kamlets returned value={expected_value}"
    )


@cocotb.test()
async def kamlet_mesh_test(dut: HierarchyObject) -> None:
    """Main test entry point for KamletMesh Test 0."""
    test_utils.configure_logging_sim("DEBUG")
    test_params = test_utils.get_test_params()
    with open(test_params['params_file']) as f:
        params = ZamletParams.from_dict(json.load(f))

    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    initialize_inputs(dut, params)
    await reset(dut)
    cocotb.start_soon(monitor_errors(dut, params))

    await test_sync_aggregation(dut, params)
    await RisingEdge(dut.clock)  # Exit ReadOnly phase before next test
    await test_ident_query(dut, params)
