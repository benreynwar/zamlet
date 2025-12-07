import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional, Any
from collections import deque
import random

from zamlet.params import LamletParams
from zamlet.runner import Clock
from zamlet.router import Router, Direction
from zamlet.message import Header, IdentHeader, AddressHeader
from zamlet.utils import Queue
from zamlet.message import MessageType, SendType, CHANNEL_MAPPING
from zamlet.monitor import Monitor


logger = logging.getLogger(__name__)


@dataclass
class GatheringSlot:
    """
    A slot for gathering WRITE_LINE_READ_LINE packets from all jamlets.
    The memlet uses a fixed number of these slots to handle concurrent
    cache line operations without requiring all jamlets to send simultaneously.
    """
    ident: int
    packets: List[Optional[Any]] = field(default_factory=list)

    def is_complete(self, j_in_k: int) -> bool:
        assert len(self.packets) == j_in_k
        return all(p is not None for p in self.packets)

    def add_packet(self, j_index: int, packet: Any) -> None:
        assert self.packets[j_index] is None, \
            f'Duplicate packet for ident={self.ident} j_index={j_index}'
        self.packets[j_index] = packet


WRITE_LINE_RESPONSE_R_INDEX = 0


def get_cols_routers(params):
    """
    We have one memlet for every kamlet.
    Memlets are arranged down the west and east sides of the grid.
    
    Consider a row of kamlets. It contains k_cols kamlets.
    Each side contains k_cols/2 memlets.
    Each side is j_rows high.

    m_cols: Numbers of columns of memlets on each side.
    n_routers_in_memlet: Number of router spots in the grid that each
                         memlet covers.
    """
    assert params.k_cols % 2 == 0
    if params.k_cols//2 > params.j_rows:
        assert params.k_cols//2  % params.j_rows == 0
        m_cols = params.k_cols//2//params.j_rows
        n_routers_in_memlet = 1
    else:
        assert params.j_rows % (params.k_cols//2) == 0
        m_cols = 1
        n_routers_in_memlet = params.j_rows * 2 // params.k_cols
    return m_cols, n_routers_in_memlet


def memlet_coords_to_index(params: LamletParams, x: int, y: int) -> Tuple[int, int]:
    """
    For a given (x, y) coord we want to know what the m_index of that
    memlet is, which is equal to the k_index of the kamlet it communicates
    with.
    """
    # We require east/west symmetry.
    m_cols, n_routers_in_memlet = get_cols_routers(params)
    # Work out which kamlet row we are in.
    k_y = y // params.j_rows
    # Work out our kamlet index in that row
    # (m_x, m_y) is the position in the rectange of memlets at the edge.
    m_y = y % params.j_rows
    if x < 0:
        m_x = x + m_cols
        row_m_index = m_y * m_cols // n_routers_in_memlet + m_x
    elif x >= params.j_cols * params.k_cols:
        # Here we take m going right to left for symmetry
        m_x = (params.j_cols * params.k_cols + m_cols - 1) - x
        # And we get the reverse row index (right to left)
        rev_row_m_index = m_y * m_cols // n_routers_in_memlet + m_x
        # And then the correct order index in the row
        row_m_index = params.k_cols - 1 - rev_row_m_index
    else:
        raise ValueError('Bad memlet coords ({x}, {y})')
    m_index = row_m_index + k_y * params.k_cols
    router_index = m_y % n_routers_in_memlet
    return m_index, router_index


def j_in_k_to_m_router(params: LamletParams, j_in_k_index) -> int:
    """
    For a given jamlet in a kamlet, we want to know which
    router in a memlet it should communicate with.
    """
    m_cols, n_routers_in_memlet = get_cols_routers(params)
    assert params.j_in_k % n_routers_in_memlet == 0
    jamlets_per_router = params.j_in_k // n_routers_in_memlet
    return j_in_k_index//jamlets_per_router


def m_router_coords(params: LamletParams, m_index: int, router_index: int) -> Tuple[int, int]:
    m_cols, n_routers_in_memlet = get_cols_routers(params)
    if m_index % params.k_cols < params.k_cols//2:
        # We're on the west side
        # m_side_index should number them 
        # 0 1
        # 2 3 ...
        m_side_index = m_index//params.k_cols*(params.k_cols//2) + m_index % (params.k_cols//2)
        m_x = -m_cols + (m_side_index % m_cols)
    else:
        # We're on the east side
        # m_side_index should number them
        # 1 0
        # 3 2 ...
        m_side_index = m_index//params.k_cols*(params.k_cols//2) + params.k_cols//2 - 1 - (m_index % params.k_cols//2)
        m_x = params.j_cols * params.k_cols + m_cols - 1 - (m_side_index % m_cols)
    m_y = m_side_index // m_cols * n_routers_in_memlet + router_index
    assert 0 <= m_y < params.j_rows * params.k_rows
    return (m_x, m_y)


def jamlet_coords_to_m_router_coords(params: LamletParams, j_x: int, j_y: int) -> Tuple[int, int]:
    k_x  = j_x // params.j_cols
    k_y  = j_y // params.j_rows
    k_index = k_y * params.k_cols + k_x
    j_in_k_x = j_x % params.j_cols
    j_in_k_y = j_y % params.j_rows
    j_in_k_index = j_in_k_y * params.j_cols + j_in_k_x
    router_index = j_in_k_to_m_router(params, j_in_k_index)
    m_index = k_index
    r_x, r_y = m_router_coords(params, m_index, router_index)
    assert 0 <= r_y < params.j_rows * params.k_rows
    return (r_x, r_y)


class Memlet:

    def __init__(self, clock: Clock, params: LamletParams, coords: List[Tuple[int, int]],
                 kamlet_coords, monitor: Monitor):
        """
        A point of connection to off-chip DRAM.
        Can cover multiple 'nodes' on the grid and thus have multiple routers.
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
        self.m_cols, self.n_routers = get_cols_routers(self.params)
        # Make send and receive queues for each router

        self.receive_write_line_queues = [Queue(2) for _ in range(self.params.j_in_k)]
        self.receive_read_line_queue = Queue(2)
        # Gathering slots for WRITE_LINE_READ_LINE - allows concurrent operations
        # without requiring all jamlets to send at once
        self.gathering_slots: List[Optional[GatheringSlot]] = [
            None for _ in range(self.params.n_memlet_gathering_slots)
        ]
        # Queue for completed gathering slots ready to process
        self.complete_gathering_queue: deque = deque()
        # Queue for DROP responses to send
        self.send_drop_queue: deque = deque()
        self.send_write_line_response_queue = Queue(2)
        self.send_read_line_response_queues = [Queue(2) for _ in coords]
        self.send_write_line_read_line_response_queues = [Queue(2) for _ in coords]

        self.kamlet_coords = kamlet_coords
        self.jamlet_coords = []
        for j_in_k_y in range(self.params.j_rows):
            for j_in_k_x in range(self.params.j_cols):
                self.jamlet_coords.append((self.kamlet_coords[0] + j_in_k_x, self.kamlet_coords[1] + j_in_k_y))

    def write_cache_line(self, index, data):
        assert index < self.n_lines
        address = index * self.params.cache_line_bytes
        logger.debug(
            f'{self.clock.cycle}: MEM_WRITE: kamlet{self.kamlet_coords} '
            f'addr=0x{address:08x} memory_loc=0x{index:x} data={data.hex()}'
        )
        self.lines[index] = data

    def read_cache_line(self, index):
        assert index < self.params.kamlet_memory_bytes//self.params.cache_line_bytes
        address = index * self.params.cache_line_bytes
        if index not in self.lines:
            data = bytes(random.getrandbits(8) for _ in range(self.params.cache_line_bytes))
            logger.debug(
                f'{self.clock.cycle}: MEM_READ: kamlet{self.kamlet_coords} '
                f'addr=0x{address:08x} index={index} data={data.hex()} (UNINITIALIZED - random)'
            )
        else:
            data = self.lines[index]
            logger.debug(
                f'{self.clock.cycle}: MEM_READ: kamlet{self.kamlet_coords} '
                f'addr=0x{address:08x} index={index} data={data.hex()}'
            )
        return data

    def find_gathering_slot(self, ident: int) -> Optional[int]:
        """Find a gathering slot for this ident, or return None if not found."""
        for i, slot in enumerate(self.gathering_slots):
            if slot is not None and slot.ident == ident:
                return i
        return None

    def allocate_gathering_slot(self, ident: int) -> Optional[int]:
        """Allocate a new gathering slot for this ident, or return None if all slots full."""
        for i, slot in enumerate(self.gathering_slots):
            if slot is None:
                self.gathering_slots[i] = GatheringSlot(
                    ident=ident,
                    packets=[None] * self.params.j_in_k,
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
        for queue in self.receive_write_line_queues:
            queue.update()
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
                    else:
                        assert not isinstance(word, Header)
                        assert header
                    packet.append(word)
                    header.length -= 1
                    if header.length == 0:
                        # Record message received for all cache messages
                        dst_x, dst_y = self.coords[index]
                        self.monitor.record_message_received_by_header(packet[0], dst_x, dst_y)

                        if packet[0].message_type == MessageType.READ_LINE:
                            while not self.receive_read_line_queue.can_append():
                                await self.clock.next_cycle
                            self.receive_read_line_queue.append(packet)
                        elif packet[0].message_type == MessageType.WRITE_LINE:
                            j_x = packet[0].source_x % self.params.j_cols
                            j_y = packet[0].source_y % self.params.j_rows
                            j_index = j_y * self.params.j_cols + j_x
                            while not self.receive_write_line_queues[j_index].can_append():
                                await self.clock.next_cycle
                            self.receive_write_line_queues[j_index].append(packet)
                        elif packet[0].message_type == MessageType.WRITE_LINE_READ_LINE:
                            j_x = packet[0].source_x % self.params.j_cols
                            j_y = packet[0].source_y % self.params.j_rows
                            j_index = j_y * self.params.j_cols + j_x
                            ident = packet[0].ident

                            # Find or allocate a gathering slot for this ident
                            slot_index = self.find_gathering_slot(ident)
                            if slot_index is None:
                                slot_index = self.allocate_gathering_slot(ident)
                            if slot_index is None:
                                # No slots available - send DROP
                                logger.debug(
                                    f'{self.clock.cycle}: [MEMLET] DROP WRITE_LINE_READ_LINE '
                                    f'ident={ident} j_index={j_index} - no gathering slots'
                                )
                                cache_request_span_id = self.monitor.get_cache_request_span_id(
                                    self.kamlet_coords[0], self.kamlet_coords[1], cache_slot)
                                self.monitor.record_message_sent(
                                    cache_request_span_id, MessageType.WRITE_LINE_READ_LINE_DROP.name,
                                    ident=ident, tag=cache_slot,
                                    src_x=dst_x, src_y=dst_y,
                                    dst_x=src_x, dst_y=src_y)

                                drop_header = IdentHeader(
                                    target_x=src_x,
                                    target_y=src_y,
                                    source_x=dst_x,
                                    source_y=dst_y,
                                    message_type=MessageType.WRITE_LINE_READ_LINE_DROP,
                                    length=1,
                                    send_type=SendType.SINGLE,
                                    ident=ident,
                                )
                                channel = CHANNEL_MAPPING[MessageType.WRITE_LINE_READ_LINE_DROP]
                                await self.send_packet(index, channel, [drop_header])
                            else:
                                slot = self.gathering_slots[slot_index]
                                slot.add_packet(j_index, packet)
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

    async def handle_write_line_packets(self):
        """
        We receive a write line packet from each jamlet in our kamlet.
        Once they are all received this function is called.
        The memory is updated and a response is sent to the kamlet.
        """
        while True:
            await self.clock.next_cycle
            if all(self.receive_write_line_queues):
                packets = [queue.popleft() for queue in self.receive_write_line_queues]
                # We'll take a word from each packet and put them in the memory
                n_words = packets[0][0].length-2
                ident = packets[0][0].ident
                address = packets[0][1]
                assert address % self.params.cache_line_bytes == 0
                index = address//self.params.cache_line_bytes
                line = []
                for word_index in range(n_words):
                    for j_index in range(self.params.j_in_k):
                        line.append(packets[j_index][word_index+2])
                data = b''.join(line)
                self.write_cache_line(index, data)
                # Send a response back to the kamlet telling it the
                # write was done.
                channel = CHANNEL_MAPPING[MessageType.WRITE_LINE_RESP]
                header = IdentHeader(
                    target_x=self.kamlet_coords[0],
                    target_y=self.kamlet_coords[1],
                    source_x=self.routers[WRITE_LINE_RESPONSE_R_INDEX][channel].x,
                    source_y=self.routers[WRITE_LINE_RESPONSE_R_INDEX][channel].y,
                    message_type=MessageType.WRITE_LINE_RESP,
                    length=1,
                    send_type=SendType.SINGLE,
                    ident=ident,
                    )
                packet = [header]
                # Only reponding from one router
                while not self.send_write_line_response_queue.can_append():
                    await self.clock.next_cycle
                self.send_write_line_response_queue.append(packet)
            else:
                await self.clock.next_cycle

    async def handle_read_line_packets(self):
        while True:
            if self.receive_read_line_queue:
                packet = self.receive_read_line_queue.popleft()
                address = packet[1]
                ident = packet[0].ident
                sram_address = packet[0].address
                cache_slot = sram_address * self.params.j_in_k // self.params.cache_line_bytes
                assert address % self.params.cache_line_bytes == 0
                index = address//self.params.cache_line_bytes
                wb = self.params.word_bytes
                logger.debug(f'handle_read_line_packet: ident={ident} address={hex(address)}')

                cache_request_span_id = self.monitor.get_cache_request_span_id(
                    self.kamlet_coords[0], self.kamlet_coords[1], cache_slot)

                cache_line = self.read_cache_line(index)
                packet_payloads = [[] for i in range(self.params.j_in_k)]
                for word_index in range(len(cache_line)//wb):
                    word = cache_line[word_index*wb: (word_index+1)*wb]
                    packet_payloads[word_index % self.params.j_in_k].append(word)
                # Send a message back to each jamlet.
                resp_packets = [[] for i in range(self.n_routers)]
                for j_in_k_index, payload in enumerate(packet_payloads):
                    router_index = j_in_k_to_m_router(self.params, j_in_k_index)
                    target_x, target_y = self.jamlet_coords[j_in_k_index]
                    channel = CHANNEL_MAPPING[MessageType.READ_LINE_RESP]
                    source_x = self.routers[router_index][channel].x
                    source_y = self.routers[router_index][channel].y
                    resp_header = AddressHeader(
                        target_x=target_x,
                        target_y=target_y,
                        source_x=source_x,
                        source_y=source_y,
                        message_type=MessageType.READ_LINE_RESP,
                        length=1 + len(payload),
                        send_type=SendType.SINGLE,
                        address=packet[0].address,
                        ident=ident,
                        )
                    resp_packet = [resp_header] + payload
                    resp_packets[router_index].append(resp_packet)
                while True:
                    await self.clock.next_cycle
                    while not all(queue.can_append() for queue in self.send_read_line_response_queues):
                        await self.clock.next_cycle
                    for router_index in range(len(self.routers)):
                        if resp_packets[router_index]:
                            resp_packet = resp_packets[router_index].pop(0)
                            self.send_read_line_response_queues[router_index].append(resp_packet)
                            h = resp_packet[0]
                            self.monitor.record_message_sent(
                                cache_request_span_id, MessageType.READ_LINE_RESP.name,
                                ident=ident, tag=cache_slot,
                                src_x=h.source_x, src_y=h.source_y,
                                dst_x=h.target_x, dst_y=h.target_y)
                    if all(len(packets) == 0 for packets in resp_packets):
                        break
            else:
                await self.clock.next_cycle

    async def handle_write_line_read_line_packets(self):
        """
        Process complete gathering slots. A slot is complete when all jamlets
        have sent their WRITE_LINE_READ_LINE packets for the same ident.
        """
        while True:
            await self.clock.next_cycle
            if self.complete_gathering_queue:
                slot_index = self.complete_gathering_queue.popleft()
                slot = self.gathering_slots[slot_index]
                packets = slot.packets
                # We'll take a word from each packet and put them in the memory
                n_words = packets[0][0].length-3
                ident = packets[0][0].ident
                sram_address = packets[0][0].address
                write_address = packets[0][1]
                assert write_address % self.params.cache_line_bytes == 0
                write_index = write_address//self.params.cache_line_bytes
                read_address = packets[0][2]
                assert read_address % self.params.cache_line_bytes == 0
                read_index = read_address//self.params.cache_line_bytes
                # Verify all jamlets sent packets for the same addresses
                for j_index in range(self.params.j_in_k):
                    j_write_addr = packets[j_index][1]
                    j_read_addr = packets[j_index][2]
                    assert j_write_addr == write_address, \
                        f'j_index={j_index} write_addr=0x{j_write_addr:x} != expected 0x{write_address:x}'
                    assert j_read_addr == read_address, \
                        f'j_index={j_index} read_addr=0x{j_read_addr:x} != expected 0x{read_address:x}'

                # Compute cache slot from sram_address
                cache_slot = sram_address * self.params.j_in_k // self.params.cache_line_bytes

                line = []
                for word_index in range(n_words):
                    for j_index in range(self.params.j_in_k):
                        line.append(packets[j_index][word_index+3])
                data = b''.join(line)
                for j_index in range(self.params.j_in_k):
                    j_words = [packets[j_index][word_index+3].hex() for word_index in range(n_words)]
                    logger.debug(f'{self.clock.cycle}: [MEMLET_RECV] kamlet={self.kamlet_coords} j_index={j_index} write_addr=0x{write_address:x} words={j_words}')
                logger.debug(f'{self.clock.cycle}: [MEMLET_WRITE] kamlet={self.kamlet_coords} write_index={write_index} write_addr=0x{write_address:x} data={data.hex()}')
                self.write_cache_line(write_index, data)

                wb = self.params.word_bytes
                logger.debug(f'handle_write_line_read_line_packet: ident={ident} write_address={hex(write_address)} read_address={hex(read_address)}')
                read_cache_line = self.read_cache_line(read_index)
                logger.debug(f'[MEMLET_READ] kamlet={self.coords} read_index={read_index} read_addr=0x{read_address:x} data={read_cache_line.hex()}')
                packet_payloads = [[] for i in range(self.params.j_in_k)]
                for word_index in range(len(read_cache_line)//wb):
                    word = read_cache_line[word_index*wb: (word_index+1)*wb]
                    packet_payloads[word_index % self.params.j_in_k].append(word)

                # Send a message back to each jamlet.
                cache_request_span_id = self.monitor.get_cache_request_span_id(
                    self.kamlet_coords[0], self.kamlet_coords[1], cache_slot)

                resp_packets = [[] for i in range(self.n_routers)]
                for j_in_k_index, payload in enumerate(packet_payloads):
                    router_index = j_in_k_to_m_router(self.params, j_in_k_index)
                    target_x, target_y = self.jamlet_coords[j_in_k_index]
                    channel = CHANNEL_MAPPING[MessageType.WRITE_LINE_READ_LINE_RESP]
                    resp_header = AddressHeader(
                        target_x=target_x,
                        target_y=target_y,
                        source_x=self.routers[router_index][channel].x,
                        source_y=self.routers[router_index][channel].y,
                        message_type=MessageType.WRITE_LINE_READ_LINE_RESP,
                        length=1 + len(payload),
                        send_type=SendType.SINGLE,
                        address=sram_address,
                        ident=ident,
                        )
                    logger.debug(f'[MEMLET_RESP] send WRITE_LINE_READ_LINE_RESP ident={ident} payload={payload}')
                    resp_packet = [resp_header] + payload
                    resp_packets[router_index].append(resp_packet)
                while True:
                    await self.clock.next_cycle
                    while not all(queue.can_append() for queue in self.send_write_line_read_line_response_queues):
                        await self.clock.next_cycle
                    for router_index in range(len(self.routers)):
                        if resp_packets[router_index]:
                            resp_packet = resp_packets[router_index].pop(0)
                            self.send_write_line_read_line_response_queues[router_index].append(resp_packet)
                            h = resp_packet[0]
                            self.monitor.record_message_sent(
                                cache_request_span_id, MessageType.WRITE_LINE_READ_LINE_RESP.name,
                                ident=ident, tag=cache_slot,
                                src_x=h.source_x, src_y=h.source_y,
                                dst_x=h.target_x, dst_y=h.target_y)
                    if all(len(packets) == 0 for packets in resp_packets):
                        break
                # Free the gathering slot now that we're done
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
        self.clock.create_task(self.handle_write_line_packets())
        self.clock.create_task(self.handle_write_line_read_line_packets())
        while True:
            await self.clock.next_cycle
