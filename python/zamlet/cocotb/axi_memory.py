"""AXI4 memory responders for cocotb tests."""

import random
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import cocotb
from cocotb.triggers import ReadOnly

from zamlet.test_utils import next_drive_phase
from zamlet.utils import make_seed


@dataclass
class Axi4Signals:
    aw_valid: object
    aw_ready: object
    aw_id: object
    aw_addr: object
    aw_len: object
    aw_size: object
    aw_burst: object
    w_valid: object
    w_ready: object
    w_data: object
    w_last: object
    b_valid: object
    b_ready: object
    b_id: object
    b_resp: object
    ar_valid: object
    ar_ready: object
    ar_id: object
    ar_addr: object
    ar_len: object
    ar_size: object
    ar_burst: object
    r_valid: object
    r_ready: object
    r_id: object
    r_data: object
    r_resp: object
    r_last: object

    @classmethod
    def from_prefix(cls, dut, prefix: str) -> 'Axi4Signals':
        return cls(
            aw_valid=getattr(dut, f'{prefix}_aw_valid'),
            aw_ready=getattr(dut, f'{prefix}_aw_ready'),
            aw_id=getattr(dut, f'{prefix}_aw_bits_id'),
            aw_addr=getattr(dut, f'{prefix}_aw_bits_addr'),
            aw_len=getattr(dut, f'{prefix}_aw_bits_len'),
            aw_size=getattr(dut, f'{prefix}_aw_bits_size'),
            aw_burst=getattr(dut, f'{prefix}_aw_bits_burst'),
            w_valid=getattr(dut, f'{prefix}_w_valid'),
            w_ready=getattr(dut, f'{prefix}_w_ready'),
            w_data=getattr(dut, f'{prefix}_w_bits_data'),
            w_last=getattr(dut, f'{prefix}_w_bits_last'),
            b_valid=getattr(dut, f'{prefix}_b_valid'),
            b_ready=getattr(dut, f'{prefix}_b_ready'),
            b_id=getattr(dut, f'{prefix}_b_bits_id'),
            b_resp=getattr(dut, f'{prefix}_b_bits_resp'),
            ar_valid=getattr(dut, f'{prefix}_ar_valid'),
            ar_ready=getattr(dut, f'{prefix}_ar_ready'),
            ar_id=getattr(dut, f'{prefix}_ar_bits_id'),
            ar_addr=getattr(dut, f'{prefix}_ar_bits_addr'),
            ar_len=getattr(dut, f'{prefix}_ar_bits_len'),
            ar_size=getattr(dut, f'{prefix}_ar_bits_size'),
            ar_burst=getattr(dut, f'{prefix}_ar_bits_burst'),
            r_valid=getattr(dut, f'{prefix}_r_valid'),
            r_ready=getattr(dut, f'{prefix}_r_ready'),
            r_id=getattr(dut, f'{prefix}_r_bits_id'),
            r_data=getattr(dut, f'{prefix}_r_bits_data'),
            r_resp=getattr(dut, f'{prefix}_r_bits_resp'),
            r_last=getattr(dut, f'{prefix}_r_bits_last'),
        )


