"""Test 0: KamletMesh instruction receive path + sync network aggregation.

Tests the sync network MIN aggregation across kamlets:
1. Send SyncTrigger with value 3 to kamlet 0
2. Send SyncTrigger with value 5 to kamlet 1
3. Both kamlets should output sync result = MIN(3, 5) = 3
"""

import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Tuple

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, ReadOnly

from zamlet import test_utils
from zamlet.control_structures import pack_fields_to_int


logger = logging.getLogger(__name__)


class MessageType(IntEnum):
    SEND = 0
    INSTRUCTIONS = 1


class SendType(IntEnum):
    SINGLE = 0
    BROADCAST = 1


class KInstrOpcode(IntEnum):
    SYNC_TRIGGER = 0


class Params:
    X_POS_WIDTH = 8
    Y_POS_WIDTH = 8
    K_COLS = 2
    K_ROWS = 1
    J_COLS = 1
    J_ROWS = 1
    N_CHANNELS = 2  # nAChannels + nBChannels


@dataclass
class PacketHeader:
    """Packet header matching Chisel PacketHeader Bundle."""
    target_x: int
    target_y: int
    source_x: int
    source_y: int
    length: int
    message_type: MessageType
    send_type: SendType

    @classmethod
    def get_field_specs(cls) -> List[Tuple[str, int]]:
        """Field specs in Chisel Bundle declaration order (first field = MSB)."""
        return [
            ('target_x', 8),
            ('target_y', 8),
            ('source_x', 8),
            ('source_y', 8),
            ('length', 4),
            ('message_type', 6),
            ('send_type', 1),
        ]

    def encode(self) -> int:
        """Encode to integer matching Chisel's asUInt bit layout."""
        return pack_fields_to_int(self, self.get_field_specs())


@dataclass
class SyncTriggerKInstr:
    """SyncTrigger instruction matching Chisel SyncTriggerInstr Bundle.

    64-bit kinstr format. Chisel Bundle ordering places last field at LSB,
    so the bit layout is:
      reserved: bits [41:0]  (42 bits, at LSB)
      value: bits [49:42]    (8 bits)
      sync_ident: bits [57:50] (8 bits)
      opcode: bits [63:58]   (6 bits, at MSB)
    """
    opcode: KInstrOpcode
    sync_ident: int
    value: int
    reserved: int = 0

    @classmethod
    def get_field_specs(cls) -> List[Tuple[str, int]]:
        """Field specs in Chisel Bundle declaration order (first field = MSB)."""
        return [
            ('opcode', 6),
            ('sync_ident', 8),
            ('value', 8),
            ('reserved', 42),
        ]

    def encode(self) -> int:
        """Encode to integer matching Chisel's asUInt bit layout."""
        return pack_fields_to_int(self, self.get_field_specs())


