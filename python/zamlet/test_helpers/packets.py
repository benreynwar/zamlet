from collections import deque
from random import Random
from typing import Any, List

import cocotb
from cocotb.triggers import Event
from cocotb.triggers import ReadOnly, RisingEdge

from zamlet.future import Future
from zamlet.message import Header, int_to_header
from zamlet.utils import make_seed


class NetworkPacketSource:
    def __init__(self, dut, clock, prefix: str):
        self.dut = dut
        self.clock = clock
        self.prefix = prefix
        self.queue = deque()
        self.valid = getattr(dut, f"{prefix}_valid")
        self.ready = getattr(dut, f"{prefix}_ready")
        self.data = getattr(dut, f"{prefix}_bits_data")
        self.is_header = getattr(dut, f"{prefix}_bits_isHeader")

    def enqueue_word(self, data: int, is_header: bool) -> None:
        self.queue.append((data, is_header))

    def enqueue_packet(self, header_word: int, body_words: list[int]) -> None:
        self.enqueue_word(header_word, True)
        for word in body_words:
            self.enqueue_word(word, False)

    def start(self, rng: Random, p_valid: float = 1.0) -> List[Any]:
        return [cocotb.start_soon(self.run(seed=make_seed(rng), p_valid=p_valid))]

    async def run(self, seed: int, p_valid: float = 1.0) -> None:
        rng = Random(seed)

        self.valid.value = 0
        current = None
        while True:
            if current is None and self.queue and rng.random() < p_valid:
                current = self.queue.popleft()

            if current is None:
                self.valid.value = 0
                fired = False
            else:
                data, is_header = current
                self.valid.value = 1
                self.data.value = data
                self.is_header.value = int(is_header)
                await ReadOnly()
                fired = bool(int(self.ready.value))

            await RisingEdge(self.clock)

            if fired:
                current = None


class NetworkPacketSink:
    def __init__(self, dut, clock, prefix: str, params,
                 max_packet_queue_depth: int | None = None):
        self.dut = dut
        self.clock = clock
        self.prefix = prefix
        self.params = params
        self.max_packet_queue_depth = max_packet_queue_depth
        self.future_queue = deque()
        self.packet_queue = deque()
        self.valid = getattr(dut, f"{prefix}_valid")
        self.ready = getattr(dut, f"{prefix}_ready")
        self.data = getattr(dut, f"{prefix}_bits_data")
        self.is_header = getattr(dut, f"{prefix}_bits_isHeader")

    def get_packet_future(self) -> Future:
        future = Future(Event())
        self.future_queue.append(future)
        return future

    def start(self, rng: Random, p_ready: float = 1.0) -> List[Any]:
        return [
            cocotb.start_soon(self.run(seed=make_seed(rng), p_ready=p_ready)),
            cocotb.start_soon(self.resolve()),
        ]

    async def resolve(self) -> None:
        while True:
            while self.future_queue and self.packet_queue:
                self.future_queue.popleft().set_result(self.packet_queue.popleft())
            await RisingEdge(self.clock)

    async def run(self, seed: int, p_ready: float = 1.0) -> None:
        rng = Random(seed)
        packet = []
        remaining = 0

        self.ready.value = 0
        while True:
            queue_has_room = (
                self.max_packet_queue_depth is None
                or len(self.packet_queue) < self.max_packet_queue_depth)
            self.ready.value = int(queue_has_room and rng.random() < p_ready)
            await ReadOnly()
            if int(self.valid.value) and int(self.ready.value):
                data = int(self.data.value)
                if int(self.is_header.value):
                    assert remaining == 0, "received new header before packet payload completed"
                    header = int_to_header(data, self.params)
                    assert isinstance(header, Header)
                    packet = [header]
                    remaining = header.length
                else:
                    assert packet, "received payload word before packet header"
                    assert remaining > 0, "received more payload words than packet length"
                    packet.append(data)
                    remaining -= 1
                if packet and remaining == 0:
                    self.packet_queue.append(packet)
                    packet = []
            await RisingEdge(self.clock)
