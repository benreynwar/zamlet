import os
import sys
import logging

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, ReadOnly

from zamlet import test_utils


logger = logging.getLogger(__name__)


# Direction indices matching SyncDirection in Synchronizer.scala
class Dir:
    N = 0
    S = 1
    E = 2
    W = 3
    NE = 4
    NW = 5
    SE = 6
    SW = 7
    COUNT = 8

    NAMES = ['N', 'S', 'E', 'W', 'NE', 'NW', 'SE', 'SW']


def initialize_inputs(dut: HierarchyObject) -> None:
    """Set all inputs to safe default values."""
    dut.io_localEvent_valid.value = 0
    dut.io_localEvent_bits_syncIdent.value = 0
    dut.io_localEvent_bits_value.value = 0

    for i in range(Dir.COUNT):
        getattr(dut, f'io_portIn_{i}_valid').value = 0
        getattr(dut, f'io_portIn_{i}_bits').value = 0


async def reset(dut: HierarchyObject) -> None:
    """Reset the module."""
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)


async def send_local_event(dut: HierarchyObject, sync_ident: int, value: int) -> None:
    """Send a local sync event."""
    dut.io_localEvent_valid.value = 1
    dut.io_localEvent_bits_syncIdent.value = sync_ident
    dut.io_localEvent_bits_value.value = value
    await RisingEdge(dut.clock)
    dut.io_localEvent_valid.value = 0


async def send_sync_packet(dut: HierarchyObject, direction: int, sync_ident: int, value: int):
    """Send a 2-byte sync packet from a neighbor direction.

    Byte 0: sync_ident (last_byte=0)
    Byte 1: value (last_byte=1)
    """
    port_valid = getattr(dut, f'io_portIn_{direction}_valid')
    port_bits = getattr(dut, f'io_portIn_{direction}_bits')

    # Byte 0: sync_ident, last_byte=0
    port_valid.value = 1
    port_bits.value = (0 << 8) | (sync_ident & 0xFF)
    await RisingEdge(dut.clock)

    # Byte 1: value, last_byte=1
    port_bits.value = (1 << 8) | (value & 0xFF)
    await RisingEdge(dut.clock)

    port_valid.value = 0


async def wait_for_result(dut: HierarchyObject, timeout_cycles: int = 100):
    """Wait for a sync result to be valid. Returns (sync_ident, value) or None on timeout."""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clock)
        await ReadOnly()
        if int(dut.io_result_valid.value) == 1:
            sync_ident = int(dut.io_result_bits_syncIdent.value)
            value = int(dut.io_result_bits_value.value)
            return (sync_ident, value)
    return None


async def wait_for_port_out(dut: HierarchyObject, direction: int, timeout_cycles: int = 100):
    """Wait for output on a port. Returns list of (last_byte, data) tuples or None on timeout."""
    packets = []
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clock)
        await ReadOnly()
        port_valid = getattr(dut, f'io_portOut_{direction}_valid')
        port_bits = getattr(dut, f'io_portOut_{direction}_bits')
        if int(port_valid.value) == 1:
            bits = int(port_bits.value)
            last_byte = (bits >> 8) & 1
            data = bits & 0xFF
            packets.append((last_byte, data))
            if last_byte == 1:
                return packets
    return None if not packets else packets


async def collect_all_port_outputs(dut: HierarchyObject, cycles: int = 50):
    """Collect output packets from all ports over a number of cycles.

    Returns dict: direction -> list of (sync_ident, value) tuples
    """
    outputs = {d: [] for d in range(Dir.COUNT)}
    pending = {d: None for d in range(Dir.COUNT)}  # pending byte0 per direction

    for _ in range(cycles):
        await RisingEdge(dut.clock)
        await ReadOnly()

        for d in range(Dir.COUNT):
            port_valid = getattr(dut, f'io_portOut_{d}_valid')
            port_bits = getattr(dut, f'io_portOut_{d}_bits')

            if int(port_valid.value) == 1:
                bits = int(port_bits.value)
                last_byte = (bits >> 8) & 1
                data = bits & 0xFF

                if last_byte == 0:
                    pending[d] = data  # byte0 = sync_ident
                else:
                    if pending[d] is not None:
                        outputs[d].append((pending[d], data))  # (sync_ident, value)
                        pending[d] = None

    return outputs


async def basic_sync_test(dut: HierarchyObject) -> None:
    """Test a basic sync operation with all 8 neighbors.

    This tests a node in the center of a grid that has all 8 neighbors.
    The sync completes when:
    1. Local event is received
    2. All 8 neighbors send their sync packets
    3. All 8 outgoing packets are sent
    """
    sync_ident = 42
    local_value = 100

    # Send local event
    await send_local_event(dut, sync_ident, local_value)
    logger.info(f"Sent local event: sync_ident={sync_ident}, value={local_value}")

    # The node needs to receive from all 8 neighbors before it can complete.
    # It also needs to send to all 8 neighbors, but sending has dependencies:
    # - Can send N when S is synced
    # - Can send S when N is synced
    # - Can send E when W is synced
    # - Can send W when E is synced
    # - Can send NE when SW, S, W are synced
    # etc.

    # First, let's just send from all neighbors with their values.
    # Each neighbor sends (sync_ident, their_value).
    neighbor_values = {
        Dir.N: 90,
        Dir.S: 110,
        Dir.E: 85,
        Dir.W: 95,
        Dir.NE: 80,
        Dir.NW: 120,
        Dir.SE: 75,  # This should be the minimum
        Dir.SW: 105,
    }

    # Send from all neighbors
    for direction, value in neighbor_values.items():
        await send_sync_packet(dut, direction, sync_ident, value)
        logger.info(f"Sent sync packet from {Dir.NAMES[direction]}: value={value}")

    # Wait for result - the minimum across all values should be 75 (from SE)
    # But wait, the minimum should also include local_value (100).
    # So minimum of [100, 90, 110, 85, 95, 80, 120, 75, 105] = 75
    result = await wait_for_result(dut, timeout_cycles=200)

    assert result is not None, "Sync did not complete within timeout"
    result_ident, result_value = result
    assert result_ident == sync_ident, f"Expected sync_ident {sync_ident}, got {result_ident}"

    expected_min = min([local_value] + list(neighbor_values.values()))
    assert result_value == expected_min, \
        f"Expected MIN value {expected_min}, got {result_value}"

    logger.info(f"basic_sync_test passed: result_value={result_value}")