def initialize_inputs(dut: HierarchyObject) -> None:
    """Set all KamletMesh inputs to safe defaults.

    Note: Chisel flattens nested Vecs inner-to-outer, so Vec(kCols, Vec(jCols, Vec(ch, ...)))
    becomes io_name_{kX}_{j}_{ch} in the signal naming.
    """
    for kX in range(Params.K_COLS):
        for j in range(Params.J_COLS):
            for ch in range(Params.N_CHANNELS):
                getattr(dut, f'io_nChannelsIn_{kX}_{j}_{ch}_valid').value = 0
                getattr(dut, f'io_nChannelsIn_{kX}_{j}_{ch}_bits_data').value = 0
                getattr(dut, f'io_nChannelsIn_{kX}_{j}_{ch}_bits_isHeader').value = 0

    for kX in range(Params.K_COLS):
        for j in range(Params.J_COLS):
            for ch in range(Params.N_CHANNELS):
                getattr(dut, f'io_sChannelsIn_{kX}_{j}_{ch}_valid').value = 0
                getattr(dut, f'io_sChannelsIn_{kX}_{j}_{ch}_bits_data').value = 0
                getattr(dut, f'io_sChannelsIn_{kX}_{j}_{ch}_bits_isHeader').value = 0

    for kY in range(Params.K_ROWS):
        for j in range(Params.J_ROWS):
            for ch in range(Params.N_CHANNELS):
                getattr(dut, f'io_eChannelsIn_{kY}_{j}_{ch}_valid').value = 0
                getattr(dut, f'io_eChannelsIn_{kY}_{j}_{ch}_bits_data').value = 0
                getattr(dut, f'io_eChannelsIn_{kY}_{j}_{ch}_bits_isHeader').value = 0

    for kY in range(Params.K_ROWS):
        for j in range(Params.J_ROWS):
            for ch in range(Params.N_CHANNELS):
                getattr(dut, f'io_wChannelsIn_{kY}_{j}_{ch}_valid').value = 0
                getattr(dut, f'io_wChannelsIn_{kY}_{j}_{ch}_bits_data').value = 0
                getattr(dut, f'io_wChannelsIn_{kY}_{j}_{ch}_bits_isHeader').value = 0

    # Sync network inputs - north edge (N, NE, NW for all kCols)
    for kX in range(Params.K_COLS):
        getattr(dut, f'io_nSyncN_{kX}_in_valid').value = 0
        getattr(dut, f'io_nSyncN_{kX}_in_bits').value = 0
        getattr(dut, f'io_nSyncNE_{kX}_in_valid').value = 0
        getattr(dut, f'io_nSyncNE_{kX}_in_bits').value = 0
        getattr(dut, f'io_nSyncNW_{kX}_in_valid').value = 0
        getattr(dut, f'io_nSyncNW_{kX}_in_bits').value = 0

    # Sync network inputs - south edge (S, SE, SW for all kCols)
    for kX in range(Params.K_COLS):
        getattr(dut, f'io_sSyncS_{kX}_in_valid').value = 0
        getattr(dut, f'io_sSyncS_{kX}_in_bits').value = 0
        getattr(dut, f'io_sSyncSE_{kX}_in_valid').value = 0
        getattr(dut, f'io_sSyncSE_{kX}_in_bits').value = 0
        getattr(dut, f'io_sSyncSW_{kX}_in_valid').value = 0
        getattr(dut, f'io_sSyncSW_{kX}_in_bits').value = 0

    # Sync network inputs - east edge (E for all kRows)
    for kY in range(Params.K_ROWS):
        getattr(dut, f'io_eSyncE_{kY}_in_valid').value = 0
        getattr(dut, f'io_eSyncE_{kY}_in_bits').value = 0

    # Sync network inputs - east edge NE/SE (kRows-1 elements)
    for i in range(Params.K_ROWS - 1):
        getattr(dut, f'io_eSyncNE_{i}_in_valid').value = 0
        getattr(dut, f'io_eSyncNE_{i}_in_bits').value = 0
        getattr(dut, f'io_eSyncSE_{i}_in_valid').value = 0
        getattr(dut, f'io_eSyncSE_{i}_in_bits').value = 0

    # Sync network inputs - west edge (W for all kRows)
    for kY in range(Params.K_ROWS):
        getattr(dut, f'io_wSyncW_{kY}_in_valid').value = 0
        getattr(dut, f'io_wSyncW_{kY}_in_bits').value = 0

    # Sync network inputs - west edge NW/SW (kRows-1 elements)
    for i in range(Params.K_ROWS - 1):
        getattr(dut, f'io_wSyncNW_{i}_in_valid').value = 0
        getattr(dut, f'io_wSyncNW_{i}_in_bits').value = 0
        getattr(dut, f'io_wSyncSW_{i}_in_valid').value = 0
        getattr(dut, f'io_wSyncSW_{i}_in_bits').value = 0


async def reset(dut: HierarchyObject) -> None:
    """Reset the module."""
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)


async def send_packet_to_kamlet(dut: HierarchyObject, k_x: int, data: int,
                                is_header: bool) -> None:
    """Send a packet word to a kamlet via its north port."""
    valid_sig = getattr(dut, f'io_nChannelsIn_{k_x}_0_0_valid')
    data_sig = getattr(dut, f'io_nChannelsIn_{k_x}_0_0_bits_data')
    header_sig = getattr(dut, f'io_nChannelsIn_{k_x}_0_0_bits_isHeader')
    ready_sig = getattr(dut, f'io_nChannelsIn_{k_x}_0_0_ready')

    valid_sig.value = 1
    data_sig.value = data
    header_sig.value = 1 if is_header else 0

    for _ in range(100):
        await RisingEdge(dut.clock)
        await ReadOnly()
        if int(ready_sig.value) == 1:
            break
    else:
        raise TimeoutError(f"Timeout waiting for ready on kamlet {k_x}")

    await RisingEdge(dut.clock)
    valid_sig.value = 0


