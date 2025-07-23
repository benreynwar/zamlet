from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields


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
    def get_field_specs(cls) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('mode', 4),     # 4 bits to support up to 15
            ('result', 5),   # Assuming 5 bits for b-reg address
            ('length', 4),   # Assuming 4 bits for a-reg address
            ('target', 4),   # Assuming 4 bits for a-reg address
            ('channel', 2),  # Assuming 2 bits for channel (up to 4 channels)
        ]
    
    def encode(self) -> int:
        """Encode to instruction bits"""
        words = pack_fields_to_words(self, self.get_field_specs(), word_width=32)
        assert len(words) == 1, f"PacketInstruction requires {len(words)} words but should fit in 1 word"
        return words[0]
    
    @classmethod
    def from_word(cls, word: int) -> 'PacketInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs()
        field_values = unpack_words_to_fields([word], field_specs, word_width=32)
        return cls(**field_values)