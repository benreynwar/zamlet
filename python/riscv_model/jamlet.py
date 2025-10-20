import logging
from collections import deque
from dataclasses import dataclass
from enum import Enum

from addresses import CacheState
from params import Direction, LamletParams, directions, Header, SendType


logger = logging.getLogger(__name__)


@dataclass
class Connection:
    remaining: int
    dests: set(Direction)
    unconsumed: set(Direction)


class Router:

    def __init__(self, x: int, y: int, params: LamletParams):
        self.x = x
        self.y = y
        self.params = params
        self.input_buffers = {Direction.N: deque(), Direction.S: deque(), Direction.E: deque(), Direction.W: deque(), Direction.H: deque()}
        self.output_buffers = {Direction.N: deque(), Direction.S: deque(), Direction.E: deque(), Direction.W: deque(), Direction.H: deque()}
        self.input_connections = {}
        self.output_connections = {}
        self.output_headers = {}
        self.priority = list(directions)

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
        return len(self.input_buffers[direction]) < self.params.router_input_buffer_length

    def receive(self, direction, word):
        assert self.has_input_room(direction)
        self.input_buffers[direction].append(word)

    def step(self):
        self.priority = self.priority[1:] + self.priority[0:1]
        for input_direction in self.priority:
            buffer = self.input_buffers[input_direction]
            if (input_direction not in self.input_connections) and buffer:
                header = buffer[0]
                if not isinstance(header, Header):
                    logger.error(f'({self.x}, {self.y}): from {input_direction} we got a non-header')
                assert isinstance(header, Header)
                headers_and_output_directions = self.get_output_directions(header)
                output_dirs = set(x[1] for x in headers_and_output_directions)
                if all(output_direction not in self.output_connections for output_direction in output_dirs):
                    for new_header, output_direction in headers_and_output_directions:
                        logger.debug(f'Make a new connection from {input_direction} to {output_direction} length {header.length} in router ({self.x}, {self.y})')
                        assert output_direction not in self.output_connections
                        self.output_connections[output_direction] = input_direction
                        assert output_direction not in self.output_headers
                        self.output_headers[output_direction] = new_header
                    self.input_connections[input_direction] = Connection(header.length, set(output_dirs), set(output_dirs))

        for output_direction in directions:
            # If there is a connection see if we can send a word
            if (output_direction in self.output_connections) and len(self.output_buffers[output_direction]) < self.params.router_output_buffer_length:
                input_direction = self.output_connections[output_direction]
                buffer = self.input_buffers[input_direction]
                if input_direction not in self.input_connections:
                    logger.error(f'({self.x}, {self.y}): output_dir = {output_direction} input_dir = {input_direction} cannot find input conn')
                conn = self.input_connections[input_direction]
                if buffer and (output_direction in conn.unconsumed):
                    word = self.input_buffers[input_direction][0]
                    if output_direction in self.output_headers:
                        # We want to use the replaced header
                        # because we might have updated the target.
                        assert isinstance(word, Header)
                        self.output_buffers[output_direction].append(self.output_headers[output_direction])
                        del self.output_headers[output_direction]
                    else:
                        assert not isinstance(word, Header)
                        self.output_buffers[output_direction].append(word)
                    conn.unconsumed.remove(output_direction)
                    if not conn.unconsumed:
                        # No other outputs are waiting on this word so we
                        # can pop it off the input queue.
                        self.input_buffers[input_direction].popleft()
                        conn.remaining -= 1
                    if conn.remaining == 1 and conn.unconsumed:
                        # There still stuff left but it's not going to our output.
                        del self.output_connections[output_direction]
                    if conn.remaining == 0:
                        del self.output_connections[output_direction]
                        if not conn.unconsumed:
                            logger.debug(f'({self.x}, {self.y}): from {input_direction} closing connection')
                            del self.input_connections[input_direction]
                    if not conn.unconsumed:
                        conn.unconsumed = set(conn.dests)


class Jamlet:

    def __init__(self, params: LamletParams, x: int, y: int):
        self.params = params
        self.x = x
        self.y = y

        rf_slice_bytes = params.maxvl_bytes // params.k_cols // params.k_rows // params.j_cols // params.j_rows * params.n_vregs
        self.rf_slice = bytearray([0] * rf_slice_bytes)
        self.sram = bytearray([0] * params.jamlet_sram_bytes)
        self.receive_buffer = [None] * params.receive_buffer_depth
        # This is just a queue to hand them up to kamlet
        self.instruction_buffer = None
        self.router = Router(x, y, params)
        self.receive_header = None

    def step(self):
        self.router.step()

        queue = self.router.output_buffers[Direction.H]
        if queue:
            if not self.receive_header:
                assert isinstance(queue[0], Header)
                self.receive_header = queue.popleft().copy()
                self.receive_header.length -= 1
            else:
                if self.receive_header.message_type.INSTRUCTIONS:
                    assert self.instruction_buffer is None
                    self.instruction_buffer = queue.popleft()
                    logger.debug(f'jamlet({self.x}, {self.y}): adding {self.instruction_buffer} to queue')
                    self.receive_header.length -= 1
                elif self.receive_header.message_type == MessageType.SEND:
                    self.receive_buffer[self.receive_header.address % self.receive_buffer_depth] = (
                            queue.popleft())
                    self.receive_header.length -= 1
                    self.receive_header.address += 1
                else:
                    raise NotImplmented()

    SEND = 0
    INSTRUCTIONS = 1