class OutputCollector:
    """Collects output packets from all ports continuously."""

    def __init__(self, dut):
        self.dut = dut
        self.outputs = {d: [] for d in range(Dir.COUNT)}
        self._pending = {d: None for d in range(Dir.COUNT)}
        self._running = False

    async def run(self):
        self._running = True
        while self._running:
            await RisingEdge(self.dut.clock)
            await ReadOnly()
            for d in range(Dir.COUNT):
                port_valid = getattr(self.dut, f'io_portOut_{d}_valid')
                port_bits = getattr(self.dut, f'io_portOut_{d}_bits')

                if int(port_valid.value) == 1:
                    bits = int(port_bits.value)
                    last_byte = (bits >> 8) & 1
                    data = bits & 0xFF

                    if last_byte == 0:
                        self._pending[d] = data
                    else:
                        if self._pending[d] is not None:
                            self.outputs[d].append((self._pending[d], data))
                            self._pending[d] = None

    def stop(self):
        self._running = False


async def outgoing_packets_test(dut: HierarchyObject) -> None:
    """Test that outgoing packets are sent correctly.

    Send local event and verify that packets are sent to all directions
    once the send conditions are met.
    """
    sync_ident = 7
    local_value = 50

    # Start collector coroutine
    collector = OutputCollector(dut)
    cocotb.start_soon(collector.run())

    # Send local event
    await send_local_event(dut, sync_ident, local_value)
    logger.info(f"Sent local event: sync_ident={sync_ident}, value={local_value}")

    # Send from all neighbors to enable all send conditions
    for d in range(Dir.COUNT):
        await send_sync_packet(dut, d, sync_ident, 100 + d)

    # Wait for outputs to be sent
    for _ in range(50):
        await RisingEdge(dut.clock)

    collector.stop()

    # All directions should have sent a packet
    for d in range(Dir.COUNT):
        assert len(collector.outputs[d]) >= 1, \
            f"Expected output on direction {Dir.NAMES[d]}, got none"
        out_ident, out_value = collector.outputs[d][0]
        assert out_ident == sync_ident, \
            f"Direction {Dir.NAMES[d]}: expected sync_ident {sync_ident}, got {out_ident}"
        logger.info(f"Direction {Dir.NAMES[d]}: sent sync_ident={out_ident}, value={out_value}")

    logger.info("outgoing_packets_test passed")


async def multiple_syncs_test(dut: HierarchyObject) -> None:
    """Test multiple concurrent sync operations."""
    # Start two sync operations
    await send_local_event(dut, sync_ident=1, value=50)
    await send_local_event(dut, sync_ident=2, value=60)

    # Send neighbor packets for sync 1
    for d in range(Dir.COUNT):
        await send_sync_packet(dut, d, sync_ident=1, value=40 + d)

    # Wait for first result
    result1 = await wait_for_result(dut, timeout_cycles=200)
    assert result1 is not None, "First sync did not complete"
    assert result1[0] == 1, f"Expected sync_ident 1, got {result1[0]}"
    logger.info(f"Sync 1 completed: value={result1[1]}")

    # Exit ReadOnly phase before sending more packets
    await RisingEdge(dut.clock)

    # Now send neighbor packets for sync 2
    for d in range(Dir.COUNT):
        await send_sync_packet(dut, d, sync_ident=2, value=70 + d)

    # Wait for second result
    result2 = await wait_for_result(dut, timeout_cycles=200)
    assert result2 is not None, "Second sync did not complete"
    assert result2[0] == 2, f"Expected sync_ident 2, got {result2[0]}"
    logger.info(f"Sync 2 completed: value={result2[1]}")

    logger.info("multiple_syncs_test passed")


@cocotb.test()
async def synchronizer_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")

    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    # Initialize and reset
    initialize_inputs(dut)
    await reset(dut)

    # Run tests
    await basic_sync_test(dut)

    # Reset for next test
    await RisingEdge(dut.clock)
    initialize_inputs(dut)
    await reset(dut)

    await outgoing_packets_test(dut)

    # Reset for next test
    await RisingEdge(dut.clock)
    initialize_inputs(dut)
    await reset(dut)

    await multiple_syncs_test(dut)


def test_synchronizer(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]

    toplevel = "Synchronizer"
    module = "zamlet.kamlet_test.test_synchronizer"

    test_params = {
        "seed": seed,
    }

    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")

    if len(sys.argv) >= 2:
        verilog_file = os.path.abspath(sys.argv[1])
        test_synchronizer(verilog_file)
    else:
        print("Usage: python test_synchronizer.py <verilog_file>")
        sys.exit(1)
