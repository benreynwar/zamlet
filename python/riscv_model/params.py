import dataclasses
from dataclasses import dataclass
from enum import Enum

from asyncio import Event


class SendType(Enum):
    SINGLE = 0
    BROADCAST = 1


class MessageType(Enum):
    SEND = 0
    INSTRUCTIONS = 1

    READ_BYTE_FROM_SRAM_RESP = 2

    WRITE_REG_REQ = 8
    WRITE_SP_REQ = 9
    WRITE_MEM_REQ = 10

    WRITE_REG_RESP = 12
    WRITE_SP_RESP = 13
    WRITE_MEM_RESP = 14

    READ_REG_REQ = 16
    READ_SP_REQ = 17
    READ_MEM_REQ = 18

    READ_REG_RESP = 20 
    READ_SP_RESP = 21
    READ_MEM_RESP = 22


@dataclass
class Header:
    target_x: int    # 7: 0
    target_y: int    # 15: 8
    source_x: int    # 23: 16
    source_y: int    # 32: 24 
    length: int    # 35: 32
    message_type: MessageType  # 43: 36
    send_type: SendType
    address: int = None  # 63: 48
    value: int = None

    def copy(self):
        return dataclasses.replace(self)


class Direction(Enum):
    N = 0
    S = 1
    E = 2
    W = 3
    H = 4


directions = (Direction.N, Direction.S, Direction.E, Direction.W, Direction.H)


@dataclass
class LamletParams:
    k_cols: int
    k_rows: int

    j_cols: int
    j_rows: int

    n_vregs: int = 40
    maxvl_bytes: int = 1024
    cache_line_bytes: int = 512
    word_bytes: int = 8
    page_bytes: int = 1 << 12
    scalar_memory_bytes: int = 3 << 20
    kamlet_memory_bytes: int = 1 << 20
    jamlet_sram_bytes: int = 2 << 10
    tohost_addr: int = 0x80001000
    fromhost_addr: int = 0x80001040
    receive_buffer_depth: int = 16
    router_output_buffer_length: int = 2
    router_input_buffer_length: int = 2
    instruction_queue_length: int = 16

    def __post_init__(self):
        # Page must be bigger than a vector
        assert self.page_bytes > 0
        assert self.page_bytes % self.maxvl_bytes == 0
        # Vector must be a multiple of words per jamlet
        assert self.maxvl_bytes > 0
        assert self.maxvl_bytes % (self.k_cols*self.k_rows*self.j_cols*self.j_rows*self.word_bytes) == 0
        # Cache line must be bigger than 1 word per jamlet in a kamlet
        assert self.cache_line_bytes > 0
        assert self.cache_line_bytes % (self.j_cols*self.j_rows*self.word_bytes) == 0
        # Page must be bigger than a cache line
        assert self.page_bytes >= self.k_in_l * self.cache_line_bytes
        assert self.page_bytes % (self.k_in_l * self.cache_line_bytes) == 0
        # Sane scalar memory
        assert self.scalar_memory_bytes > self.cache_line_bytes
        assert self.scalar_memory_bytes % self.cache_line_bytes == 0
        # Sane kamlet memory
        assert self.kamlet_memory_bytes > self.cache_line_bytes
        assert self.kamlet_memory_bytes % self.cache_line_bytes == 0

    @property
    def k_in_l(self):
        return self.k_cols * self.k_rows

    @property
    def j_in_k(self):
        return self.j_cols * self.j_rows

    @property
    def j_in_l(self):
        return self.j_in_k * self.k_in_l

    @property
    def vline_bytes(self):
        return self.j_in_l * self.word_bytes
