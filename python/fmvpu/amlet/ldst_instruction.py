from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields


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
    def get_field_specs(cls) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('mode', 2),
            ('addr', 4),  # Assuming 4 bits for a-reg address
            ('reg', 5),   # Assuming 5 bits for b-reg address
        ]
    
    def encode(self) -> int:
        """Encode to instruction bits"""
        words = pack_fields_to_words(self, self.get_field_specs(), word_width=16)
        assert len(words) == 1, f"LoadStoreInstruction requires {len(words)} words but should fit in 1 word"
        return words[0]
    
    @classmethod
    def from_word(cls, word: int) -> 'LoadStoreInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs()
        field_values = unpack_words_to_fields([word], field_specs, word_width=16)
        return cls(**field_values)