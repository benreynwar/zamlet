import logging
from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields, calculate_total_width, pack_fields_to_int


logger = logging.getLogger(__name__)


class ALUModes(IntEnum):
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
class ALUInstruction:
    """ALU instruction for amlet"""
    mode: ALUModes = ALUModes.NONE
    src1: int = 0  # Source 1 register (d-type register)
    src2: int = 0  # Source 2 register (d-type register)
    dst: int = None   # Encoded destination register (B-register space)
    a_dst: int = None  # A-register destination (if specified)
    d_dst: int = None  # D-register destination (if specified)
    
    def __post_init__(self):
        """Set dst based on a_dst or d_dst if specified"""
        if self.mode != ALUModes.NONE:
            count = (self.a_dst is not None) + (self.d_dst is not None) + (self.dst is not None)
            if count != 1:
                raise ValueError(f"Must specifiy exactly 1 of a_dst ({self.a_dst}), d_dst({self.d_dst}) and dst({self.dst})")
    
    @classmethod
    def get_width(cls, params) -> int:
        """Get the bit width of this instruction type based on parameters"""
        return calculate_total_width(cls.get_field_specs(params))
    
    @classmethod
    def get_field_specs(cls, params) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('mode', 5),  # 5 bits to support up to 31
            ('src1', params.d_reg_width),
            ('src2', params.d_reg_width),
            ('dst', params.b_reg_width),
        ]
    
    def encode(self, params) -> int:
        """Encode to instruction bits"""
        # Determine the actual dst value
        if self.a_dst is not None:
            # A-registers map directly to B-register space
            actual_dst = self.a_dst
        elif self.d_dst is not None:
            # D-registers map to B-register space starting at cutoff
            cutoff = max(params.n_a_regs, params.n_d_regs)
            actual_dst = cutoff + self.d_dst
        elif self.dst is not None:
            actual_dst = self.dst
        else:
            actual_dst = 0
        
        # Create a temporary object for encoding
        temp_instr = type(self)(
            mode=self.mode,
            src1=self.src1,
            src2=self.src2,
            dst=actual_dst
        )
        
        field_specs = self.get_field_specs(params)
        assert temp_instr.dst is not None
        return pack_fields_to_int(temp_instr, field_specs)
    
    @classmethod
    def from_word(cls, word: int, params) -> 'ALUInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs(params)
        field_values = unpack_words_to_fields([word], field_specs, word_width=32)
        return cls(**field_values)
