from collections import deque
from dataclasses import dataclass
from enum import Enum

from params import Direction, LamletParams, CacheState, directions


@dataclass
class OutputConnection:
    remaining: int
    source: Direction


class Router:

    def __init__(self, x: int, y: int, params: LamletParams):
        self.params = params
        self.input_buffers = {Direction.N: deque(), Direction.S: deque(), Direction.E: deque(), Direction.W: deque(), Direction.H: deque()}
        self.output_buffers = {Direction.N: deque(), Direction.S: deque(), Direction.E: deque(), Direction.W: deque(), Direction.H: deque()}
        self.output_connections = {}
        self.priority = list(directions)

    def get_output_direction(self, header):
        if header.x > self.x:
            return Direction.E
        elif header.x < self.x:
            return Direction.W
        elif header.y > self.y:
            return Direction.S
        elif header.y < self.y:
            return Direction.N
        else:
            return Direction.H

    async def run(self, clock):

        while True:
            self.priority = self.priority[1:] + self.priority[0]
            for output_direction in self.directions:
                if output_direction not in self.output_connections:
                    # Try to make a new connection 
                    for input_direction in self.priority:
                        if self.input_buffers[input_direction]:
                            if isinstance(self.input_buffers[input_direction][0], Header):
                                header = self.input_buffers[input_direction][0]
                                output_direction = self.get_output_direction(header)
                                self.output_connections[output_direction] = OutputConnection(header.length+1, input_direction)
                                break
                # If there is a connection see if we can send a word
                if output_direction in self.output_connections:
                    conn = self.output_connections[output_direction]
                    if self.input_buffers[conn.source] and self.output_buffers[output_direction] < self.params.router_output_buffer_length:
                        word = self.input_buffers[conn.source].popleft()
                        self.output_buffers[output_direction].append(word)
                        conn.remaining -= 1
                        if conn.remaining == 0:
                            del self.output_connections[output_direction]

            await clock.next_cycle()
        


class Jamlet:

    def __init__(self, params: LamletParams, x: int, y: int):
        self.params = params
        self.x = x
        self.y = y

        rf_slice_bytes = params.maxvl_bytes // params.k_cols // params.k_rows // params.j_cols // params.j_rows * params.n_vregs
        self.rf_slice = bytes([0] * rf_slice_bytes)

        self.sram = bytes([0] * params.jamlet_sram_bytes)

        self.receive_buffer = [None] * params.receive_buffer_depth

        # This is just a queue to hand them up to kamlet
        self.instruction_buffer = None

        self.router = Router(x, y, params)

        self.receive_header = None

    async def run(self, clock):

        spawn(self.router.run())

        while True:

            await self.router.finished

            queue = self.output_connections[Direction.H]
            if queue:
                if not receive_header:
                    assert isinstance(queue[0], Header)
                    self.receive_header = queue.popleft()
                    self.receive_header.length -= 1
                else:
                    if self.receive_header.INSTRUCTIONS:
                        assert self.instruction_buffer is None
                        self.instruction_buffer = queue.popleft()
                        self.receive_header.length -= 1
                    elif self.receive_header.message_type == MessageType.SEND:
                        self.receive_buffer[self.receive_header.address % self.receive_buffer_depth] = (
                                queue.popleft())
                        self.receive_header.length -= 1
                        self.receive_header.address += 1
                    else:
                        raise NotImplmented()

            await clock.next_cycle()

    SEND = 0
    INSTRUCTIONS = 1