class Axi4MemoryBase:

    def __init__(self, signals: Axi4Signals, clock,
                 aw_p_ready: float = 1.0, w_p_ready: float = 1.0,
                 ar_p_ready: float = 1.0, seed: int = 0):
        self.signals = signals
        self.clock = clock
        self._aw_queue: deque = deque()
        self._w_bursts: deque = deque()
        self._b_queue: deque = deque()
        self._ar_queue: deque = deque()
        self.aw_p_ready = aw_p_ready
        self.w_p_ready = w_p_ready
        self.ar_p_ready = ar_p_ready
        self._rng = random.Random(seed)

    def start(self) -> List[Any]:
        s = self.signals
        s.aw_ready.value = 0
        s.w_ready.value = 0
        s.ar_ready.value = 0
        s.b_valid.value = 0
        s.b_id.value = 0
        s.b_resp.value = 0
        s.r_valid.value = 0
        s.r_id.value = 0
        s.r_data.value = 0
        s.r_resp.value = 0
        s.r_last.value = 0
        return [
            cocotb.start_soon(self._aw_capture(random.Random(make_seed(self._rng)))),
            cocotb.start_soon(self._w_capture(random.Random(make_seed(self._rng)))),
            cocotb.start_soon(self._match_writes()),
            cocotb.start_soon(self._b_driver()),
            cocotb.start_soon(self._ar_capture(random.Random(make_seed(self._rng)))),
            cocotb.start_soon(self._r_driver()),
        ]

    async def _aw_capture(self, rng: random.Random):
        s = self.signals
        while True:
            await next_drive_phase(self.clock)
            s.aw_ready.value = int(rng.random() < self.aw_p_ready)
            await ReadOnly()
            if int(s.aw_valid.value) == 1 and int(s.aw_ready.value) == 1:
                entry = {
                    'id': int(s.aw_id.value),
                    'addr': int(s.aw_addr.value),
                    'len': int(s.aw_len.value),
                    'size': int(s.aw_size.value),
                    'burst': int(s.aw_burst.value),
                }
                self._aw_queue.append(entry)

    async def _w_capture(self, rng: random.Random):
        s = self.signals
        burst: List[int] = []
        while True:
            await next_drive_phase(self.clock)
            s.w_ready.value = int(rng.random() < self.w_p_ready)
            await ReadOnly()
            if int(s.w_valid.value) == 1 and int(s.w_ready.value) == 1:
                burst.append(int(s.w_data.value))
                if int(s.w_last.value):
                    self._w_bursts.append(list(burst))
                    burst = []

    async def _match_writes(self):
        while True:
            await next_drive_phase(self.clock)
            if self._aw_queue and self._w_bursts:
                aw = self._aw_queue.popleft()
                data = self._w_bursts.popleft()
                self.handle_write(aw, data)
                self._b_queue.append(aw['id'])

    async def _b_driver(self):
        s = self.signals
        while True:
            await next_drive_phase(self.clock)
            s.b_valid.value = 0
            if self._b_queue:
                bid = self._b_queue.popleft()
                s.b_valid.value = 1
                s.b_id.value = bid
                s.b_resp.value = 0
                await ReadOnly()
                while int(s.b_ready.value) != 1:
                    await next_drive_phase(self.clock)
                    await ReadOnly()

    async def _ar_capture(self, rng: random.Random):
        s = self.signals
        while True:
            await next_drive_phase(self.clock)
            s.ar_ready.value = int(rng.random() < self.ar_p_ready)
            await ReadOnly()
            if int(s.ar_valid.value) == 1 and int(s.ar_ready.value) == 1:
                entry = {
                    'id': int(s.ar_id.value),
                    'addr': int(s.ar_addr.value),
                    'len': int(s.ar_len.value),
                    'size': int(s.ar_size.value),
                    'burst': int(s.ar_burst.value),
                }
                self._ar_queue.append(entry)

    async def _r_driver(self):
        s = self.signals
        await next_drive_phase(self.clock)
        while True:
            s.r_valid.value = 0
            if self._ar_queue:
                ar = self._ar_queue.popleft()
                data = self.handle_read(ar)
                for i, beat in enumerate(data):
                    s.r_valid.value = 1
                    s.r_id.value = ar['id']
                    s.r_data.value = beat
                    s.r_resp.value = 0
                    s.r_last.value = 1 if i == len(data) - 1 else 0
                    await ReadOnly()
                    while int(s.r_ready.value) != 1:
                        await next_drive_phase(self.clock)
                        await ReadOnly()
                    await next_drive_phase(self.clock)
            else:
                await next_drive_phase(self.clock)

    def handle_write(self, aw: dict, data: List[int]) -> None:
        raise NotImplementedError

    def handle_read(self, ar: dict) -> List[int]:
        raise NotImplementedError


class AxiMemory(Axi4MemoryBase):

    def __init__(self, signals: Axi4Signals, clock, word_bytes: int = 8,
                 aw_p_ready: float = 1.0, w_p_ready: float = 1.0,
                 ar_p_ready: float = 1.0, seed: int = 0):
        super().__init__(signals, clock, aw_p_ready, w_p_ready, ar_p_ready, seed)
        self.word_bytes = word_bytes
        self.mem: Dict[int, int] = {}
        self.writes: List[Tuple[int, List[int]]] = []

    def handle_write(self, aw: dict, data: List[int]) -> None:
        addr = aw['addr']
        for i, word in enumerate(data):
            self.mem[addr + i * self.word_bytes] = word
        self.writes.append((addr, data))

    def handle_read(self, ar: dict) -> List[int]:
        addr = ar['addr']
        beat_bytes = 1 << ar['size']
        n_beats = ar['len'] + 1
        return [
            self.mem.get(addr + i * beat_bytes, 0)
            for i in range(n_beats)
        ]
