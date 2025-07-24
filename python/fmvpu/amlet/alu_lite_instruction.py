from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields, calculate_total_width, pack_fields_to_int


class ALULiteModes(IntEnum):
    NONE = 0
    ADD = 1
    ADDI = 2
    SUB = 3
    SUBI = 4
    MULT = 5
    MULT_ACC = 6
    MULT_ACC_INIT = 7
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
class ALULiteInstruction:
    """ALU Lite instruction for amlet (address calculations)"""
    mode: ALULiteModes = ALULiteModes.NONE
    src1: int = 0  # Source 1 register (a-type register)
    src2: int = 0  # Source 2 register (a-type register)
    dst: int = 0   # Destination register (b-type register)
    
    @classmethod
    def get_width(cls, params) -> int:
        """Get the bit width of this instruction type based on parameters"""
        return calculate_total_width(cls.get_field_specs(params))
    
    @classmethod
    def get_field_specs(cls, params) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('mode', 5),  # 5 bits to support up to 31
            ('src1', params.a_reg_width),
            ('src2', params.a_reg_width),
            ('dst', params.b_reg_width),
        ]
    
    def encode(self, params) -> int:
        """Encode to instruction bits"""
        field_specs = self.get_field_specs(params)
        return pack_fields_to_int(self, field_specs)
    
    @classmethod
    def from_word(cls, word: int) -> 'ALULiteInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs()
        field_values = unpack_words_to_fields([word], field_specs, word_width=32)
        return cls(**field_values)