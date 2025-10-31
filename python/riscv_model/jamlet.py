import logging

from params import LamletParams
from message import Direction, Header, SendType, MessageType
from utils import Queue
from router import Router
import  kinstructions
import memlet
from response_tracker import ResponseTracker


logger = logging.getLogger(__name__)


def jamlet_coords_to_frontend_coords(params, x, y):
    return (0, -1)


class Jamlet:
    """
    A single lane of the processor.
    """

    def __init__(self, clock, params: LamletParams, x: int, y: int, response_tracker: ResponseTracker):
        self.clock = clock
        self.params = params
        self.x = x
        self.y = y

        # The coords of the memlet router that this jamlet talks to.
        self.mem_x, self.mem_y = memlet.jamlet_coords_to_m_router_coords(params, x, y)

        # The coords of the frontend that this jamlet talks to.
        self.front_x, self.front_y = jamlet_coords_to_frontend_coords(params, x, y)

        # The register file in this jamlet.  It's referred to as a register file
        # slice since it's part of a logically larger register file.
        rf_slice_bytes = (params.maxvl_bytes // params.k_cols // params.k_rows //
                          params.j_cols // params.j_rows * params.n_vregs)
        self.rf_slice = bytearray([0] * rf_slice_bytes)

        # The jamlet contains some SRAM. Currently this is used as cache.
        self.sram = bytearray([0] * params.jamlet_sram_bytes)

        # The receive buffer is used for receiving messages from SEND messages.
        # It's used to reorder the messages so that we get deterministic ordering.
        self.receive_buffer = [None] * params.receive_buffer_depth

        self.router = Router(clock=clock, params=params, x=x, y=y)

        # This is just a queue to hand instructions up to kamlet.
        self._instruction_buffer = Queue(2)

        # We have a queue for each type of message that we can send.
        # This is so that we can add multiple messages every cycle
        # without worrying out non-deterministic order of the async
        # functions.
        self.send_queues = {
            MessageType.READ_BYTES_RESP: Queue(2),
            MessageType.WRITE_LINE: Queue(2),
            MessageType.READ_LINE: Queue(2),
            }

        # Debugging logic. Shouldn't need in future.
        self.expecting_read_line_idents = set()

        self.response_tracker = response_tracker


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

    async def handle_read_bytes_instr(self, instr: 'ReadBytes', sram_address: int):
        """
        Process a read bytes from SRAM instruction.
        This blocks until the reponse message can be sent.
        """
        logger.debug(f'jamlet ({self.x}, {self.y}) reading byte from sram {hex(sram_address)}')
        # The access must be all inside a word
        assert instr.k_maddr.addr//self.params.word_bytes == (instr.k_maddr.addr+instr.size-1)//self.params.word_bytes
        value = bytes(self.sram[sram_address: sram_address+instr.size])
        header = Header(
            message_type=MessageType.READ_BYTES_RESP,
            send_type=SendType.SINGLE,
            value=value,
            target_x=self.front_x,
            target_y=self.front_y,
            source_x=self.x,
            source_y=self.y,
            address=instr.k_maddr,
            length=1,
            ident=instr.ident,
            )
        packet = [header]
        send_queue = self.send_queues[header.message_type]
        while not send_queue.can_append():
            await self.clock.next_cycle
        logger.debug(f'jamlet ({self.x}, {self.y}) appending a packet')
        send_queue.append(packet)
        logger.debug(f'jamlet ({self.x}, {self.y}) sent response')

    async def write_cache_line(self, cache_slot: int, address_in_memory: int, response_ident: int):
        """
        Writes this jamlets share of a cache line to memory.
        """
        address_in_sram = cache_slot * self.params.cache_line_bytes // self.params.j_in_k
        n_words = self.params.cache_line_bytes // self.params.j_in_k // self.params.word_bytes
        header = Header(
            message_type=MessageType.WRITE_LINE,
            send_type=SendType.SINGLE,
            target_x=self.mem_x,
            target_y=self.mem_y,
            source_x=self.x,
            source_y=self.y,
            address=None,
            length=n_words+2,
            ident=response_ident,
            )
        packet = [header, address_in_memory]
        wb = self.params.word_bytes
        for index in range(n_words):
            word = self.sram[address_in_sram + index * wb: address_in_sram + (index+1) * wb]
            packet.append(word)
        as_int = []
        for word in packet[2:]:
            #as_int += [int(x) for x in word]
            as_int += [int.from_bytes(word[i*4:(i+1)*4], byteorder='little') for i in range(len(word)//4)]
        send_queue = self.send_queues[header.message_type]
        while not send_queue.can_append():
            await self.clock.next_cycle
        send_queue.append(packet)

    async def read_cache_line_resolve(self, packet):
        """
        The kamlet sends a read line packet to the memory.
        Each jamlet receives a response packet and uses this function to 
        handle it.
        """
        logger.debug('jamlet: read_cache_line_resolve')
        # Wait for the response packet from the memory
        header = packet[0]
        data = packet[1:]
        s_address = header.address
        assert len(data) == self.params.vlines_in_cache_line
        wb = self.params.word_bytes
        assert s_address % wb == 0
        for index, word in enumerate(data):
            self.sram[s_address + index * wb: s_address + (index+1) * wb] = word
        as_int = []
        for word in data:
            as_int += [int(x) for x in word]

    def update(self):
        self.router.update()
        self._instruction_buffer.update()
        for queue in self.send_queues.values():
            queue.update()

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
                        assert isinstance(queue.head(), kinstructions.KInstr)
                        if self._instruction_buffer.can_append():
                            word = queue.popleft()
                            self._instruction_buffer.append(word)
                            receive_header.length -= 1
                            packet.append(word)
                        assert receive_header.ident is None
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
                    else:
                        raise NotImplementedError
                if receive_header.length == 0:
                    if receive_header.message_type in (MessageType.READ_LINE_RESP, MessageType.WRITE_LINE_RESP):
                        self.response_tracker.check_packet(packet)
                    receive_header = None
                    packet = []
            else:
                #logger.debug(f'{self.clock.cycle}: jamlet({self.x}, {self.y}): No input queue')
                pass

    SEND = 0
    INSTRUCTIONS = 1


