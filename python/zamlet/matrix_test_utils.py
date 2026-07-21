import random

from cocotb.triggers import ReadOnly

from zamlet.test_utils import rising_edge

INT8_MIN = -128
INT8_MAX = 127
UINT32_MASK = (1 << 32) - 1


class SkewedControlDriver:
    def __init__(self, dut, signal_name: str):
        self.signal = getattr(dut, f"io_{signal_name}")
        self.clock = dut.clock
        self.cycle = 0
        self.n_cycles = 0
        self.just_set = False
        self.next_n_cycles: None | int = None

    def request(self, cycles: int) -> None:
        assert self.n_cycles == 0
        if cycles > 0:
            self.signal.value = 1
            assert not self.just_set
            self.just_set = True
            self.next_n_cycles = cycles - 1

    async def run(self) -> None:
        while True:
            await rising_edge(self.clock)
            if not self.just_set:
                self.signal.value = int(self.n_cycles > 0)
            await ReadOnly()
            if self.n_cycles > 0:
                self.n_cycles -= 1
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
