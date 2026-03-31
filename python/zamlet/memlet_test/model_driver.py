"""Model driver for memlet tests.

Wraps a standalone Python Memlet instance, converting integer-encoded
packets to/from the model's Header objects at the router boundary.

The model uses its own Clock for async simulation. The driver runs the
clock forward when tick() is called.
"""
import logging

from zamlet.future import Future
from zamlet.memlet import Memlet, memlet_coords
from zamlet.memlet_test.memlet_driver import MemletDriver
from zamlet.message import Direction, Header
from zamlet.monitor import Monitor
from zamlet.params import ZamletParams
from zamlet.router import xy_direction
from zamlet.runner import Clock


logger = logging.getLogger(__name__)


class ModelDriver(MemletDriver):

    def __init__(self, params: ZamletParams, kamlet_index: int = 0):
        coords = memlet_coords(params, kamlet_index)
        kx = (kamlet_index % params.k_cols) * params.j_cols
        ky = (kamlet_index // params.k_cols) * params.j_rows
        kamlet_x = kx + params.west_offset
        kamlet_y = ky + params.north_offset
        super().__init__(params, coords, kamlet_x, kamlet_y)
        self.clock = Clock()
        self.monitor = Monitor(self.clock, params, enabled=False)
        self.memlet = Memlet(
            self.clock, params, coords,
            kamlet_coords=(kamlet_x, kamlet_y),
            monitor=self.monitor,
        )

    async def reset(self) -> None:
        pass

    def start(self) -> None:
        super().start()
        self.clock.create_task(self.memlet.run())
        self.clock.create_task(self._update_loop())
        for r in range(self.n_routers):
            self.clock.create_task(self._send_loop(r))
            self.clock.create_task(self._recv_loop(r))

    async def _update_loop(self) -> None:
        while True:
            await self.clock.next_update
            self.memlet.update()

    async def _send_loop(self, r: int) -> None:
        """Send packets from b_queues[r] into the memlet's router input buffer."""
        router = self.memlet.routers[r][0]
        while True:
            if self.b_queues[r]:
                packet = self.b_queues[r].popleft()
                header = packet[0]
                in_dir = xy_direction(
                    router.x, router.y, header.source_x, header.source_y)
                buf = router._input_buffers[in_dir]
                for word in packet:
                    while not buf.can_append():
                        await self.clock.next_cycle
                    logger.debug(f'Sending word to router {r} via {in_dir}')
                    buf.append(word)
            else:
                await self.clock.next_cycle

    async def _recv_loop(self, r: int) -> None:
        """Read packets from the memlet's router output buffers into a_queues[r]."""
        router = self.memlet.routers[r][0]
        dirs = [d for d in router._output_buffers if d != Direction.H]
        while True:
            for d in dirs:
                buf = router._output_buffers[d]
                if buf:
                    word = buf.popleft()
                    assert isinstance(word, Header)
                    header = word
                    remaining = header.length
                    packet = [header]
                    while remaining > 0:
                        await self.clock.next_cycle
                        if buf:
                            packet.append(buf.popleft())
                            remaining -= 1
                    self.a_queues[r].append(packet)
            await self.clock.next_cycle

    def _make_future(self):
        return Future(self.clock.create_event())

    async def tick(self, n: int = 1) -> None:
        for _ in range(n):
            await self.clock.next_cycle

    def start_soon(self, coro):
        return self.clock.create_task(coro)
