import logging
from dataclasses import dataclass
from enum import Enum

from addresses import CacheState, KMAddr, JSAddr
from params import LamletParams
from message import Direction, directions, Header, SendType, MessageType
from utils import Queue


logger = logging.getLogger(__name__)


@dataclass
class Connection:
    remaining: int
    dests: set(Direction)
    unconsumed: set(Direction)
    age: int


class Router:

    def __init__(self, clock, x: int, y: int, params: LamletParams):
        self.clock = clock
        self.x = x
        self.y = y
        self.params = params

        # Local State
        ibl = self.params.router_input_buffer_length
        obl = self.params.router_output_buffer_length
        self._input_buffers = {Direction.N: Queue(ibl), Direction.S: Queue(ibl), Direction.E: Queue(ibl), Direction.W: Queue(ibl), Direction.H: Queue(ibl)}
        self._output_buffers = {Direction.N: Queue(obl), Direction.S: Queue(obl), Direction.E: Queue(obl), Direction.W: Queue(obl), Direction.H: Queue(obl)}
        self._input_connections = {}
        self._output_connections = {}
        self._output_headers = {}
        self._priority = list(directions)

    def get_output_directions(self, header):
        new_header = header.copy()
        new_header.target_x = self.x
        if header.send_type == SendType.SINGLE:
            if header.target_x > self.x:
                directions = [(header, Direction.E)]
            elif header.target_x < self.x:
                directions = [(header, Direction.W)]
            elif header.target_y > self.y:
                directions = [(header, Direction.S)]
            elif header.target_y < self.y:
                directions = [(header, Direction.N)]
            else:
                directions = [(header, Direction.H)]
        elif header.send_type == SendType.BROADCAST:
            if header.target_x > self.x:
                if header.target_y > self.y:
                    target_x = self.x
                    directions = [(header, Direction.H), (header, Direction.E), (new_header, Direction.S)]
                elif header.target_y < self.y:
                    target_x = self.x
                    directions = [(header, Direction.H), (header, Direction.E), (new_header, Direction.N)]
                else:
                    directions = [(header, Direction.H), (header, Direction.E)]
            elif header.target_x < self.x:
                if header.target_y > self.y:
                    target_x = self.x
                    directions = [(header, Direction.H), (header, Direction.W), (new_header, Direction.S)]
                elif header.target_y < self.y:
                    target_x = self.x
                    directions = [(header, Direction.H), (header, Direction.W), (new_header, Direction.N)]
                else:
                    directions = [(header, Direction.H), (header, Direction.W)]
            elif header.target_y > self.y:
                directions = [(header, Direction.H), (header, Direction.S)]
            elif header.target_y < self.y:
                directions = [(header, Direction.H), (header, Direction.N)]
            else:
                directions = [(header, Direction.H)]
        else:
            assert False
        return directions

    def has_input_room(self, direction):
        return len(self._input_buffers[direction]) < self.params.router_input_buffer_length

    def receive(self, direction, word):
        assert self.has_input_room(direction)
        self._input_buffers[direction].append(word)

    def update(self):
        for buffer in self._input_buffers.values():
            buffer.update()
        for buffer in self._output_buffers.values():
            buffer.update()

    async def run(self):
        while True:
            await self.clock.next_cycle
            self._priority = self._priority[1:] + self._priority[0:1]
            #if self._input_buffers[Direction.N]:
            for input_direction in self._priority:
                buffer = self._input_buffers[input_direction]
                if (input_direction not in self._input_connections) and buffer:
                    header = buffer.head()
                    #if not isinstance(header, Header):
                    #    logger.error(f'({self.x}, {self.y}): from {input_direction} we got a non-header')
                    assert isinstance(header, Header)
                    headers_and_output_directions = self.get_output_directions(header)
                    output_dirs = set(x[1] for x in headers_and_output_directions)
                    if all(output_direction not in self._output_connections for output_direction in output_dirs):
                        for new_header, output_direction in headers_and_output_directions:
                            logger.debug(f'{self.clock.cycle}: Make a new connection from {input_direction} to {output_direction} length {header.length} in router ({self.x}, {self.y}) target=({header.target_x}, {header.target_y})')
                            assert output_direction not in self._output_connections
                            self._output_connections[output_direction] = input_direction
                            assert output_direction not in self._output_headers
                            self._output_headers[output_direction] = new_header
                        self._input_connections[input_direction] = Connection(header.length, set(output_dirs), set(output_dirs), 0)

            for output_direction in directions:
                # If there is a connection see if we can send a word
                if (output_direction in self._output_connections) and len(self._output_buffers[output_direction]) < self.params.router_output_buffer_length:
                    input_direction = self._output_connections[output_direction]
                    buffer = self._input_buffers[input_direction]
                    #if input_direction not in self.input_connections:
                    #    logger.error(f'({self.x}, {self.y}): output_dir = {output_direction} input_dir = {input_direction} cannot find input conn')
                    conn = self._input_connections[input_direction]
                    if buffer and (output_direction in conn.unconsumed):
                        word = self._input_buffers[input_direction].head()
                        if output_direction in self._output_headers:
                            # We want to use the replaced header
                            # because we might have updated the target.
                            assert isinstance(word, Header)
                            self._output_buffers[output_direction].append(self._output_headers[output_direction])
                            del self._output_headers[output_direction]
                        else:
                            assert not isinstance(word, Header)
                            self._output_buffers[output_direction].append(word)
                        conn.unconsumed.remove(output_direction)
                        if not conn.unconsumed:
                            # No other outputs are waiting on this word so we
                            # can pop it off the input queue.
                            self._input_buffers[input_direction].popleft()
                            conn.remaining -= 1
                        if conn.remaining == 1 and conn.unconsumed:
                            # There still stuff left but it's not going to our output.
                            del self._output_connections[output_direction]
                        if conn.remaining == 0:
                            del self._output_connections[output_direction]
                            if not conn.unconsumed:
                                logger.debug(f'{self.clock.cycle}: ({self.x}, {self.y}): from {input_direction} closing connection')
                                del self._input_connections[input_direction]
                        if not conn.unconsumed:
                            conn.unconsumed = set(conn.dests)
            for conn in self._input_connections.values():
                conn.age +=1 
                if conn.age > 100:
                    import pdb
                    pdb.set_trace()


