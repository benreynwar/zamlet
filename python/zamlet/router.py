from dataclasses import dataclass
import logging
from typing import Set

from zamlet.message import Direction, directions, Header, SendType
from zamlet.params import LamletParams
from zamlet.utils import Queue


logger = logging.getLogger(__name__)


@dataclass
class Connection:
    remaining: int
    dests: Set[Direction]
    unconsumed: Set[Direction]
    age: int
    header: Header


class Router:

    def __init__(self, clock, params: LamletParams, x: int, y: int, channel: int = 0):
        self.clock = clock
        self.x = x
        self.y = y
        self.channel = channel
        self.params = params

        # Local State
        ibl = self.params.router_input_buffer_length
        obl = self.params.router_output_buffer_length
        self._input_buffers = {Direction.N: Queue(ibl), Direction.S: Queue(ibl), Direction.E: Queue(ibl), Direction.W: Queue(ibl), Direction.H: Queue(ibl)}
        self._output_buffers = {Direction.N: Queue(obl), Direction.S: Queue(obl), Direction.E: Queue(obl), Direction.W: Queue(obl), Direction.H: Queue(obl)}
        self._input_connections = {}
        self._output_connections = {}
        self._output_headers = {}

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
        new_priority = list(directions)
        while True:
            shift_priority = False
            await self.clock.next_cycle
            priority = new_priority[:]
            for input_direction in priority:
                buffer = self._input_buffers[input_direction]
                if (input_direction not in self._input_connections) and buffer:
                    # We have some input data, and it's not made a connection yet.
                    header = buffer.head()
                    assert isinstance(header, Header)
                    # For each output direction this should connect to, we create a new header.
                    # We need to create new headers to handle broadcast instructions.
                    # TODO: We could probably do this by just looking at the source x and y rather
                    #       than making a new header.
                    headers_and_output_directions = self.get_output_directions(header)
                    output_dirs = set(x[1] for x in headers_and_output_directions)
                    if all(output_direction not in self._output_connections for output_direction in output_dirs):
                        # All the required output directions are free.
                        # We create a new connection.
                        for new_header, output_direction in headers_and_output_directions:
                            logger.debug(f'{self.clock.cycle}: ({self.x}, {self.y}) ch{self.channel}: Make a new connection from {input_direction} to {output_direction} length {header.length} in router ({self.x}, {self.y}) target=({header.target_x}, {header.target_y})')
                            assert output_direction not in self._output_connections
                            self._output_connections[output_direction] = input_direction
                            # Put the new headers in self._output_headers
                            # We'll use this the first time we send something in this direction on this connection.
                            assert output_direction not in self._output_headers
                            self._output_headers[output_direction] = new_header
                        self._input_connections[input_direction] = Connection(header.length, set(output_dirs), set(output_dirs), 0, header.copy())
                        # We made a connection, put this at lowest priority
                        new_priority.remove(input_direction)
                        new_priority.append(input_direction)
                else:
                    # It doesn't have any packets, put it at low priority
                    new_priority.remove(input_direction)
                    new_priority.append(input_direction)
                if (input_direction in self._input_connections) and buffer:
                    # We have some data and we've already made a connection.
                    # Just make sure that we have headers when we expect them.
                    conn = self._input_connections[input_direction]
                    if conn.remaining == conn.header.length:
                        assert isinstance(buffer.head(), Header)
                    else:
                        assert not isinstance(buffer.head(), Header)

            for output_direction in directions:
                # If there is a connection see if we can send a word
                output_buffer = self._output_buffers[output_direction]
                if output_direction in self._output_connections:
                    input_direction = self._output_connections[output_direction]
                    input_buffer = self._input_buffers[input_direction]
                    conn = self._input_connections[input_direction]
                    if not output_buffer.can_append():
                        # Get message type from the header if available
                        msg_type = "unknown"
                        if input_buffer and isinstance(input_buffer.head(), Header):
                            msg_type = input_buffer.head().message_type.name
                        logger.debug(
                            f'{self.clock.cycle}: ({self.x}, {self.y}) ch{self.channel}: '
                            f'BLOCKED {input_direction}->{output_direction} '
                            f'output_buffer full (len={len(output_buffer)}, appended={output_buffer.appended}) '
                            f'msg_type={msg_type} conn.header={conn.header}')
                    elif not input_buffer:
                        logger.debug(
                            f'{self.clock.cycle}: ({self.x}, {self.y}) ch{self.channel}: '
                            f'WAITING {input_direction}->{output_direction} '
                            f'input_buffer empty, remaining={conn.remaining}')
                    elif output_direction not in conn.unconsumed:
                        logger.debug(
                            f'{self.clock.cycle}: ({self.x}, {self.y}) ch{self.channel}: '
                            f'SKIP {input_direction}->{output_direction} '
                            f'already consumed this word')
                if (output_direction in self._output_connections) and output_buffer.can_append():
                    input_direction = self._output_connections[output_direction]
                    input_buffer = self._input_buffers[input_direction]
                    conn = self._input_connections[input_direction]
                    if input_buffer and (output_direction in conn.unconsumed):
                        # We haven't yet sent this word to this output direction.
                        word = input_buffer.head()
                        if output_direction in self._output_headers:
                            # This is the first time we've used this connection in this direction.
                            # We want to use the replaced header
                            # because we might have updated the target.
                            assert isinstance(word, Header)
                            updated_header = self._output_headers[output_direction]
                            # Remove the output header so we know it's not the first time we've used this.
                            del self._output_headers[output_direction]
                            output_buffer.append(updated_header)
                            logger.debug(f'{self.clock.cycle}: ({self.x}, {self.y}) {input_direction} -> {output_direction} {updated_header}')
                        else:
                            assert not isinstance(word, Header)
                            logger.debug(f'{self.clock.cycle}: ({self.x}, {self.y}) {input_direction} -> {output_direction} {word}')
                            output_buffer.append(word)
                        conn.unconsumed.remove(output_direction)
                        #if not conn.unconsumed:
                        #    import kinstructions
                        #    if isinstance(word, kinstructions.ReadLine) and word.ident == 4:
                        #        logger.error(f'************** {self.clock.cycle}: ({self.x}, {self.y}) {input_direction} -> {output_direction} consuming value')
                        #    # No other outputs are waiting on this word so we
                        #    # can pop it off the input queue.
                        #    input_buffer.popleft()
                        #    conn.remaining -= 1
                        #    if conn.remaining == 0:
                        #        logger.debug(f'{self.clock.cycle}: ({self.x}, {self.y}): from {input_direction} closing connection age={conn.age}')
                        #        del self._input_connections[input_direction]
                        #        del self._output_connections[output_direction]
                        #    # We finished with that word.
                        #    # So we update this to indicate that noone has consumed the next word yet.
                        #    conn.unconsumed = set(conn.dests)
                        #else:
                        #    # Other outputs are still waiting on this word.
                        #    # But this output isn't anymore so remove this output connection.
                        #    if conn.remaining == 1:
                        #        # There still stuff left but it's not going to our output.
                        #        del self._output_connections[output_direction]

                        # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                        #if self.x == 0 and self.y == 0 and isinstance(word, kinstructions.ReadLine):
                        #    logger.error(f'jamlet got {word}')

            # If we're on the last word delete the output connections as we send the final word.
            to_delete_output_dirs = set()
            for output_direction, input_direction in self._output_connections.items():
                conn = self._input_connections[input_direction]
                if output_direction not in conn.unconsumed and conn.remaining == 1:
                    to_delete_output_dirs.add(output_direction)
            for output_direction in to_delete_output_dirs:
                del self._output_connections[output_direction]

            to_delete_input_dirs = set()
            for input_direction, conn in self._input_connections.items():
                # Pop a word is nowhere is needs it.
                if not conn.unconsumed:
                    input_buffer = self._input_buffers[input_direction]
                    input_buffer.popleft()
                    conn.remaining -= 1
                    if conn.remaining == 0:
                        logger.debug(f'{self.clock.cycle}: ({self.x}, {self.y}): from {input_direction} closing connection age={conn.age}')
                        to_delete_input_dirs.add(input_direction)
                    # We finished with that word.
                    # So we update this to indicate that noone has consumed the next word yet.
                    conn.unconsumed = set(conn.dests)
                # Just debugging to catch when our network gets jammed.
                conn.age +=1
                #if conn.age > 100:
                #    import pdb
                #    pdb.set_trace()

            for input_direction in to_delete_input_dirs:
                del self._input_connections[input_direction]