async def send_sync_trigger_to_kamlet(dut: HierarchyObject, k_x: int, sync_ident: int,
                                      value: int) -> None:
    """Send a SyncTrigger instruction packet to a kamlet."""
    j_x = k_x * Params.J_COLS
    header = PacketHeader(
        target_x=j_x,
        target_y=0,
        source_x=j_x,
        source_y=255,
        length=1,
        message_type=MessageType.INSTRUCTIONS,
        send_type=SendType.SINGLE
    )
    kinstr = SyncTriggerKInstr(
        opcode=KInstrOpcode.SYNC_TRIGGER,
        sync_ident=sync_ident,
        value=value
    )

    logger.info(f"Sending SyncTrigger to kamlet {k_x}: sync_ident={sync_ident}, value={value}")
    logger.info(f"  header={hex(header.encode())}, kinstr={hex(kinstr.encode())}")
    await send_packet_to_kamlet(dut, k_x, header.encode(), is_header=True)
    await send_packet_to_kamlet(dut, k_x, kinstr.encode(), is_header=False)


async def wait_for_sync_results(dut: HierarchyObject, timeout_cycles: int = 500):
    """Wait for sync results from both kamlets. Returns dict of results or None on timeout."""
    results = {}

    for _ in range(timeout_cycles):
        await RisingEdge(dut.clock)
        await ReadOnly()

        # Probe kamlet 0 (kamlets_0_0, kX=0, kY=0) sync result via internal synchronizer
        if 0 not in results:
            valid = int(dut.kamlets_0_0.synchronizer.io_result_valid.value)
            if valid == 1:
                ident = int(dut.kamlets_0_0.synchronizer.io_result_bits_syncIdent.value)
                value = int(dut.kamlets_0_0.synchronizer.io_result_bits_value.value)
                results[0] = (ident, value)
                logger.info(f"Kamlet 0 sync result: ident={ident}, value={value}")

        # Probe kamlet 1 (kamlets_1_0, kX=1, kY=0) sync result via internal synchronizer
        if 1 not in results:
            valid = int(dut.kamlets_1_0.synchronizer.io_result_valid.value)
            if valid == 1:
                ident = int(dut.kamlets_1_0.synchronizer.io_result_bits_syncIdent.value)
                value = int(dut.kamlets_1_0.synchronizer.io_result_bits_value.value)
                results[1] = (ident, value)
                logger.info(f"Kamlet 1 sync result: ident={ident}, value={value}")

        if len(results) == 2:
            return results

    return results if results else None


async def test_sync_aggregation(dut: HierarchyObject) -> None:
    """Test sync MIN aggregation across two kamlets."""
    # sync_ident must be in range [0, maxConcurrentSyncs) - default is 4
    sync_ident = 0

    await send_sync_trigger_to_kamlet(dut, k_x=0, sync_ident=sync_ident, value=3)
    await send_sync_trigger_to_kamlet(dut, k_x=1, sync_ident=sync_ident, value=5)

    logger.info("Sent SyncTrigger to both kamlets, waiting for sync results...")

    results = await wait_for_sync_results(dut, timeout_cycles=500)

    assert results is not None, "No sync results received within timeout"
    assert 0 in results, "Kamlet 0 did not produce sync result"
    assert 1 in results, "Kamlet 1 did not produce sync result"

    ident0, value0 = results[0]
    ident1, value1 = results[1]

    assert ident0 == sync_ident, f"Kamlet 0: expected ident {sync_ident}, got {ident0}"
    assert ident1 == sync_ident, f"Kamlet 1: expected ident {sync_ident}, got {ident1}"
    expected_min = 3
    assert value0 == expected_min, f"Kamlet 0: expected MIN value {expected_min}, got {value0}"
    assert value1 == expected_min, f"Kamlet 1: expected MIN value {expected_min}, got {value1}"

    logger.info(f"test_sync_aggregation passed: both kamlets returned value={expected_min}")


@cocotb.test()
async def kamlet_mesh_test(dut: HierarchyObject) -> None:
    """Main test entry point for KamletMesh Test 0."""
    test_utils.configure_logging_sim("DEBUG")

    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    initialize_inputs(dut)
    await reset(dut)

    await test_sync_aggregation(dut)
