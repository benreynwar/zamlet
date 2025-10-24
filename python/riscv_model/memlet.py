import logging
from typing import List, Tuple
from collections import deque

from params import LamletParams
from runner import Clock
from router import Router, Direction, Header
from utils import Queue
from message import MessageType, SendType


logger = logging.getLogger(__name__)


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


def memlet_coords_to_index(params: LamletParams, x: int, y: int) -> (int, int):
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


def m_router_coords(params: LamletParams, m_index: int, router_index: int) -> (int, int):
    m_cols, n_routers_in_memlet = get_cols_routers(params)
    if m_index % params.k_cols < params.k_cols//2:
        # We're on the west side
        m_y = m_index // m_cols * n_routers_in_memlet + router_index
        m_x = -m_cols + (m_index % m_cols)
    else:
        rev_index = params.k_cols - 1  - m_index
        m_y = rev_index // m_cols * n_routers_in_memlet + router_index
        m_x = params.j_cols * params.k_cols + m_cols - 1 - (m_index % m_cols)
    return (m_x, m_y)


def jamlet_coords_to_m_router_coords(params: LamletParams, j_x: int, j_y: int) -> (int, int):
    k_x  = j_x // params.j_cols
    k_y  = j_y // params.j_rows
    k_index = k_y * params.k_cols + k_x
    j_in_k_x = j_x % params.j_cols
    j_in_k_y = j_y % params.j_rows
    j_in_k_index = j_in_k_y * params.j_cols + j_in_k_x
    router_index = j_in_k_to_m_router(params, j_in_k_index)
    m_index = k_index
    r_x, r_y = m_router_coords(params, m_index, router_index)
    return (r_x, r_y)


