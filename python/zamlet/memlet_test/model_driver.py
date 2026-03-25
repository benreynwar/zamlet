"""Model driver for memlet tests.

Wraps a standalone Python Memlet instance, converting integer-encoded
packets to/from the model's Header objects at the router boundary.

The model uses its own Clock for async simulation. The driver runs the
clock forward when tick() is called.
"""

from zamlet.memlet import Memlet, memlet_coords
from zamlet.memlet_test.memlet_driver import MemletDriver
from zamlet.message import Header, header_to_int, int_to_header
from zamlet.monitor import Monitor
from zamlet.params import ZamletParams
from zamlet.router import Direction
from zamlet.runner import Clock


class ModelDriver(MemletDriver):

    def __init__(self, params: ZamletParams, kamlet_index: int = 0):
        coords = memlet_coords(params, kamlet_index)
        super().__init__(n_routers=len(coords))
        self.params = params
        self.clock = Clock()
        self.monitor = Monitor(self.clock, params, enabled=False)

        kamlet_x = (kamlet_index % params.k_cols) * params.j_cols
        kamlet_y = (kamlet_index // params.k_cols) * params.j_rows
        self.memlet = Memlet(
            self.clock, params, coords,
            kamlet_coords=(kamlet_x, kamlet_y),
            monitor=self.monitor,
        )

    async def reset(self) -> None:
        pass

    def start(self) -> None:
        self.clock.create_task(self.memlet.run())
        for r in range(self.n_routers):
            self.clock.create_task(self._send_loop(r))
            self.clock.create_task(self._recv_loop(r))

    async def _send_loop(self, r: int) -> None:
        """Convert integer packets from b_queues[r] into Header objects
        and push into the memlet's router input buffer."""
        router = self.memlet.routers[r][0]
        buf = router._input_buffers[Direction.W]
        while True:
            if self.b_queues[r]:
                packet = self.b_queues[r].popleft()
                header = int_to_header(packet[0], self.params)
                header.length = len(packet)
                buf.append(header)
                for word in packet[1:]:
                    while not buf.can_append():
                        await self.clock.next_cycle
                    buf.append(word)
            else:
                await self.clock.next_cycle

    async def _recv_loop(self, r: int) -> None:
        """Read Header objects from the memlet's router output buffer
        and convert to integer packets for a_queues[r]."""
        router = self.memlet.routers[r][0]
        buf = router._output_buffers[Direction.W]
        while True:
            if buf:
                word = buf.popleft()
                assert isinstance(word, Header)
                header = word
                remaining = header.length
                int_words = [header_to_int(header, self.params)]
                while remaining > 0:
                    if buf:
                        body = buf.popleft()
                        if isinstance(body, bytes):
                            int_words.append(
                                int.from_bytes(body, 'little'))
                        else:
                            int_words.append(int(body))
                        remaining -= 1
                    else:
                        await self.clock.next_cycle
                self.a_queues[r].append(int_words)
            else:
                await self.clock.next_cycle

    async def tick(self, n: int = 1) -> None:
        for _ in range(n):
            await self.clock.next_cycle
