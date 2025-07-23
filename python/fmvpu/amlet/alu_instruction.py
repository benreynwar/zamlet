from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields


class ALUModes(IntEnum):
    NONE = 0
    ADD = 1
    ADDI = 2
    SUB = 3
    SUBI = 4
    MULT = 5
    MULT_ACC = 6
    RESERVED7 = 7
    EQ = 8
    GTE = 9
    LTE = 10
    NOT = 11
    AND = 12
    OR = 13
    RESERVED14 = 14
    RESERVED15 = 15
    SHIFT_L = 16
    SHIFT_R = 17
    RESERVED18 = 18
    RESERVED19 = 19
    RESERVED20 = 20
    RESERVED21 = 21
    RESERVED22 = 22
    RESERVED23 = 23
    RESERVED24 = 24
    RESERVED25 = 25
    RESERVED26 = 26
    RESERVED27 = 27
    RESERVED28 = 28
    RESERVED29 = 29
    RESERVED30 = 30
    JUMP = 31


@dataclass
class ALUInstruction:
    """ALU instruction for amlet"""
    mode: ALUModes = ALUModes.NONE
    src1: int = 0  # Source 1 register (d-type register)
    src2: int = 0  # Source 2 register (d-type register)
    dst: int = 0   # Destination register (b-type register)
    
    @classmethod
    def get_field_specs(cls) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('mode', 5),  # 5 bits to support up to 31
            ('src1', 4),  # Assuming 4 bits for d-reg address
            ('src2', 4),  # Assuming 4 bits for d-reg address
            ('dst', 5),   # Assuming 5 bits for b-reg address
        ]
    
    def encode(self) -> int:
        """Encode to instruction bits"""
        words = pack_fields_to_words(self, self.get_field_specs(), word_width=32)
        assert len(words) == 1, f"ALUInstruction requires {len(words)} words but should fit in 1 word"
        return words[0]
    
    @classmethod
    def from_word(cls, word: int) -> 'ALUInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs()
        field_values = unpack_words_to_fields([word], field_specs, word_width=32)
        return cls(**field_values)