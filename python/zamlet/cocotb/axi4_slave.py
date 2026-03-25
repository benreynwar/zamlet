"""AXI4 memory slave for cocotb tests.

Captures AW+W write transactions, stores data in a dict, and
automatically sends B responses.
"""

from collections import deque
from typing import Dict, List, Tuple

import cocotb
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, ReadOnly


class AXI4Slave:

    def __init__(self, dut: HierarchyObject, word_bytes: int = 8):
        self.dut = dut
        self.word_bytes = word_bytes
        self.mem: Dict[int, int] = {}
        self.writes: List[Tuple[int, List[int]]] = []
        self._aw_queue: deque = deque()
        self._w_bursts: deque = deque()
        self._b_queue: deque = deque()

    def start(self):
        self.dut.io_axi_aw_ready.value = 1
        self.dut.io_axi_w_ready.value = 1
        self.dut.io_axi_ar_ready.value = 1
        self.dut.io_axi_b_valid.value = 0
        self.dut.io_axi_b_bits_id.value = 0
        self.dut.io_axi_b_bits_resp.value = 0
        self.dut.io_axi_r_valid.value = 0
        self.dut.io_axi_r_bits_id.value = 0
        self.dut.io_axi_r_bits_data.value = 0
        self.dut.io_axi_r_bits_resp.value = 0
        self.dut.io_axi_r_bits_last.value = 0
        cocotb.start_soon(self._aw_capture())
        cocotb.start_soon(self._w_capture())
        cocotb.start_soon(self._match_writes())
        cocotb.start_soon(self._b_driver())

    async def _aw_capture(self):
        while True:
            await RisingEdge(self.dut.clock)
            await ReadOnly()
            if (int(self.dut.io_axi_aw_valid.value)
                    and int(self.dut.io_axi_aw_ready.value)):
                entry = {
                    'id': int(self.dut.io_axi_aw_bits_id.value),
                    'addr': int(self.dut.io_axi_aw_bits_addr.value),
                    'len': int(self.dut.io_axi_aw_bits_len.value),
                    'size': int(self.dut.io_axi_aw_bits_size.value),
                    'burst': int(self.dut.io_axi_aw_bits_burst.value),
                }
                self._aw_queue.append(entry)

    async def _w_capture(self):
        burst: List[int] = []
        while True:
            await RisingEdge(self.dut.clock)
            await ReadOnly()
            if (int(self.dut.io_axi_w_valid.value)
                    and int(self.dut.io_axi_w_ready.value)):
                burst.append(int(self.dut.io_axi_w_bits_data.value))
                if int(self.dut.io_axi_w_bits_last.value):
                    self._w_bursts.append(list(burst))
                    burst = []

    async def _match_writes(self):
        while True:
            await RisingEdge(self.dut.clock)
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
            if self._b_queue:
                bid = self._b_queue[0]
                self.dut.io_axi_b_valid.value = 1
                self.dut.io_axi_b_bits_id.value = bid
                self.dut.io_axi_b_bits_resp.value = 0
                await RisingEdge(self.dut.clock)
                await ReadOnly()
                if int(self.dut.io_axi_b_ready.value):
                    self._b_queue.popleft()
            else:
                self.dut.io_axi_b_valid.value = 0
                await RisingEdge(self.dut.clock)
