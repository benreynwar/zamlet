from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields, calculate_total_width, pack_fields_to_int


class LoadStoreModes(IntEnum):
    NONE = 0
    LOAD = 1
    STORE = 2
    RESERVED3 = 3


@dataclass
class LoadStoreInstruction:
    """Load/Store instruction for amlet"""
    mode: LoadStoreModes = LoadStoreModes.NONE
    addr: int = 0  # Address register (a-type register)
    reg: int = 0   # Data register (b-type register for load/store data)
    
    @classmethod
    def get_width(cls, params) -> int:
        """Get the bit width of this instruction type based on parameters"""
        return calculate_total_width(cls.get_field_specs(params))
    
    @classmethod
    def get_field_specs(cls, params) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('mode', 2),
            ('addr', params.a_reg_width),
            ('reg', params.b_reg_width),
        ]
    
    def encode(self, params) -> int:
        """Encode to instruction bits"""
        field_specs = self.get_field_specs(params)
        return pack_fields_to_int(self, field_specs)
    
    @classmethod
    def from_word(cls, word: int) -> 'LoadStoreInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs()
        field_values = unpack_words_to_fields([word], field_specs, word_width=16)
        return cls(**field_values)