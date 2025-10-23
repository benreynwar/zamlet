from dataclasses import dataclass
from collections import deque

from addresses import CacheState
from params import LamletParams
from jamlet import Jamlet
from kinstructions import KInstr
from message import Header, MessageType, SendType
from utils import Queue


class KamletScoreBoard:

    def __init__(self, params: LamletParams):
        self.registers_updating = [False] * params.n_vregs
        # Instructions that produce results are put
        max_pipeline_length = 4
        self.in_flight_funcs = [[] for i in range(max_pipeline_length)]


class Kamlet:

    def __init__(self, clock, params: LamletParams, min_x: int, min_y: int):
        self.clock = clock
        self.params = params
        self.min_x = min_x
        self.min_y = min_y
        self.n_columns = params.j_cols
        self.n_rows = params.j_rows
        self.n_jamlets = self.n_columns * self.n_rows

        self.jamlets = []
        for index in range(self.n_jamlets):
            x = min_x+index % self.n_columns
            y = min_y+index//self.n_columns
            self.jamlets.append(Jamlet(clock, params, x, y))

        # Local State
        self._instruction_queue = Queue(self.params.instruction_queue_length)

    def update(self):
        self._instruction_queue.update()
        for jamlet in self.jamlets:
            jamlet.update()

    @property
    def k_index(self):
        return self.min_y // self.params.j_rows * self.params.k_cols + self.min_x // self.params.j_cols

    def get_jamlet(self, x, y):
        assert self.min_x <= x < self.min_x + self.n_columns
        assert self.min_y <= y < self.min_y + self.n_rows
        jamlet = self.jamlets[(y - self.min_y) * self.n_columns + (x - self.min_x)]
        assert jamlet.x == x
        assert jamlet.y == y
        return jamlet

    def add_to_instruction_queue(self, instr: KInstr):
        assert isinstance(instr, KInstr)
        self._instruction_queue.append(instr)

    async def run(self):
        for jamlet in self.jamlets:
            self.clock.create_task(jamlet.run())
        while True:
            await self.clock.next_cycle
            # If we have an instruction then do it
            if self._instruction_queue:
                instruction = self._instruction_queue.popleft()
                self.clock.create_task(instruction.update_kamlet(self))
            # Get received instructions from jamlets
            for index, jamlet in enumerate(self.jamlets):
                if jamlet._instruction_buffer:
                    instr = jamlet._instruction_buffer.popleft()
                    if index == 0:
                        self.add_to_instruction_queue(instr)
