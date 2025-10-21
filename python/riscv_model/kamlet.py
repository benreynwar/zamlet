from dataclasses import dataclass
from collections import deque

from addresses import CacheState
from params import LamletParams
from jamlet import Jamlet
from kinstructions import KInstr
from message import Header, MessageType


class KamletScoreBoard:

    def __init__(self, params: LamletParams):
        self.registers_updating = [False] * params.n_vregs
        # Instructions that produce results are put
        max_pipeline_length = 4
        self.in_flight_funcs = [[] for i in range(max_pipeline_length)]


class Kamlet:

    def __init__(self, params: LamletParams, min_x: int, min_y: int):
        self.params = params
        self.min_x = min_x
        self.min_y = min_y
        self.n_columns = params.j_cols
        self.n_rows = params.j_rows
        self.n_jamlets = self.n_columns * self.n_rows

        self.jamlets = [Jamlet(params, min_x+index % self.n_columns, min_y+index//self.n_columns)
                        for index in range(self.n_jamlets)]

        self.instruction_queue = deque()

    def get_jamlet(self, x, y):
        assert self.min_x <= x < self.min_x + self.n_columns
        assert self.min_y <= y < self.min_y + self.n_rows
        jamlet = self.jamlets[(y - self.min_y) * self.n_columns + (x - self.min_x)]
        assert jamlet.x == x
        assert jamlet.y == y
        return jamlet

    def add_to_instruction_queue(self, instr: KInstr):
        assert isinstance(instr, KInstr)
        self.instruction_queue.append(instr)
        assert len(self.instruction_queue) < self.params.instruction_queue_length

    def step(self):

        for jamlet in self.jamlets:
            jamlet.step()

        # If we have an instruction then do it
        if self.instruction_queue:
            instr = self.instruction_queue[0]
            if (not hasattr(instr, 'blocking')) or not instr.blocking(self):
                instr.update_kamlet(self)
                self.instruction_queue.popleft()

        # Get received instructions from jamlets
        for index, jamlet in enumerate(self.jamlets):
            if jamlet.instruction_buffer is not None:
                if index == 0:
                    self.add_to_instruction_queue(jamlet.instruction_buffer)
                jamlet.instruction_buffer = None
