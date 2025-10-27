from enum import Enum
import dataclasses
from dataclasses import dataclass


class SendType(Enum):
    SINGLE = 0
    BROADCAST = 1


class MessageType(Enum):
    SEND = 0
    INSTRUCTIONS = 1

    READ_BYTES_FROM_SRAM_RESP = 2
    # Jamlet tells a memory to write some cache line
    WRITE_LINE = 3
    # Jamlet tells a memory to read a cache line
    READ_LINE = 4
    # Memory replies with the cache line
    READ_LINE_RESP = 5
    # Memory notifys the scalar processor of a line write
    WRITE_LINE_NOTIFY = 6
    # Jamlet notifies the scalar processor of a line read
    READ_LINE_NOTIFY = 7

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
    words_requested: int = None

    def copy(self):
        return dataclasses.replace(self)


class Direction(Enum):
    N = 0
    S = 1
    E = 2
    W = 3
    H = 4


directions = (Direction.N, Direction.S, Direction.E, Direction.W, Direction.H)


