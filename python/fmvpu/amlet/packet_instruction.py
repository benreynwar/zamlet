from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields, calculate_total_width, pack_fields_to_int


class PacketModes(IntEnum):
    NULL = 0
    RECEIVE = 1
    RECEIVE_AND_FORWARD = 2
    RECEIVE_FORWARD_AND_APPEND = 3
    FORWARD_AND_APPEND = 4
    SEND = 5
    GET_PACKET_WORD = 6
    BROADCAST = 7
    UNUSED8 = 8
    UNUSED9 = 9
    RECEIVE_AND_FORWARD_CONTINUOUSLY = 10
    RECEIVE_FORWARD_AND_APPEND_CONTINUOUSLY = 11
    FORWARD_AND_APPEND_CONTINUOUSLY = 12
    SEND_AND_FORWARD_AGAIN = 13
    UNUSED14 = 14
    UNUSED15 = 15


@dataclass
class PacketInstruction:
    """Packet instruction for amlet (send/receive packets)"""
    mode: PacketModes = PacketModes.NULL
    result: int = 0   # Result register (b-type register)
    length: int = 0   # Length register (a-type register)
    target: int = 0   # Target register (a-type register)
    channel: int = 0  # Channel number
    
    @classmethod
    def get_width(cls, params) -> int:
        """Get the bit width of this instruction type based on parameters"""
        return calculate_total_width(cls.get_field_specs(params))
    
    @classmethod
    def get_field_specs(cls, params) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        from fmvpu.test_utils import clog2
        return [
            ('mode', 4),     # 4 bits to support up to 15
            ('result', params.b_reg_width),
            ('length', params.a_reg_width),
            ('target', params.a_reg_width),
            ('channel', clog2(params.n_channels)),
        ]
    
    def encode(self, params) -> int:
        """Encode to instruction bits"""
        field_specs = self.get_field_specs(params)
        return pack_fields_to_int(self, field_specs)
    
    @classmethod
    def from_word(cls, word: int) -> 'PacketInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs()
        field_values = unpack_words_to_fields([word], field_specs, word_width=32)
        return cls(**field_values)