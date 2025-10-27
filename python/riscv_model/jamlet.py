import logging

from addresses import KMAddr, JSAddr
from params import LamletParams
from message import Direction, Header, SendType, MessageType
from utils import Queue
from router import Router
from kinstructions import KInstr
import memlet


logger = logging.getLogger(__name__)


def jamlet_coords_to_frontend_coords(params, x, y):
    return (0, -1)


class Jamlet:

    def __init__(self, clock, params: LamletParams, x: int, y: int):
        self.clock = clock
        self.params = params
        self.x = x
        self.y = y

        self.mem_x, self.mem_y = memlet.jamlet_coords_to_m_router_coords(params, x, y)
        self.front_x, self.front_y = jamlet_coords_to_frontend_coords(params, x, y)

        rf_slice_bytes = (params.maxvl_bytes // params.k_cols // params.k_rows //
                          params.j_cols // params.j_rows * params.n_vregs)
        self.rf_slice = bytearray([0] * rf_slice_bytes)
        self.sram = bytearray([0] * params.jamlet_sram_bytes)
        self.receive_buffer = [None] * params.receive_buffer_depth
        self.router = Router(clock=clock, params=params, x=x, y=y)
        # This is just a queue to hand them up to kamlet
        self._instruction_buffer = Queue(2)

        self.send_queues = {
            MessageType.READ_BYTES_FROM_SRAM_RESP: Queue(2),
            MessageType.WRITE_LINE: Queue(2),
            MessageType.READ_LINE: Queue(2),
            MessageType.READ_LINE_NOTIFY: Queue(2),
            }

    async def _send_packet(self, packet):
        assert isinstance(packet[0], Header)
        assert len(packet) == packet[0].length
        # This is only called from _send_packets
        queue = self.router._input_buffers[Direction.H]
        while True:
            if queue.can_append():
                word = packet.pop(0)
                queue.append(word)
                if not packet:
                    await self.clock.next_cycle
                    break
            await self.clock.next_cycle

    async def _send_packets(self):
        """
        Iterate through the send queues and send packets.
        """
        something_in_a_queue = False
        while True:
            for send_queue in self.send_queues.values():
                if send_queue:
                    await self._send_packet(send_queue.popleft())
                something_in_a_queue = any(send_queue for send_queue in self.send_queues.values())
                if not something_in_a_queue:
                    await self.clock.next_cycle

    def has_instruction(self):
        bool(self._instruction_buffer)

    async def read_bytes_from_sram(self, instr: 'ReadBytesFromSRAM', size: int):
        logger.debug(f'jamlet ({self.x}, {self.y}) reading byte from sram')
        # The access must be all inside a word
        assert instr.j_saddr.addr//self.params.word_bytes == (instr.j_saddr.addr+size-1)//self.params.word_bytes
        value = bytes(self.sram[instr.j_saddr.addr: instr.j_saddr.addr+size])
        header = Header(
            message_type=MessageType.READ_BYTES_FROM_SRAM_RESP,
            send_type=SendType.SINGLE,
            value=value,
            target_x=instr.target_x,
            target_y=instr.target_y,
            source_x=self.x,
            source_y=self.y,
            address=instr.j_saddr,
            length=1,
            )
        packet = [header]
        logger.debug(f'jamlet ({self.x}, {self.y}) sending response')
        send_queue = self.send_queues[header.message_type]
        while not send_queue.can_append():
            await self.clock.next_cycle
        logger.debug(f'jamlet ({self.x}, {self.y}) appending a packet')
        send_queue.append(packet)
        logger.debug(f'jamlet ({self.x}, {self.y}) sent response')

    async def write_line(self, k_maddr: KMAddr,  j_saddr: JSAddr, n_cache_lines: int):
        """
        address: A word address in the local sram.
        """
        n_words = self.params.cache_line_bytes // self.params.j_in_k // self.params.word_bytes * n_cache_lines
        address_in_sram = j_saddr.addr
        address_in_memory = k_maddr.addr
        # This is the address in the whole kamlet memory.  Doesn't take into account our
        # jamlet offset but the receive can worry about that.
        logger.debug(f'jamlet ({self.x}, {self.y}) sending a write line packet')
        packet = []
        header = Header(
            message_type=MessageType.WRITE_LINE,
            send_type=SendType.SINGLE,
            target_x=self.mem_x,
            target_y=self.mem_y,
            source_x=self.x,
            source_y=self.y,
            address=None,
            length=n_words+2,
            )
        packet = [header, address_in_memory]
        wb = self.params.word_bytes
        for index in range(n_words):
            word = self.sram[address_in_sram + index * wb: address_in_sram + (index+1) * wb]
            packet.append(word)
        as_int = []
        for word in packet[2:]:
            as_int += [int(x) for x in word]
        logger.warning(f'{self.clock.cycle}: ({self.x}, {self.y}): write_line: {hex(k_maddr.addr)} Sent data {as_int}')
        send_queue = self.send_queues[header.message_type]
        while not send_queue.can_append():
            await self.clock.next_cycle
        send_queue.append(packet)

    async def read_line(self, k_maddr: KMAddr,  j_saddr: JSAddr, n_cache_lines: int):
        """
        address: A word address in the local sram.
        """
        #logger.warning(f'{self.clock.cycle}: ({self.x}, {self.y}): read_line {hex(k_maddr.addr)}')
        n_words = (self.params.cache_line_bytes // self.params.j_in_k //
                   self.params.word_bytes * n_cache_lines)
        address_in_sram = j_saddr.addr
        address_in_memory = k_maddr.addr
        # This is the address in the whole kamlet memory.  Doesn't take into account our
        # jamlet offset but the receive can worry about that.
        logger.debug(f'jamlet ({self.x}, {self.y}) sending a write line packet')
        packet = []
        header = Header(
            message_type=MessageType.READ_LINE, #4
            send_type=SendType.SINGLE,          #1
            target_x=self.mem_x,                #8
            target_y=self.mem_y,                #8
            source_x=self.x,                    #8
            source_y=self.y,                    #8
            address=address_in_sram,            #12
            words_requested=n_words,            #5
            length=2,                           #5  (total 59 bits just ok)
            )
        packet = [header, address_in_memory]
        send_queue = self.send_queues[header.message_type]
        while not send_queue.can_append():
            await self.clock.next_cycle
        send_queue.append(packet)

    def update(self):
        self.router.update()
        self._instruction_buffer.update()
        for queue in self.send_queues.values():
            queue.update()

    async def process_read_line_response(self, packet):
        header = packet[0]
        m_address = packet[1]
        data = packet[2:]
        s_address = header.address
        wb = self.params.word_bytes
        assert s_address % wb == 0
        for index, word in enumerate(data):
            self.sram[s_address + index * wb: s_address + (index+1) * wb] = word
        as_int = []
        for word in data:
            as_int += [int(x) for x in word]
        logger.warning(f'{self.clock.cycle}: ({self.x}, {self.y}): {hex(m_address)} read_line: Wrote data {as_int}')
        # Send a reply to the scalar proc
        response_header = Header(
            message_type=MessageType.READ_LINE_NOTIFY,
            send_type=SendType.SINGLE,
            target_x=self.front_x,
            target_y=self.front_y,
            source_x=self.x,
            source_y=self.y,
            address=header.address,
            length=2,
            )
        packet = [response_header, m_address]
        send_queue = self.send_queues[response_header.message_type]
        while not send_queue.can_append():
            await self.clock.next_cycle
        send_queue.append(packet)

    async def run(self):
        self.clock.create_task(self.router.run())
        self.clock.create_task(self._send_packets())
        receive_header = None
        packet = []
        while True:
            await self.clock.next_cycle
            queue = self.router._output_buffers[Direction.H]
            if queue:
                if not receive_header:
                    word = queue.popleft()
                    assert isinstance(word, Header)
                    receive_header = word.copy()
                    receive_header.length -= 1
                    packet.append(word)
                else:
                    assert not isinstance(queue.head(), Header)
                    if receive_header.message_type == MessageType.INSTRUCTIONS:
                        assert isinstance(queue.head(), KInstr)
                        word = queue.popleft()
                        self._instruction_buffer.append(word)
                        receive_header.length -= 1
                        packet.append(word)
                    elif receive_header.message_type == MessageType.SEND:
                        word = queue.popleft()
                        rb_addr = receive_header.address % self.params.receive_buffer_depth
                        self.receive_buffer[rb_addr] = word
                        receive_header.length -= 1
                        receive_header.address += 1
                        packet.append(word)
                    elif receive_header.message_type == MessageType.WRITE_LINE:
                        raise Exception('A jamlet should not receive a WRITE_LINE message')
                    elif receive_header.message_type == MessageType.READ_LINE_RESP:
                        word = queue.popleft()
                        receive_header.length -= 1
                        packet.append(word)
                        if receive_header.length == 0:
                            await self.process_read_line_response(packet)
                    else:
                        raise NotImplementedError
                    if receive_header.length == 0:
                        receive_header = None
                        packet = []

    SEND = 0
    INSTRUCTIONS = 1


