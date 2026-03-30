"""AXI4 memory slave for cocotb tests.

Captures AW+W write transactions, stores data in a dict, and
automatically sends B responses.
"""

from collections import deque
from typing import Dict, List, Tuple

import cocotb
from cocotb.triggers import RisingEdge, ReadOnly


class AxiMemory:

    def __init__(self, signals: dict, clock, word_bytes: int = 8):
        self.s = signals
        self.clock = clock
        self.word_bytes = word_bytes
        self.mem: Dict[int, int] = {}
        self.writes: List[Tuple[int, List[int]]] = []
        self._aw_queue: deque = deque()
        self._w_bursts: deque = deque()
        self._b_queue: deque = deque()
        self._ar_queue: deque = deque()

    def start(self):
        self.s['aw_ready'].value = 1
        self.s['w_ready'].value = 1
        self.s['ar_ready'].value = 1
        self.s['b_valid'].value = 0
        self.s['b_id'].value = 0
        self.s['b_resp'].value = 0
        self.s['r_valid'].value = 0
        self.s['r_id'].value = 0
        self.s['r_data'].value = 0
        self.s['r_resp'].value = 0
        self.s['r_last'].value = 0
        cocotb.start_soon(self._aw_capture())
        cocotb.start_soon(self._w_capture())
        cocotb.start_soon(self._match_writes())
        cocotb.start_soon(self._b_driver())
        cocotb.start_soon(self._ar_capture())
        cocotb.start_soon(self._r_driver())

    async def _aw_capture(self):
        while True:
            await RisingEdge(self.clock)
            self.s['aw_ready'].value = 1
            await ReadOnly()
            if int(self.s['aw_valid'].value) == 1:
                entry = {
                    'id': int(self.s['aw_id'].value),
                    'addr': int(self.s['aw_addr'].value),
                    'len': int(self.s['aw_len'].value),
                    'size': int(self.s['aw_size'].value),
                    'burst': int(self.s['aw_burst'].value),
                }
                self._aw_queue.append(entry)

    async def _w_capture(self):
        burst: List[int] = []
        while True:
            await RisingEdge(self.clock)
            self.s['w_ready'].value = 1
            await ReadOnly()
            if int(self.s['w_valid'].value) == 1:
                burst.append(int(self.s['w_data'].value))
                if int(self.s['w_last'].value):
                    self._w_bursts.append(list(burst))
                    burst = []

    async def _match_writes(self):
        while True:
            await RisingEdge(self.clock)
            if self._aw_queue and self._w_bursts:
                aw = self._aw_queue.popleft()
                data = self._w_bursts.popleft()
                addr = aw['addr']
                for i, word in enumerate(data):
                    self.mem[addr + i * self.word_bytes] = word
                self.writes.append((addr, data))
                self._b_queue.append(aw['id'])

    async def _b_driver(self):
        while True:
            await RisingEdge(self.clock)
            self.s['b_valid'].value = 0
            if self._b_queue:
                bid = self._b_queue.popleft()
                self.s['b_valid'].value = 1
                self.s['b_id'].value = bid
                self.s['b_resp'].value = 0
                await ReadOnly()
                while int(self.s['b_ready'].value) != 1:
                    await RisingEdge(self.clock)
                    await ReadOnly()

    async def _ar_capture(self):
        while True:
            await RisingEdge(self.clock)
            self.s['ar_ready'].value = 1
            await ReadOnly()
            if int(self.s['ar_valid'].value) == 1:
                entry = {
                    'id': int(self.s['ar_id'].value),
                    'addr': int(self.s['ar_addr'].value),
                    'len': int(self.s['ar_len'].value),
                    'size': int(self.s['ar_size'].value),
                    'burst': int(self.s['ar_burst'].value),
                }
                self._ar_queue.append(entry)

    async def _r_driver(self):
        await RisingEdge(self.clock)
        while True:
            self.s['r_valid'].value = 0
            if self._ar_queue:
                ar = self._ar_queue.popleft()
                addr = ar['addr']
                beat_bytes = 1 << ar['size']
                n_beats = ar['len'] + 1
                for i in range(n_beats):
                    beat_addr = addr + i * beat_bytes
                    data = self.mem.get(beat_addr, 0)
                    self.s['r_valid'].value = 1
                    self.s['r_id'].value = ar['id']
                    self.s['r_data'].value = data
                    self.s['r_resp'].value = 0
                    self.s['r_last'].value = 1 if i == n_beats - 1 else 0
                    await ReadOnly()
                    while int(self.s['r_ready'].value) != 1:
                        await RisingEdge(self.clock)
                        await ReadOnly()
                    await RisingEdge(self.clock)
            else:
                await RisingEdge(self.clock)
