import logging
from collections import deque
import struct


logger = logging.getLogger(__name__)


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
