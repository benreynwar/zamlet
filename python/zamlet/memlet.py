import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional, Any
from collections import deque
import random

from zamlet.params import ZamletParams
from zamlet.runner import Clock
from zamlet.router import Router, Direction
from zamlet.message import Header, IdentHeader, AddressHeader
from zamlet.utils import Queue
from zamlet.message import MessageType, SendType, CHANNEL_MAPPING
from zamlet.monitor import Monitor


logger = logging.getLogger(__name__)


@dataclass
class _Pending:
    """Tracks an in-flight memory operation. See docs/PLAN_memlet_memory_model.md."""
    sram_address: int
    has_write: bool
    has_read: bool
    write_done: bool = False
    read_done: bool = False
    cache_line: Optional[bytes] = None

    def is_complete(self) -> bool:
        return (self.write_done >= self.has_write
                and self.read_done >= self.has_read)


@dataclass
class GatheringSlot:
    """
    A slot for gathering write data from all jamlets. Used for both WRITE_LINE
    and WRITE_LINE_READ_LINE. The ADDR packet allocates the slot, then each
    jamlet sends a WRITE_LINE_DATA packet to fill its portion.
    """
    ident: int
    addr_packet: Optional[list] = None
    data_packets: List[Optional[list]] = field(default_factory=list)

    def is_complete(self, j_in_k: int) -> bool:
        assert len(self.data_packets) == j_in_k
        return self.addr_packet is not None and all(d is not None for d in self.data_packets)

    def set_addr(self, packet: list) -> None:
        assert self.addr_packet is None, \
            f'Duplicate addr packet for ident={self.ident}'
        self.addr_packet = packet

    def add_data(self, j_index: int, words: list) -> None:
        assert self.data_packets[j_index] is None, \
            f'Duplicate data for ident={self.ident} j_index={j_index}'
        self.data_packets[j_index] = words


WRITE_LINE_RESPONSE_R_INDEX = 0


def memlet_coords(params: ZamletParams, kamlet_index: int):
    """Compute routing coordinates for a kamlet's memlet.

    Memlets are placed on the left or right edge of the jamlet grid.
    Returns a list of (x, y) in routing coordinates (always non-negative).

    Left memlets:  x = west_offset - 1 - edge_col
    Right memlets: x = west_offset + k_cols * j_cols + edge_col
    All y values:  north_offset + y_start + dy
    """
    k_col = kamlet_index % params.k_cols
    k_row = kamlet_index // params.k_cols
    edge_height = params.k_rows * params.j_rows
    left = k_col < params.k_cols // 2
    if left:
        n_side_cols = params.k_cols // 2
        col_in_side = k_col
    else:
        n_side_cols = params.k_cols - params.k_cols // 2
        col_in_side = (params.k_cols - 1) - k_col
    n_memlets = n_side_cols * params.k_rows
    n_edge_cols = (n_memlets + edge_height - 1) // edge_height
    memlets_per_col = (n_memlets + n_edge_cols - 1) // n_edge_cols
    positions_per_memlet = edge_height // memlets_per_col
    idx = k_row * n_side_cols + col_in_side
    edge_col = idx // memlets_per_col
    slot = idx % memlets_per_col
    y_start = slot * positions_per_memlet
    if left:
        mem_x = params.west_offset - 1 - edge_col
    else:
        mem_x = params.west_offset + params.k_cols * params.j_cols + edge_col
    return [(mem_x, params.north_offset + y_start + dy)
            for dy in range(positions_per_memlet)]


def j_in_k_to_m_router(j_in_k_index: int, n_routers: int, j_in_k: int) -> int:
    """Map a jamlet-in-kamlet index to a memlet router index."""
    assert j_in_k % n_routers == 0
    jamlets_per_router = j_in_k // n_routers
    return j_in_k_index // jamlets_per_router


