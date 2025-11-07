from enum import Enum
import dataclasses
from dataclasses import dataclass


class SendType(Enum):
    SINGLE = 0
    BROADCAST = 1



class MessageType(Enum):
    SEND = 0
    INSTRUCTIONS = 1

    # Jamlet responds to scalar processor instruction  with some bytes
    READ_BYTES_RESP = 2
    # Jamlet tells a memory to write some cache line
    WRITE_LINE = 3
    # Kamlet tells a memory to read a cache line
    READ_LINE = 4
    # Memory replies to jamlets with the cache line
    READ_LINE_RESP = 5
    # Memory notifys the kamlet of a line write
    WRITE_LINE_RESP = 6

    # A request to read a single byte from VPU memory
    READ_BYTE = 8
    READ_BYTE_RESP = 9
    # A request to read a word from VPU memory
    READ_WORD = 10
    READ_WORD_RESP = 11

    #WRITE_REG_REQ = 8
    #WRITE_SP_REQ = 9
    #WRITE_MEM_REQ = 10

    #WRITE_REG_RESP = 12
    #WRITE_SP_RESP = 13
    #WRITE_MEM_RESP = 14

    #READ_REG_REQ = 16
    #READ_SP_REQ = 17
    #READ_MEM_REQ = 18

    #READ_REG_RESP = 20 
    #READ_SP_RESP = 21
    #READ_MEM_RESP = 22

# What channel do different messages travel on.

CHANNEL_MAPPING = {
    # Which messages types can always be consumed
    MessageType.READ_LINE_RESP: 0,
    MessageType.WRITE_LINE_RESP: 0,
    MessageType.READ_BYTES_RESP: 0,

    # Which channel require to send a always consumable message for them to be consumed
    MessageType.READ_LINE: 1,
    MessageType.WRITE_LINE: 1,

    # This is always consumable because we will explicitly track how much buffer room there is.
    MessageType.INSTRUCTIONS: 0,

    # Send is always consumable becaue we track how many slots are available.
    MessageType.SEND: 0,
    }


@dataclass
class Header:
    # Limited to 64 bit  total
    target_x: int    # 8 bits
    target_y: int    # 8 bits
    source_x: int    # 8 bits
    source_y: int    # 8 bits
    length: int      # 4 bits
    # Used to tie requests and responses together
    message_type: MessageType  # 5 bits
    send_type: SendType        # 2 bits
    ident: int = None      # 5 bits
    address: int = None  # 12 or 16 bits   (either address or value)
    value: int = None    # 16 bits
    words_requested: int = None  # 4 bits  (if used address is 12 bits)

    def copy(self):
        return dataclasses.replace(self)


class Direction(Enum):
    N = 0
    S = 1
    E = 2
    W = 3
    H = 4


directions = (Direction.N, Direction.S, Direction.E, Direction.W, Direction.H)