class Jamlet:

    def __init__(self, clock, params: LamletParams, x: int, y: int, mem_x: int, mem_y: int):
        self.clock = clock
        self.params = params
        self.x = x
        self.y = y
        self.mem_x = x
        self.mem_y = y

        rf_slice_bytes = params.maxvl_bytes // params.k_cols // params.k_rows // params.j_cols // params.j_rows * params.n_vregs
        self.rf_slice = bytearray([0] * rf_slice_bytes)
        self.sram = bytearray([0] * params.jamlet_sram_bytes)
        self.receive_buffer = [None] * params.receive_buffer_depth
        self.router = Router(clock=clock, x=x, y=y, params=params)
        self.receive_header = None
        # This is just a queue to hand them up to kamlet
        self._instruction_buffer = Queue(2)

    def has_instruction(self):
        bool(self._instruction_buffer)

    async def read_byte_from_sram(self, instr: 'ReadByteFromSRAM'):
        logger.debug(f'jamlet ({self.x}, {self.y}) reading byte from sram')
        value = self.sram[instr.j_saddr.addr]
        header = Header(
            message_type=MessageType.READ_BYTE_FROM_SRAM_RESP,
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
        await self.send_packet(packet)
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
            word = self.sram[(address_in_sram+index) * wb: (address_in_sram+index+1) * wb]
            packet.append(word)
        await self.send_packet(packet)

    async def read_line(self, k_maddr: KMAddr,  j_saddr: JSAddr, n_cache_lines: int):
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
        await self.send_packet(packet)

    async def send_packet(self, packet):
        while True:
            if len(self.router._input_buffers[Direction.H]) < self.params.router_input_buffer_length:
                word = packet.pop(0)
                self.router._input_buffers[Direction.H].append(word)
                if not packet:
                    break
            await self.clock.next_cycle

    def update(self):
        self.router.update()
        self._instruction_buffer.update()

    async def run(self):
        self.clock.create_task(self.router.run())
        while True:
            await self.clock.next_cycle
            queue = self.router._output_buffers[Direction.H]
            if queue:
                logger.info(f'{self.clock.cycle}: ({self.x}, {self.y}): something in input queue')
                if not self.receive_header:
                    assert isinstance(queue.head(), Header)
                    self.receive_header = queue.popleft().copy()
                    self.receive_header.length -= 1
                else:
                    assert not isinstance(queue.head(), Header)
                    if self.receive_header.message_type.INSTRUCTIONS:
                        word = queue.popleft()
                        logger.info(f'{self.clock.cycle}: ({self.x}, {self.y}): Adding to instruction buffer {word}')
                        self._instruction_buffer.append(word)
                        #logger.debug(f'jamlet({self.x}, {self.y}): adding {self._instruction_buffer} to queue')
                        self.receive_header.length -= 1
                    elif self.receive_header.message_type == MessageType.SEND:
                        self.receive_buffer[self.receive_header.address % self.params.receive_buffer_depth] = (
                                queue.popleft())
                        self.receive_header.length -= 1
                        self.receive_header.address += 1
                    else:
                        raise NotImplementedError
                    if self.receive_header.length == 0:
                        self.receive_header = None

    SEND = 0
    INSTRUCTIONS = 1


