import logging
from collections import deque
import struct
from typing import List


logger = logging.getLogger(__name__)


def uint_to_bits(value, width):
    """
    >> uint_to_bits(3)
    [1, 1]
    >> uint_to_bits(16)
    [0, 0, 0, 0, 1]
    """
    bits = []
    for i in range(width):
        bits.append(value % 2)
        value = value // 2
    assert not value
    return bits

def bits_to_uint(bits):
    """
    >> bits_to_uint([1, 0, 1, 1])
    13
    """
    value = 0
    for bit in reversed(bits):
        value = value*2 + bit
    return value


def make_seed(rnd):
    return rnd.getrandbits(32)


def clog2(value: int) -> int:
    """Calculate ceiling log2 - how many bits are required to represent 'value-1'."""
    value = value - 1
    bits = 0
    while value > 0:
        value = value >> 1
        bits += 1
    return bits


def log2ceil(value):
    assert value >= 0
    n_bits = 0
    while value > 0:
        n_bits += 1
        value = value >> 1
    return n_bits


def bytes_to_float(byts):
    length = len(byts)
    if length == 4:
        float_val = struct.unpack('f', byts)[0]
    elif length == 8:
        float_val = struct.unpack('d', byts)[0]
    else:
        raise NotImplementedError
    return float_val


def float_to_bytes(fl, length=4):
    if length == 4:
        byts = struct.pack('f', fl)
    elif length == 8:
        byts = struct.pack('d', fl)
    else:
        raise NotImplementedError
    assert len(byts) == length
    return byts


def is_power_of_two(value):
    return (value == 2) or ((value > 1) and (value % 2 == 0) and (is_power_of_two(value//2)))


class Queue:
    """
    This is a queue where we can control that only at most one value is appended or popped per cycle.
    """

    def __init__(self, length=None):
        self.queue = deque()
        self.popped = False
        self.appended = False
        self.to_append = None
        self.length = length

    def __bool__(self):
        return bool(self.queue)

    def __len__(self):
        return len(self.queue)

    def head(self):
        return self.queue[0]

    def popleft(self):
        assert not self.popped
        self.popped = True
        return self.head()

    def append(self, value):
        assert not self.appended
        self.to_append = value
        self.appended = True
        assert len(self.queue) < self.length

    def can_append(self):
        return (len(self.queue) < self.length) and (not self.appended)

    def update(self):
        if self.popped:
            self.queue.popleft()
        if self.appended:
            self.queue.append(self.to_append)
        self.popped = False
        self.appended = False
        self.to_append = None


async def combine_futures(combined_future, futures):
    x = []
    for index, future in enumerate(futures):
        await future
        x.append(future.result)
    combined_future.set_result(x)


def pad(data, n_bytes):
    assert isinstance(data, bytes)
    assert len(data) <= n_bytes
    return data + bytes([0] * (n_bytes - len(data)))


def list_of_uints_to_uint(values: List[int], width: int) -> int:
    total = 0
    for value in reversed(values):
        assert 0 <= value < (1 << width)
        total = (total << width) + value
    return total


def uint_to_list_of_uints(value: int, width: int, size: int) -> List[int]:
    ll = []
    f = 1 << width
    for _ in range(size):
        ll.append(value % f)
        value = value >> width
    assert value == 0
    return ll


class SettableBool:

    def __init__(self, value):
        self.value = value
        self.has_next_value = False
        self.next_value = False

    def set(self, value):
        assert not self.has_next_value
        self.has_next_value = True
        self.next_value = value

    def update(self):
        if self.has_next_value:
            self.value = self.next_value
        self.has_next_value = False

    def __bool__(self):
        return self.value

    def peek(self):
        if self.has_next_value:
            return self.next_value
        else:
            return self.value

def update_int_word(old_word: int, new_word: int, mask: int):
    old_masked = old_word & (~mask)
    new_masked = new_word & mask
    updated = old_masked | new_masked
    return updated

def update_bytes_word(old_word: bytes, new_word: bytes, mask: int) -> bytes:
    n_bytes = len(old_word)
    assert len(new_word) == n_bytes
    assert mask < 1 << (n_bytes * 8)
    old_int = int.from_bytes(old_word, byteorder='little')
    new_int = int.from_bytes(new_word, byteorder='little')
    updated_int = update_int_word(old_int, new_int, mask)
    updated = updated_int.to_bytes(n_bytes, byteorder='little')
    return updated

def shift_and_update_word(old_word: bytes, src_word: bytes, src_start: int, dst_start:int, n_bytes: int):
    '''
    We want to take `n_bytes` bytes from the `src_word` starting at byte `src_start` and write them to
    the `old_word` starting at byte `dst_start` to produce the new word which we return.

    All parameters are in bytes, not bits.
    '''
    word_length = len(old_word)
    assert word_length == len(src_word)
    src_word_int = int.from_bytes(src_word, byteorder='little')
    # Convert byte offsets to bit offsets for shifting
    shift_bits = (src_start - dst_start) * 8
    if shift_bits > 0:
        shifted = src_word_int >> shift_bits
    else:
        shifted = src_word_int << (-shift_bits)
    # Create mask for n_bytes starting at dst_start (in bits)
    mask = ((1 << (n_bytes * 8)) - 1) << (dst_start * 8)
    masked_shifted = shifted & mask
    old_word_int = int.from_bytes(old_word, byteorder='little')
    updated_int = update_int_word(old_word_int, masked_shifted, mask)
    updated = updated_int.to_bytes(word_length, byteorder='little')
    return updated


def split_by_factors(value, factors, allow_remainder=True):
    reduced = value
    pieces = []
    for factor in factors:
        pieces.append(reduced % factor)
        reduced = reduced//factor
    if allow_remainder:
        pieces.append(reduced)
    else:
        assert reduced == 0
    return pieces


def join_by_factors(values, factors):
    assert len(values) in (len(factors) + 1, len(factors))
    f = 1
    total = 0
    for value, factor in zip(values[:-1], factors):
        assert value < factor
        total += value * f
        f *= factor
    if len(values) == len(factors):
        assert values[-1] < factors[-1]
    total += values[-1] * f
    return total
