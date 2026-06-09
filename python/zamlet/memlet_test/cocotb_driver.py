"""Cocotb driver for memlet tests.

Wraps signal-level cocotb driving of the Memlet RTL module.
Packets are injected on the B channel and responses are captured
on the A channel. The direction (N/S/E/W) is configurable based
on where the kamlet sits relative to the memlet router.

Ready and valid signals are randomized to exercise backpressure.
"""

import logging
from random import Random

import cocotb
from cocotb.handle import HierarchyObject
from cocotb.triggers import Event, ReadOnly, RisingEdge

from zamlet.future import Future
from zamlet.memlet_test.memlet_driver import MemletDriver
from zamlet.message import Header, MessageType
from zamlet.params import ZamletParams
from zamlet.test_helpers.packets import NetworkPacketSink, NetworkPacketSource
from zamlet.router import xy_direction

logger = logging.getLogger(__name__)


class CocotbDriver(MemletDriver):
    """Drive memlet RTL via cocotb signals.

    Packet direction is derived from source/target coordinates, matching
    the model driver's approach.
    """

    def __init__(self, dut: HierarchyObject, params: ZamletParams,
                 router_coords: list, k_base_x: int, k_base_y: int,
                 p_valid: float = 1.0, p_ready: float = 1.0,
                 seed: int = 0):
        super().__init__(params, router_coords, k_base_x, k_base_y)
        self.dut = dut
        self.p_valid = p_valid
        self.p_ready = p_ready
        self.rng = Random(seed)
        self.b_sources = {
            (r, d): NetworkPacketSource(dut, dut.clock, f'io_b{d}i_{r}_0')
            for r in range(self.n_routers)
            for d in 'NSEW'
        }
        self.a_sinks = {
            (r, d): NetworkPacketSink(
                dut, dut.clock, f'io_a{d}o_{r}_0', params,
                max_packet_queue_depth=self.a_queue_depth)
            for r in range(self.n_routers)
            for d in 'NSEW'
        }
        self.control_source = NetworkPacketSource(
            dut, dut.clock, 'io_controlBHo')
        self.control_sink = NetworkPacketSink(
            dut, dut.clock, 'io_controlAHi', params,
            max_packet_queue_depth=self.a_queue_depth)

    async def reset(self) -> None:
        self.dut.io_controlBHo_valid.value = 0
        self.dut.io_controlBHo_bits_data.value = 0
        self.dut.io_controlBHo_bits_isHeader.value = 0
        self.dut.io_controlAHi_ready.value = 0
        for r in range(self.n_routers):
            for d in 'NSEW':
                getattr(self.dut, f'io_b{d}i_{r}_0_valid').value = 0
                getattr(self.dut, f'io_b{d}i_{r}_0_bits_data').value = 0
                getattr(self.dut, f'io_b{d}i_{r}_0_bits_isHeader').value = 0
                getattr(self.dut, f'io_a{d}o_{r}_0_ready').value = 0

        self.dut.reset.value = 1
        await RisingEdge(self.dut.clock)
        await RisingEdge(self.dut.clock)
        self.dut.reset.value = 0
        # Wait for reset synchronizer (2 cycles) + RegNext on position (1 cycle)
        for _ in range(4):
            await RisingEdge(self.dut.clock)

    def start(self) -> None:
        super().start()
        self.control_source.start(
            rng=self.rng, p_valid=self.p_valid)
        self.control_sink.start(
            rng=self.rng, p_ready=self.p_ready)
        cocotb.start_soon(self._drain_sink(0, self.control_sink))
        for r in range(self.n_routers):
            cocotb.start_soon(self._send_loop(r))
            for d in 'NSEW':
                self.b_sources[(r, d)].start(
                    rng=self.rng, p_valid=self.p_valid)
                sink = self.a_sinks[(r, d)]
                sink.start(rng=self.rng, p_ready=self.p_ready)
                cocotb.start_soon(self._drain_sink(r, sink))
        cocotb.start_soon(self._error_monitor())

    async def _send_loop(self, r: int) -> None:
        """Background: route queued packets to the right packet source."""
        rx, ry = self.router_coords[r]
        while True:
            if self.b_queues[r]:
                packet = self.b_queues[r].popleft()
                header = packet[0]
                assert isinstance(header, Header)
                if self._is_control_packet(header):
                    self._enqueue_packet(self.control_source, packet)
                else:
                    d = xy_direction(rx, ry, header.source_x, header.source_y).name
                    self._enqueue_packet(self.b_sources[(r, d)], packet)
            else:
                await RisingEdge(self.dut.clock)

    def _is_control_packet(self, header: Header) -> bool:
        return header.message_type in (
            MessageType.WRITE_LINE_ADDR,
            MessageType.READ_LINE_ADDR,
            MessageType.WRITE_LINE_READ_LINE_ADDR,
        )

    def _enqueue_packet(self, source: NetworkPacketSource, packet: list) -> None:
        header = packet[0]
        assert isinstance(header, Header)
        words = [(header.encode(self.params), True)]
        for word in packet[1:]:
            assert isinstance(word, int)
            words.append((word, False))
        source.enqueue_packet(words)

    async def _drain_sink(self, r: int, sink: NetworkPacketSink) -> None:
        """Background: move completed helper packets into MemletDriver queues."""
        while True:
            while sink.packet_queue:
                await self.a_queue_append(r, sink.packet_queue.popleft())
            await RisingEdge(self.dut.clock)

    async def _error_monitor(self) -> None:
        """Background: assert all error signals stay zero every cycle."""
        control_fields = [
            'allocOverwrite', 'duplicateComplete', 'missingHeader',
            'unexpectedHeader', 'badMessageType', 'badPacketLength',
        ]
        gather_fields = [
            'cacheSlotAllocOverwrite', 'missingHeader', 'unexpectedHeader',
            'duplicateArrived', 'badMessageType', 'badPacketLength',
            'unexpectedData',
        ]
        response_fields = [
            'responseAllocOverwrite', 'sentInInvalid', 'sentInDuplicate',
        ]
        # Resolve signal handles once up front.
        signals = []
        for field in control_fields:
            sig = getattr(self.dut, f'io_errors_controlErrors_{field}')
            signals.append((f'controlErrors.{field}', sig))
        for r in range(self.n_routers):
            for field in gather_fields:
                sig = getattr(self.dut, f'io_errors_gatherErrors_{r}_{field}')
                signals.append((f'gatherErrors[{r}].{field}', sig))
            for field in response_fields:
                sig = getattr(self.dut, f'io_errors_responseErrors_{r}_{field}')
                signals.append((f'responseErrors[{r}].{field}', sig))

        while True:
            await ReadOnly()
            fired = None
            for name, sig in signals:
                if int(sig.value):
                    fired = name
                    break
            if fired:
                # Let a few more cycles into the waveform for debugging context.
                for _ in range(3):
                    await RisingEdge(self.dut.clock)
                assert False, f"Error signal asserted: {fired}"
            await RisingEdge(self.dut.clock)

    def _make_future(self):
        return Future(Event())

    async def tick(self, n: int = 1) -> None:
        for _ in range(n):
            await RisingEdge(self.dut.clock)

    def start_soon(self, coro):
        return cocotb.start_soon(coro)
