import random
from collections.abc import Callable

from cocotb.triggers import ReadOnly, RisingEdge


INT8_MIN = -128
INT8_MAX = 127
UINT32_MASK = (1 << 32) - 1


class SkewedControlDriver:
    def __init__(self, lane_count: int, drive_lanes: Callable[[list[bool]], None]):
        self.cycle = 0
        self.n_cycles = 0
        self.just_set = False
        self.next_n_cycles: None | int = None
        self.history = [False for _ in range(lane_count - 1)]
        self.drive_lanes = drive_lanes

    def request(self, cycles: int) -> None:
        # We are in the Writeable phase.
        assert self.n_cycles == 0
        if cycles > 0:
            self.drive_lanes([True] + self.history)
            assert not self.just_set
            self.just_set = True
            self.next_n_cycles = cycles - 1

    async def run(self, clock) -> None:
        while True:
            await RisingEdge(clock)
            lane0 = self.just_set or self.n_cycles > 0
            lanes = [lane0] + self.history
            if not self.just_set:
                self.drive_lanes(lanes)
            await ReadOnly()
            lane0 = self.just_set or self.n_cycles > 0
            lanes[0] = lane0
            if self.n_cycles > 0:
                self.n_cycles -= 1
            self.history = lanes[:-1]
            if self.just_set:
                self.just_set = False
                assert self.next_n_cycles is not None
                self.n_cycles = self.next_n_cycles
            self.cycle += 1


def int8_bits(value: int) -> int:
    assert INT8_MIN <= value <= INT8_MAX
    if value < 0:
        return value + 256
    return value


def matrix_product(a: list[list[int]], b: list[list[int]]) -> list[list[int]]:
    n = len(a)
    return [
        [sum(a[row][k] * b[k][col] for k in range(n)) for col in range(n)]
        for row in range(n)
    ]


def random_matrix(rng: random.Random, n: int) -> list[list[int]]:
    return [[rng.randint(INT8_MIN, INT8_MAX) for _ in range(n)] for _ in range(n)]
