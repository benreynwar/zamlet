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
from cocotb.triggers import RisingEdge, ReadOnly

from zamlet import utils
from zamlet.control_structures import unpack_int_to_fields
from zamlet.memlet_test.memlet_driver import MemletDriver
from zamlet.params import ZamletParams

logger = logging.getLogger(__name__)


class CocotbDriver(MemletDriver):
    """Drive memlet RTL via cocotb signals.

    send_dir: direction packets arrive FROM (e.g. 'E' if kamlet is east).
    recv_dir: direction responses go TO (e.g. 'E' if kamlet is east).
    These are usually the same direction.
    """

    def __init__(self, dut: HierarchyObject, params: ZamletParams,
                 n_routers: int,
                 send_dir: str = 'W', recv_dir: str = 'W',
                 p_valid: float = 1.0, p_ready: float = 1.0,
                 seed: int = 0):
        super().__init__(n_routers)
        self.dut = dut
        self.params = params
        self.send_dir = send_dir
        self.recv_dir = recv_dir
        self.p_valid = p_valid
        self.p_ready = p_ready
        self.rng = Random(seed)

    def _b_sig(self, r: int, suffix: str):
        return getattr(self.dut, f'io_b{self.send_dir}i_{r}_0_{suffix}')

    def _a_sig(self, r: int, suffix: str):
        return getattr(self.dut, f'io_a{self.recv_dir}o_{r}_0_{suffix}')

    async def reset(self) -> None:
        for r in range(self.n_routers):
            self._b_sig(r, 'valid').value = 0
            self._a_sig(r, 'ready').value = 0

        self.dut.reset.value = 1
        await RisingEdge(self.dut.clock)
        await RisingEdge(self.dut.clock)
        self.dut.reset.value = 0
        # Wait for reset synchronizer (2 cycles) + RegNext on position (1 cycle)
        for _ in range(4):
            await RisingEdge(self.dut.clock)

    def start(self) -> None:
        for r in range(self.n_routers):
            send_rng = utils.create_rng(self.rng)
            recv_rng = utils.create_rng(self.rng)
            cocotb.start_soon(self._send_loop(r, send_rng))
            cocotb.start_soon(self._recv_loop(r, recv_rng))

    async def _send_loop(self, r: int, rng: Random) -> None:
        """Background: drain b_queues[r] with randomized valid."""
        while True:
            if self.b_queues[r]:
                packet = self.b_queues[r].popleft()
                for i, word in enumerate(packet):
                    await self._send_b_word(
                        r, word, rng=rng, is_header=(i == 0))
            else:
                self._b_sig(r, 'valid').value = 0
                await RisingEdge(self.dut.clock)

    async def _send_b_word(self, r: int, data: int,
                           rng: Random, is_header: bool) -> None:
        # Enter after RisingEdge but before ReadOnly
        # Leave after RisingEdge but before ReadOnly
        sig_name = f'b{self.send_dir}i_{r}_0'
        while True:
            if rng.random() < self.p_valid:
                self._b_sig(r, 'valid').value = 1
                self._b_sig(r, 'bits_data').value = data
                self._b_sig(r, 'bits_isHeader').value = 1 if is_header else 0
                await ReadOnly()
                ready = int(self._b_sig(r, 'ready').value)
                if ready:
                    logger.debug(f"[{sig_name}] sent 0x{data:x} hdr={is_header}")
                    await RisingEdge(self.dut.clock)
                    self._b_sig(r, 'valid').value = 0
                    return
                logger.debug(f"[{sig_name}] valid but not ready")
                await RisingEdge(self.dut.clock)
            else:
                self._b_sig(r, 'valid').value = 0
                await RisingEdge(self.dut.clock)

    async def _recv_loop(self, r: int, rng: Random) -> None:
        """Background: capture packets into a_queues[r] with randomized ready."""
        sig_name = f'a{self.recv_dir}o_{r}_0'
        words = []
        remaining = 0
        await RisingEdge(self.dut.clock)
        while True:
            self._a_sig(r, 'ready').value = 1 if rng.random() < self.p_ready else 0
            await ReadOnly()
            if (int(self._a_sig(r, 'valid').value)
                    and int(self._a_sig(r, 'ready').value)):
                data = int(self._a_sig(r, 'bits_data').value)
                is_header = int(self._a_sig(r, 'bits_isHeader').value)
                logger.debug(f"[{sig_name}] recv 0x{data:x} hdr={is_header}")
                if is_header:
                    hdr = unpack_int_to_fields(data, self.params.address_header_fields)
                    remaining = hdr['length']
                    words = [data]
                    logger.debug(f"[{sig_name}] msg={hdr['message_type']}"
                                 f" ident={hdr['ident']} len={hdr['length']}")
                else:
                    words.append(data)
                    remaining -= 1
                if remaining == 0 and words:
                    logger.info(f"[{sig_name}] complete packet: {len(words)} words")
                    self.a_queues[r].append(words)
                    words = []
                    remaining = 0
            await RisingEdge(self.dut.clock)

    async def tick(self, n: int = 1) -> None:
        for _ in range(n):
            await RisingEdge(self.dut.clock)

    def start_soon(self, coro):
        return cocotb.start_soon(coro)