class Memlet:

    def __init__(self, clock: Clock, params: LamletParams, coords: List[Tuple[int, int]]):
        self.clock = clock
        self.params = params
        self.coords = coords
        self.routers = [Router(clock, params, x, y) for x, y in coords]
        self.lines = {}
        self.n_lines = params.kamlet_memory_bytes // params.cache_line_bytes
        self.m_cols, self.n_routers = get_cols_routers(self.params)
        # Make send and receive queues for each router
        self.receive_queues = [Queue(2) for _ in coords]
        self.send_queues = [Queue(2) for _ in coords]

    def write_cache_line(self, index, data):
        assert index < self.n_lines
        self.lines[index] = data

    def read_cache_line(self, index):
        return self.lines[index]

    def update(self):
        for router in self.routers:
            router.update()
        for queue in self.receive_queues:
            queue.update()
        for queue in self.send_queues:
            queue.update()

    async def receive_packets(self, index):
        assert index < len(self.coords)
        queue = self.routers[index]._output_buffers[Direction.H]
        header = None
        packet = []
        while True:
            await self.clock.next_cycle
            r = self.routers[index]
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
                    self.receive_queues[index].append(packet)
                    header = None
                    packet = []

    async def send_packets(self, index):
        assert index < len(self.coords)
        queue = self.routers[index]._input_buffers[Direction.H]
        await self.clock.next_cycle
        while True:
            if self.send_queues[index]:
                packet = self.send_queues[index].popleft()
                for word in packet:
                    while True:
                        if queue.can_append():
                            queue.append(word)
                            await self.clock.next_cycle
                            break
                        await self.clock.next_cycle
            else:
                await self.clock.next_cycle

    def handle_write_line_packets(self, packets):
        # We'll take a word from each packet and put them in the memory
        n_words = packets[0][0].length-2
        address = packets[0][1]
        assert address % self.params.cache_line_bytes == 0
        index = address//self.params.cache_line_bytes
        line = []
        for word_index in range(n_words):
            for j_index in range(self.params.j_in_k):
                line.append(packets[j_index][word_index+2])
        data = b''.join(line)
        self.write_cache_line(index, data)
        # Send a message back to the scalar processor that the write was done.
        header = Header(
            target_x=0,
            target_y=-1,
            source_x=self.routers[0].x,
            source_y=self.routers[0].y,
            message_type=MessageType.WRITE_LINE_NOTIFY,
            length=2,
            send_type=SendType.SINGLE,
            )
        packet = [header, address]
        # Only reponding from one router
        # This is a list of lists
        # A list of packets to send from each router.
        return [[packet]] + [[] for _ in range(self.n_routers - 1)]

    def handle_read_line_packets(self, packets):
        # We'll take a word from each packet and put them in the memory
        address = packets[0][1]
        assert address % self.params.cache_line_bytes == 0
        index = address//self.params.cache_line_bytes
        wb = self.params.word_bytes
        cache_line = self.read_cache_line(index)
        packet_payloads = [[] for i in range(self.params.j_in_k)]
        for word_index in range(len(cache_line)//wb):
            word = cache_line[word_index*wb: (word_index+1)*wb]
            packet_payloads[word_index % self.params.j_in_k].append(word)
        # Send a message back to each jamlet.
        resp_packets = [[] for i in range(self.n_routers)]
        for packet, payload in zip(packets, packet_payloads):
            _, router_index = memlet_coords_to_index(self.params, packet[0].target_x, packet[0].target_y)
            resp_header = Header(
                target_x=packet[0].source_x,
                target_y=packet[0].source_y,
                source_x=packet[0].target_x,
                source_y=packet[0].target_y,
                message_type=MessageType.READ_LINE_RESP,
                length=2 + len(payload),
                send_type=SendType.SINGLE,
                address=packet[0].address,
                )
            resp_packet = [resp_header, address] + payload
            resp_packets[router_index].append(resp_packet)
        return resp_packets


    async def handle_packets(self):
        """
        We grab packets.  If we get a packet from each jamlet of the same
        type we combine them and perform the action.
        """
        actions_in_progress = {}
        response_packets = [deque() for _ in range(self.n_routers)]
        while True:
            await self.clock.next_cycle
            for index in range(len(self.coords)):
                if self.receive_queues[index]:
                    packet = self.receive_queues[index].popleft()
                    if packet[0].message_type == MessageType.WRITE_LINE:
                        label = (packet[0].message_type, packet[1])
                    elif packet[0].message_type == MessageType.READ_LINE:
                        label = (packet[0].message_type, packet[1])
                    else:
                        raise NotImplementedError
                    source_x = packet[0].source_x
                    source_y = packet[0].source_y
                    j_in_k_x = source_x % self.params.j_cols
                    j_in_k_y = source_y % self.params.j_rows
                    j_index = j_in_k_y * self.params.j_cols + j_in_k_x
                    if label not in actions_in_progress:
                        actions_in_progress[label] = [None] * self.params.j_in_k
                    actions_in_progress[label][j_index] = packet
                    if None not in actions_in_progress[label]:
                        packets = actions_in_progress[label]
                        # We have received a packet from each jamlet.
                        if packet[0].message_type == MessageType.WRITE_LINE:
                            new_packets = self.handle_write_line_packets(packets)
                            for router_index, packets in enumerate(new_packets):
                                response_packets[router_index] += packets
                        elif packet[0].message_type == MessageType.READ_LINE:
                            new_packets = self.handle_read_line_packets(packets)
                            for router_index, packets in enumerate(new_packets):
                                response_packets[router_index] += packets
                        else:
                            raise NotImplementedError
                        del actions_in_progress[label]
            for router_index, packets in enumerate(response_packets):
                if packets:
                    packet = packets.popleft()
                    self.send_queues[router_index].append(packet)

    async def run(self):
        for router in self.routers:
            self.clock.create_task(router.run())
        for index in range(len(self.coords)):
            self.clock.create_task(self.receive_packets(index))
            self.clock.create_task(self.send_packets(index))
        self.clock.create_task(self.handle_packets())
        while True:
            await self.clock.next_cycle
