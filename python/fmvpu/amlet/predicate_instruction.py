import logging
from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields, calculate_total_width, pack_fields_to_int
from fmvpu.utils import clog2


logger = logging.getLogger(__name__)


class PredicateModes(IntEnum):
    """Predicate instruction modes"""
    NONE = 0
    EQ = 1
    NEQ = 2
    GTE = 3
    GT = 4
    LTE = 5
    LT = 6
    UNUSED7 = 7


class Src1Mode(IntEnum):
    """Source 1 modes for predicate instructions"""
    IMMEDIATE = 0
    LOOP_INDEX = 1
    GLOBAL = 2
    UNUSED3 = 3


@dataclass
class PredicateInstruction:
    """Predicate instruction for comparison operations"""
    mode: PredicateModes = PredicateModes.NONE
    src1_mode: Src1Mode = Src1Mode.IMMEDIATE
    src1_value: int = 0  # Immediate value, loop index, or global register index
    src2: int = 0        # A-register index
    base: int = 0        # P-register index for base predicate
    not_base: bool = False  # Whether to negate the base predicate
    dst: int = 0         # P-register index for destination
    
    @classmethod
    def get_width(cls, params) -> int:
        """Get the bit width of this instruction type based on parameters"""
        return calculate_total_width(cls.get_field_specs(params))
    
    @classmethod
    def get_field_specs(cls, params) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        src1_value_width = clog2(max(params.n_loop_levels, params.n_g_regs))
        
        return [
            ('mode', 3),  # 8 modes -> 3 bits
            ('src1_mode', 2),  # 4 modes -> 2 bits
            ('src1_value', src1_value_width),
            ('src2', params.a_reg_width),
            ('base', params.p_reg_width),
            ('not_base', 1),
            ('dst', params.p_reg_width),
        ]
    
    def encode(self, params) -> int:
        """Encode to instruction bits"""
        field_specs = self.get_field_specs(params)
        return pack_fields_to_int(self, field_specs)
    
    @classmethod
    def from_word(cls, word: int, params) -> 'PredicateInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs(params)
        field_values = unpack_words_to_fields([word], field_specs, word_width=32)
        
        # Convert enum fields
        field_values['mode'] = PredicateModes(field_values['mode'])
        field_values['src1_mode'] = Src1Mode(field_values['src1_mode'])
        field_values['not_base'] = bool(field_values['not_base'])
        
        return cls(**field_values)
    
    def __str__(self) -> str:
        if self.mode == PredicateModes.NONE:
            return "predicate none"
            
        src1_str = f"{self.src1_value}"
        if self.src1_mode == Src1Mode.LOOP_INDEX:
            src1_str = f"loop[{self.src1_value}]"
        elif self.src1_mode == Src1Mode.GLOBAL:
            src1_str = f"g{self.src1_value}"
        
        base_str = f"{'!' if self.not_base else ''}p{self.base}"
        
        return f"predicate {self.mode.name.lower()} {src1_str}, a{self.src2} -> p{self.dst} (base: {base_str})"