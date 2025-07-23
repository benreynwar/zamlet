from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields


class ControlModes(IntEnum):
    NONE = 0
    IF = 1
    LOOP = 2
    RESERVED3 = 3
    INCR = 4  # Increments the index of the current loop
    RESERVED5 = 5
    RESERVED6 = 6
    RESERVED7 = 7


@dataclass
class ControlInstruction:
    """Control instruction for amlet (loops, conditionals, halt)"""
    mode: ControlModes = ControlModes.NONE
    src: int = 0   # Source register (a-type register)
    dst: int = 0   # Destination register (a-type register)
    endif: bool = False   # End if control bit
    endloop: bool = False # End loop control bit
    halt: bool = False    # Halt control bit
    
    @classmethod
    def get_field_specs(cls) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('mode', 3),
            ('src', 4),    # Assuming 4 bits for a-reg address
            ('dst', 4),    # Assuming 4 bits for a-reg address
            ('endif', 1),
            ('endloop', 1),
            ('halt', 1),
        ]
    
    def encode(self) -> int:
        """Encode to instruction bits"""
        words = pack_fields_to_words(self, self.get_field_specs(), word_width=16)
        assert len(words) == 1, f"ControlInstruction requires {len(words)} words but should fit in 1 word"
        return words[0]
    
    @classmethod
    def from_word(cls, word: int) -> 'ControlInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs()
        field_values = unpack_words_to_fields([word], field_specs, word_width=16)
        return cls(**field_values)