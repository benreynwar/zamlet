"""Model driver for memlet tests.

Wraps a standalone Python Memlet instance, converting integer-encoded
packets to/from the model's Header objects at the router boundary.

The model uses its own Clock for async simulation. The driver runs the
clock forward when tick() is called.
"""
import logging

from zamlet.future import Future
from zamlet.memlet import Memlet, memlet_coords
from zamlet import kamlet_network
from zamlet.memlet_test.memlet_driver import MemletDriver
from zamlet.message import CHANNEL_MAPPING, Direction, Header, MessageType
from zamlet.monitor import Monitor
from zamlet.params import ZamletParams
from zamlet.router import xy_direction
from zamlet.runner import Clock


logger = logging.getLogger(__name__)


class ModelDriver(MemletDriver):

    def __init__(self, params: ZamletParams, kamlet_index: int = 0,
                 write_latency: int = 32, read_latency: int = 32,
                 max_pending: int = 2):
        coords = memlet_coords(params, kamlet_index)
        knet_x, knet_y = kamlet_network.kamlet_memlet_kcoord(
            params, kamlet_index)
        self.kamlet_knet_x, self.kamlet_knet_y = kamlet_network.kamlet_kcoord(
            params, kamlet_index)
        kx = (kamlet_index % params.k_cols) * params.j_cols
        ky = (kamlet_index // params.k_cols) * params.j_rows
        kamlet_x = kx + params.west_offset
        kamlet_y = ky + params.north_offset
        super().__init__(params, coords, kamlet_x, kamlet_y)
        self.clock = Clock()
        self.monitor = Monitor(self.clock, params, detailed=False)
        self.memlet = Memlet(
            self.clock, params, coords,
            knet_x=knet_x,
            knet_y=knet_y,
            kamlet_coords=(kamlet_x, kamlet_y),
            monitor=self.monitor,
            write_latency=write_latency,
            read_latency=read_latency,
            max_pending=max_pending,
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
        self.clock.create_task(self._recv_kamlet_network_loop())

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
                if self._is_control_packet(header):
                    await self._send_control_packet(packet)
                    continue
                self._record_injected_packet_sent(header, r)
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

    def _is_control_packet(self, header: Header) -> bool:
        return header.message_type in (
            MessageType.READ_LINE_ADDR,
            MessageType.WRITE_LINE_ADDR,
            MessageType.WRITE_LINE_READ_LINE_ADDR,
        )

    async def _send_control_packet(self, packet: list) -> None:
        header = packet[0]
        header.source_x = self.kamlet_knet_x
        header.source_y = self.kamlet_knet_y
        header.target_x = self.memlet.knet_x
        header.target_y = self.memlet.knet_y
        self.monitor.record_kamlet_message_sent(
            None,
            header.message_type.name,
            ident=header.slot,
            tag=self.monitor._tag_from_header(header),
            src_x=header.source_x,
            src_y=header.source_y,
            dst_x=header.target_x,
            dst_y=header.target_y,
        )
        channel = CHANNEL_MAPPING[header.message_type]
        router = self.memlet.kamlet_network_routers[channel]
        in_dir = xy_direction(
            router.x, router.y, header.source_x, header.source_y)
        buf = router._input_buffers[in_dir]
        for word in packet:
            while not buf.can_append():
                await self.clock.next_cycle
            buf.append(word)
            await self.clock.next_cycle

    def _record_injected_packet_sent(self, header: Header, router_idx: int) -> None:
        """Record packets injected by the standalone test driver."""
        dst_x, dst_y = self.router_coords[router_idx]
        self.monitor.record_message_sent(
            None,
            header.message_type.name,
            ident=header.slot,
            tag=self.monitor._tag_from_header(header),
            src_x=header.source_x,
            src_y=header.source_y,
            dst_x=dst_x,
            dst_y=dst_y,
        )

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
                    await self.a_queue_append(r, packet)
            await self.clock.next_cycle

    async def _recv_kamlet_network_loop(self) -> None:
        """Read Kamlet-network control responses from the memlet."""
        for router in self.memlet.kamlet_network_routers:
            assert router.x == self.memlet.knet_x
            assert router.y == self.memlet.knet_y
        while True:
            for router in self.memlet.kamlet_network_routers:
                for d, buf in router._output_buffers.items():
                    if d == Direction.H or not buf:
                        continue
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
                    self.monitor.record_kamlet_message_received_by_header(
                        header, self.kamlet_knet_x, self.kamlet_knet_y)
                    await self.a_queue_append(0, packet)
            await self.clock.next_cycle

    def _make_future(self):
        return Future(self.clock.create_event())

    async def tick(self, n: int = 1) -> None:
        for _ in range(n):
            await self.clock.next_cycle

    def start_soon(self, coro):
        return self.clock.create_task(coro)
