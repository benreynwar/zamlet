from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields, calculate_total_width, pack_fields_to_int


class ControlModes(IntEnum):
    NONE = 0
    IF = 1
    LOOP = 2
    LOOPGLOBAL = 3
    INCR = 4  # Increments the index of the current loop
    ENDIF = 5
    ENDLOOP = 6
    HALT = 7


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
    def get_width(cls, params) -> int:
        """Get the bit width of this instruction type based on parameters"""
        return calculate_total_width(cls.get_field_specs(params))
    
    @classmethod
    def get_field_specs(cls, params) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('mode', 3),
            ('src', params.a_reg_width),
            ('dst', params.a_reg_width),
            ('endif', 1),
            ('endloop', 1),
            ('halt', 1),
        ]
    
    def encode(self, params) -> int:
        """Encode to instruction bits"""
        field_specs = self.get_field_specs(params)
        return pack_fields_to_int(self, field_specs)
    
    @classmethod
    def from_word(cls, word: int) -> 'ControlInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs()
        field_values = unpack_words_to_fields([word], field_specs, word_width=16)
        return cls(**field_values)