class Memlet:

    def __init__(self, clock: Clock, params: ZamletParams, coords: List[Tuple[int, int]],
                 kamlet_coords, monitor: Monitor,
                 write_latency: int = 32, read_latency: int = 32,
                 max_pending: int = 2):
        """
        A point of connection to off-chip DRAM.
        Can cover multiple 'nodes' on the grid and thus have multiple routers.
        See docs/PLAN_memlet_memory_model.md for memory pipeline architecture.
        """
        self.clock = clock
        self.params = params
        self.monitor = monitor
        self.coords = coords
        self.routers = [[Router(clock, params, x, y, channel=channel)
                         for channel in range(params.n_channels)]
                        for x, y in coords]

        self.lines: Dict[int, bytes] = {}
        self.n_lines = params.kamlet_memory_bytes // params.cache_line_bytes
        self.write_latency = write_latency
        self.read_latency = read_latency
        self.max_pending = max_pending
        self._pending: Dict[int, _Pending] = {}
        self._pending_order: List[int] = []

        self.n_routers = len(self.coords)
        # Make send and receive queues for each router

        self.receive_read_line_queue = Queue(2)
        # Gathering slots for WRITE_LINE and WRITE_LINE_READ_LINE
        self.gathering_slots: List[Optional[GatheringSlot]] = [
            None for _ in range(self.params.n_memlet_gathering_slots)
        ]
        # Queue for completed gathering slots ready to process
        self.complete_gathering_queue: deque = deque()
        # Queue for DROP responses to send
        self.send_drop_queues = [deque() for _ in range(self.n_routers)]
        self.send_write_line_response_queue = Queue(2)
        self.send_read_line_response_queues = [Queue(2) for _ in coords]
        self.send_write_line_read_line_response_queues = [Queue(2) for _ in coords]

        self.kamlet_coords = kamlet_coords
        self.jamlet_coords = []
        for j_in_k_y in range(self.params.j_rows):
            for j_in_k_x in range(self.params.j_cols):
                self.jamlet_coords.append((self.kamlet_coords[0] + j_in_k_x, self.kamlet_coords[1] + j_in_k_y))

    def find_gathering_slot(self, ident: int) -> Optional[int]:
        """Find a gathering slot for this ident, or return None if not found."""
        for i, slot in enumerate(self.gathering_slots):
            if slot is not None and slot.ident == ident:
                return i
        return None

    def allocate_gathering_slot(self, ident: int) -> Optional[int]:
        """Allocate a new gathering slot for this ident, or return None if all slots full."""
        assert self.find_gathering_slot(ident) is None, \
            f'Gathering slot already exists for ident={ident}'
        for i, slot in enumerate(self.gathering_slots):
            if slot is None:
                self.gathering_slots[i] = GatheringSlot(
                    ident=ident,
                    data_packets=[None] * self.params.j_in_k,
                )
                return i
        return None

    def free_gathering_slot(self, slot_index: int) -> None:
        """Free a gathering slot after processing."""
        assert self.gathering_slots[slot_index] is not None
        self.gathering_slots[slot_index] = None

    def update(self):
        for router_channels in self.routers:
            for router in router_channels:
                router.update()
        self.receive_read_line_queue.update()
        for queue in self.send_read_line_response_queues:
            queue.update()
        self.send_write_line_response_queue.update()
        for queue in self.send_write_line_read_line_response_queues:
            queue.update()

    async def receive_packets(self, index):
        """
        This takes care of receiving packets from a router
        and placing them in a receive queue.
        """
        assert index < len(self.coords)
        header = None
        remaining = 0
        packet = []
        while True:
            await self.clock.next_cycle
            for channel in range(self.params.n_channels):
                queue = self.routers[index][channel]._output_buffers[Direction.H]
                r = self.routers[index][channel]
                if queue:
                    word = queue.popleft()
                    if not header:
                        assert isinstance(word, Header)
                        header = word.copy()
                        remaining = header.length
                    else:
                        assert not isinstance(word, Header)
                        assert header
                        remaining -= 1
                    packet.append(word)
                    if remaining == 0:
                        # Record message received for all cache messages
                        dst_x, dst_y = self.coords[index]
                        self.monitor.record_message_received_by_header(packet[0], dst_x, dst_y)

                        if packet[0].message_type == MessageType.READ_LINE_ADDR:
                            while not self.receive_read_line_queue.can_append():
                                await self.clock.next_cycle
                            self.receive_read_line_queue.append(packet)
                        elif packet[0].message_type in (
                            MessageType.WRITE_LINE_ADDR,
                            MessageType.WRITE_LINE_READ_LINE_ADDR,
                        ):
                            msg_type = packet[0].message_type
                            ident = packet[0].ident
                            src_x = packet[0].source_x
                            src_y = packet[0].source_y
                            slot_index = self.allocate_gathering_slot(ident)
                            if slot_index is None:
                                if msg_type == MessageType.WRITE_LINE_ADDR:
                                    drop_type = MessageType.WRITE_LINE_ADDR_DROP
                                else:
                                    drop_type = MessageType.WRITE_LINE_READ_LINE_ADDR_DROP
                                logger.debug(
                                    f'{self.clock.cycle}: [MEMLET] DROP {msg_type.name} '
                                    f'ident={ident} - no gathering slots'
                                )
                                self.monitor.record_message_sent(
                                    None, drop_type.name,
                                    ident=ident, tag=None,
                                    src_x=dst_x, src_y=dst_y,
                                    dst_x=src_x, dst_y=src_y)
                                drop_header = IdentHeader(
                                    target_x=src_x,
                                    target_y=src_y,
                                    source_x=dst_x,
                                    source_y=dst_y,
                                    message_type=drop_type,
                                    length=0,
                                    send_type=SendType.SINGLE,
                                    ident=ident,
                                )
                                self.send_drop_queues[index].append([drop_header])
                            else:
                                self.gathering_slots[slot_index].set_addr(packet)
                        elif packet[0].message_type == MessageType.WRITE_LINE_DATA:
                            j_in_k_x = (packet[0].source_x - self.params.west_offset) % self.params.j_cols
                            j_in_k_y = (packet[0].source_y - self.params.north_offset) % self.params.j_rows
                            j_index = j_in_k_y * self.params.j_cols + j_in_k_x
                            ident = packet[0].ident
                            src_x = packet[0].source_x
                            src_y = packet[0].source_y
                            slot_index = self.find_gathering_slot(ident)
                            if slot_index is None:
                                logger.debug(
                                    f'{self.clock.cycle}: [MEMLET] DROP WRITE_LINE_DATA '
                                    f'ident={ident} j_index={j_index} - no slot'
                                )
                                self.monitor.record_message_sent(
                                    None, MessageType.WRITE_LINE_DATA_DROP.name,
                                    ident=ident, tag=None,
                                    src_x=dst_x, src_y=dst_y,
                                    dst_x=src_x, dst_y=src_y)
                                drop_header = IdentHeader(
                                    target_x=src_x,
                                    target_y=src_y,
                                    source_x=dst_x,
                                    source_y=dst_y,
                                    message_type=MessageType.WRITE_LINE_DATA_DROP,
                                    length=0,
                                    send_type=SendType.SINGLE,
                                    ident=ident,
                                )
                                self.send_drop_queues[index].append([drop_header])
                            else:
                                slot = self.gathering_slots[slot_index]
                                slot.add_data(j_index, packet[1:])
                                if slot.is_complete(self.params.j_in_k):
                                    self.complete_gathering_queue.append(slot_index)
                        header = None
                        packet = []

    async def send_packet(self, index, channel, packet):
        queue = self.routers[index][channel]._input_buffers[Direction.H]
        for word in packet:
            while True:
                if queue.can_append():
                    queue.append(word)
                    await self.clock.next_cycle
                    break
                else:
                    pass
                await self.clock.next_cycle

    async def send_packets(self, index):
        """
        This takes care of taking packets from a send queue and
        sending them out over a router.
        """
        assert index < len(self.coords)
        await self.clock.next_cycle
        read_next = True
        while True:
            packets = []
            if self.send_drop_queues[index]:
                packets.append(self.send_drop_queues[index].popleft())
            if self.send_read_line_response_queues[index]:
                packets.append(self.send_read_line_response_queues[index].popleft())
            if index == WRITE_LINE_RESPONSE_R_INDEX and self.send_write_line_response_queue:
                packets.append(self.send_write_line_response_queue.popleft())
            if self.send_write_line_read_line_response_queues[index]:
                packets.append(self.send_write_line_read_line_response_queues[index].popleft())
            for packet in packets:
                channel = CHANNEL_MAPPING[packet[0].message_type]
                await self.send_packet(index, channel, packet)
            if not packets:
                await self.clock.next_cycle


    async def _send_read_responses(self, cache_line: bytes, ident: int,
                                   sram_address: int, resp_type: MessageType,
                                   send_queues: list) -> None:
        """Build and send read response packets to each jamlet."""
        wb = self.params.word_bytes
        cache_slot = sram_address * self.params.j_in_k // self.params.cache_line_bytes
        cache_request_span_id = self.monitor.get_cache_request_span_id(
            self.kamlet_coords[0], self.kamlet_coords[1], cache_slot)
        packet_payloads = [[] for _ in range(self.params.j_in_k)]
        for word_index in range(len(cache_line) // wb):
            word = int.from_bytes(
                cache_line[word_index * wb: (word_index + 1) * wb], 'little')
            packet_payloads[word_index % self.params.j_in_k].append(word)
        resp_packets = [[] for _ in range(self.n_routers)]
        for j_in_k_index, payload in enumerate(packet_payloads):
            router_index = j_in_k_to_m_router(
                j_in_k_index, self.n_routers, self.params.j_in_k)
            target_x, target_y = self.jamlet_coords[j_in_k_index]
            channel = CHANNEL_MAPPING[resp_type]
            resp_header = AddressHeader(
                target_x=target_x,
                target_y=target_y,
                source_x=self.routers[router_index][channel].x,
                source_y=self.routers[router_index][channel].y,
                message_type=resp_type,
                length=len(payload),
                send_type=SendType.SINGLE,
                address=sram_address,
                ident=ident,
            )
            resp_packets[router_index].append([resp_header] + payload)
        while True:
            await self.clock.next_cycle
            while not all(q.can_append() for q in send_queues):
                await self.clock.next_cycle
            for router_index in range(self.n_routers):
                if resp_packets[router_index]:
                    resp_packet = resp_packets[router_index].pop(0)
                    send_queues[router_index].append(resp_packet)
                    h = resp_packet[0]
                    self.monitor.record_message_sent(
                        cache_request_span_id, resp_type.name,
                        ident=ident, tag=cache_slot,
                        src_x=h.source_x, src_y=h.source_y,
                        dst_x=h.target_x, dst_y=h.target_y)
            if all(len(p) == 0 for p in resp_packets):
                break

    async def handle_read_line_packets(self):
        while True:
            if self.receive_read_line_queue:
                packet = self.receive_read_line_queue.popleft()
                address = packet[1]
                ident = packet[0].ident
                sram_address = packet[0].address
                assert address % self.params.cache_line_bytes == 0
                index = address // self.params.cache_line_bytes
                logger.debug(
                    f'handle_read_line_packet: ident={ident} '
                    f'address={hex(address)}')
                await self._submit_pending(
                    ident, sram_address, has_write=False, has_read=True)
                self.clock.create_task(self._do_read(ident, index))
            await self.clock.next_cycle

    def _assemble_gathered_line(self, slot: GatheringSlot) -> Tuple[int, bytes]:
        """Assemble a cache line from all jamlets' data packets. Returns (index, data)."""
        write_address = slot.addr_packet[1]
        assert write_address % self.params.cache_line_bytes == 0
        write_index = write_address // self.params.cache_line_bytes
        n_words = len(slot.data_packets[0])
        wb = self.params.word_bytes
        line_words = []
        for word_index in range(n_words):
            for j_index in range(self.params.j_in_k):
                line_words.append(slot.data_packets[j_index][word_index])
        for j_index in range(self.params.j_in_k):
            j_words = [f'0x{slot.data_packets[j_index][w]:x}' for w in range(n_words)]
            logger.debug(
                f'{self.clock.cycle}: [MEMLET_RECV] kamlet={self.kamlet_coords} '
                f'j_index={j_index} write_addr=0x{write_address:x} words={j_words}')
        data = b''.join(w.to_bytes(wb, 'little') for w in line_words)
        logger.debug(
            f'{self.clock.cycle}: [MEMLET_ASSEMBLE] kamlet={self.kamlet_coords} '
            f'write_index={write_index} write_addr=0x{write_address:x} '
            f'data={data.hex()}')
        return write_index, data

    async def _submit_pending(self, ident: int, sram_address: int,
                              has_write: bool, has_read: bool) -> None:
        """Register a pending operation. Blocks if at capacity."""
        while len(self._pending) >= self.max_pending:
            await self.clock.next_cycle
        self._pending[ident] = _Pending(
            sram_address=sram_address, has_write=has_write, has_read=has_read)
        self._pending_order.append(ident)

    async def _do_write(self, ident: int, index: int, data: bytes) -> None:
        """Memory write task: latency, store, mark done."""
        for _ in range(self.write_latency):
            await self.clock.next_cycle
        address = index * self.params.cache_line_bytes
        logger.debug(
            f'{self.clock.cycle}: MEM_WRITE: addr=0x{address:08x} '
            f'index=0x{index:x} data={data.hex()}')
        self.lines[index] = data
        self._pending[ident].write_done = True

    async def _do_read(self, ident: int, index: int) -> None:
        """Memory read task: latency, read, mark done."""
        for _ in range(self.read_latency):
            await self.clock.next_cycle
        address = index * self.params.cache_line_bytes
        if index not in self.lines:
            data = bytes(
                random.getrandbits(8)
                for _ in range(self.params.cache_line_bytes))
            logger.debug(
                f'{self.clock.cycle}: MEM_READ: addr=0x{address:08x} '
                f'index={index} data={data.hex()} (UNINITIALIZED - random)')
        else:
            data = self.lines[index]
            logger.debug(
                f'{self.clock.cycle}: MEM_READ: addr=0x{address:08x} '
                f'index={index} data={data.hex()}')
        p = self._pending[ident]
        p.cache_line = data
        p.read_done = True

    async def _handle_memory_responses(self) -> None:
        """Consumer: scan pending list for first complete, send response."""
        while True:
            sent = False
            for ident in self._pending_order:
                if self._pending[ident].is_complete():
                    p = self._pending.pop(ident)
                    self._pending_order.remove(ident)
                    if p.has_read:
                        resp_type = (MessageType.WRITE_LINE_READ_LINE_RESP
                                     if p.has_write
                                     else MessageType.READ_LINE_RESP)
                        send_queues = (
                            self.send_write_line_read_line_response_queues
                            if p.has_write
                            else self.send_read_line_response_queues)
                        await self._send_read_responses(
                            p.cache_line, ident, p.sram_address,
                            resp_type, send_queues)
                    else:
                        channel = CHANNEL_MAPPING[MessageType.WRITE_LINE_RESP]
                        resp_header = IdentHeader(
                            target_x=self.kamlet_coords[0],
                            target_y=self.kamlet_coords[1],
                            source_x=self.routers[
                                WRITE_LINE_RESPONSE_R_INDEX][channel].x,
                            source_y=self.routers[
                                WRITE_LINE_RESPONSE_R_INDEX][channel].y,
                            message_type=MessageType.WRITE_LINE_RESP,
                            length=0,
                            send_type=SendType.SINGLE,
                            ident=ident,
                        )
                        while not self.send_write_line_response_queue.can_append():
                            await self.clock.next_cycle
                        self.send_write_line_response_queue.append([resp_header])
                    sent = True
                    break
            if not sent:
                await self.clock.next_cycle

    async def handle_gathering_complete(self):
        """Process complete gathering slots from the queue."""
        while True:
            await self.clock.next_cycle
            if self.complete_gathering_queue:
                slot_index = self.complete_gathering_queue.popleft()
                slot = self.gathering_slots[slot_index]
                msg_type = slot.addr_packet[0].message_type
                ident = slot.addr_packet[0].ident
                sram_address = slot.addr_packet[0].address
                write_index, data = self._assemble_gathered_line(slot)
                if msg_type == MessageType.WRITE_LINE_ADDR:
                    await self._submit_pending(
                        ident, sram_address, has_write=True, has_read=False)
                    self.clock.create_task(
                        self._do_write(ident, write_index, data))
                elif msg_type == MessageType.WRITE_LINE_READ_LINE_ADDR:
                    read_address = slot.addr_packet[2]
                    assert read_address % self.params.cache_line_bytes == 0
                    read_index = read_address // self.params.cache_line_bytes
                    await self._submit_pending(
                        ident, sram_address, has_write=True, has_read=True)
                    self.clock.create_task(
                        self._do_write(ident, write_index, data))
                    self.clock.create_task(
                        self._do_read(ident, read_index))
                self.free_gathering_slot(slot_index)
            else:
                await self.clock.next_cycle

    async def run(self):
        for router_channels in self.routers:
            for router in router_channels:
                self.clock.create_task(router.run())
        for index in range(len(self.coords)):
            self.clock.create_task(self.receive_packets(index))
            self.clock.create_task(self.send_packets(index))
        self.clock.create_task(self.handle_read_line_packets())
        self.clock.create_task(self.handle_gathering_complete())
        self.clock.create_task(self._handle_memory_responses())
