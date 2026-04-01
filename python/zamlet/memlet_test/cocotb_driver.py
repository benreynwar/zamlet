"""Cocotb driver for memlet tests.

Wraps signal-level cocotb driving of the Memlet RTL module.
Packets are injected on the B channel and responses are captured
on the A channel. The direction (N/S/E/W) is configurable based
on where the kamlet sits relative to the memlet router.

Ready and valid signals are randomized to exercise backpressure.
"""

import logging
from random import Random
from typing import List

import cocotb
from cocotb.handle import HierarchyObject
from cocotb.triggers import Event, RisingEdge, ReadOnly

from zamlet import utils
from zamlet.future import Future
from zamlet.memlet_test.memlet_driver import MemletDriver
from zamlet.message import Direction, Header, int_to_header
from zamlet.params import ZamletParams
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

    def _b_sig(self, r: int, d: str, suffix: str):
        return getattr(self.dut, f'io_b{d}i_{r}_0_{suffix}')

    def _a_sig(self, r: int, d: str, suffix: str):
        return getattr(self.dut, f'io_a{d}o_{r}_0_{suffix}')

    async def reset(self) -> None:
        for r in range(self.n_routers):
            for d in 'NSEW':
                self._b_sig(r, d, 'valid').value = 0
                self._a_sig(r, d, 'ready').value = 0

        self.dut.reset.value = 1
        await RisingEdge(self.dut.clock)
        await RisingEdge(self.dut.clock)
        self.dut.reset.value = 0
        # Wait for reset synchronizer (2 cycles) + RegNext on position (1 cycle)
        for _ in range(4):
            await RisingEdge(self.dut.clock)

    def start(self) -> None:
        super().start()
        for r in range(self.n_routers):
            send_rng = utils.create_rng(self.rng)
            cocotb.start_soon(self._send_loop(r, send_rng))
            for d in 'NSEW':
                recv_rng = utils.create_rng(self.rng)
                cocotb.start_soon(self._recv_loop(r, d, recv_rng))
        cocotb.start_soon(self._error_monitor())

    async def _send_loop(self, r: int, rng: Random) -> None:
        """Background: drain b_queues[r] with randomized valid."""
        rx, ry = self.router_coords[r]
        while True:
            if self.b_queues[r]:
                packet = self.b_queues[r].popleft()
                header = packet[0]
                assert isinstance(header, Header)
                d = xy_direction(rx, ry, header.source_x, header.source_y).name
                await self._send_b_word(
                    r, d, header.encode(self.params), rng=rng, is_header=True)
                for word in packet[1:]:
                    assert isinstance(word, int)
                    await self._send_b_word(r, d, word, rng=rng, is_header=False)
            else:
                await RisingEdge(self.dut.clock)

    async def _send_b_word(self, r: int, d: str, data: int,
                           rng: Random, is_header: bool) -> None:
        sig_name = f'b{d}i_{r}_0'
        while True:
            if rng.random() < self.p_valid:
                self._b_sig(r, d, 'valid').value = 1
                self._b_sig(r, d, 'bits_data').value = data
                self._b_sig(r, d, 'bits_isHeader').value = 1 if is_header else 0
                await ReadOnly()
                ready = int(self._b_sig(r, d, 'ready').value)
                if ready:
                    logger.debug(f"[{sig_name}] sent 0x{data:x} hdr={is_header}")
                    await RisingEdge(self.dut.clock)
                    self._b_sig(r, d, 'valid').value = 0
                    return
                logger.debug(f"[{sig_name}] valid but not ready")
                await RisingEdge(self.dut.clock)
            else:
                self._b_sig(r, d, 'valid').value = 0
                await RisingEdge(self.dut.clock)

    async def _recv_loop(self, r: int, d: str, rng: Random) -> None:
        """Background: capture packets from direction d into a_queues[r]."""
        sig_name = f'a{d}o_{r}_0'
        packet = []
        remaining = 0
        await RisingEdge(self.dut.clock)
        while True:
            self._a_sig(r, d, 'ready').value = 1 if rng.random() < self.p_ready else 0
            await ReadOnly()
            if (int(self._a_sig(r, d, 'valid').value)
                    and int(self._a_sig(r, d, 'ready').value)):
                data = int(self._a_sig(r, d, 'bits_data').value)
                is_header = int(self._a_sig(r, d, 'bits_isHeader').value)
                logger.debug(f"[{sig_name}] recv 0x{data:x} hdr={is_header}")
                if is_header:
                    header = int_to_header(data, self.params)
                    remaining = header.length
                    packet = [header]
                    logger.debug(f"[{sig_name}] msg={header.message_type}"
                                 f" ident={header.ident} len={header.length}")
                else:
                    packet.append(data)
                    remaining -= 1
                if remaining == 0 and packet:
                    logger.info(f"[{sig_name}] complete packet: {len(packet)} words")
                    # Deassert ready before waiting for queue space so
                    # backpressure propagates into the network.
                    await RisingEdge(self.dut.clock)
                    self._a_sig(r, d, 'ready').value = 0
                    await self.a_queue_append(r, packet)
                    packet = []
                    remaining = 0
                    continue
            await RisingEdge(self.dut.clock)

    async def _error_monitor(self) -> None:
        """Background: assert all error signals stay zero every cycle."""
        gather_fields = [
            'identAllocOverwrite', 'missingHeader', 'unexpectedHeader',
            'duplicateArrived', 'badMessageType', 'badPacketLength',
            'unexpectedData',
        ]
        response_fields = [
            'responseAllocOverwrite', 'sentInInvalid', 'sentInDuplicate',
        ]
        # Resolve signal handles once up front.
        signals = []
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
