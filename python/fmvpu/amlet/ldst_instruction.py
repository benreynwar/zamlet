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
    addr: int = 0   # Address register that points to memory location
    reg: int = None    # Encoded data register (B-register space)
    predicate: int = 0  # P-register for predicate
    dst: int = None   # Encoded destination register (B-register space)
    a_reg: int = None  # A-register for store result (if specified)
    d_reg: int = None  # D-register for store result (if specified)
    # Either a_reg, d_reg or src goes into reg
    
    def __post_init__(self):
        """Set reg based on a_reg or d_reg if specified"""
        if self.mode != LoadStoreModes.NONE:
            count = (self.a_reg is not None) + (self.d_reg is not None) + (self.reg is not None)
            if count != 1:
                raise ValueError("Must specifiy exactly 1 of a_reg, d_reg and reg")
    
    @classmethod
    def get_width(cls, params) -> int:
        """Get the bit width of this instruction type based on parameters"""
        return calculate_total_width(cls.get_field_specs(params))
    
    @classmethod
    def get_field_specs(cls, params) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing.
        
        Field order must match the Scala bundle definition.
        """
        return [
            ('mode', 2),
            ('addr', params.a_reg_width),
            ('reg', params.b_reg_width),
            ('predicate', params.p_reg_width),
        ]
    
    def encode(self, params) -> int:
        """Encode to instruction bits"""
        # Determine the actual reg value
        actual_reg = self.reg
        if self.a_reg is not None:
            # A-registers map directly to B-register space
            actual_reg = self.a_reg
        elif self.d_reg is not None:
            # D-registers map to B-register space starting at cutoff
            cutoff = max(params.n_a_regs, params.n_d_regs)
            actual_reg = cutoff + self.d_reg
        elif self.reg is not None:
            actual_reg = self.reg
        else:
            actual_reg = 0
        
        # Create a temporary object for encoding
        temp_instr = type(self)(
            mode=self.mode,
            addr=self.addr,
            reg=actual_reg,
            predicate=self.predicate,
            dst=self.dst if self.dst is not None else 0
        )
        
        field_specs = self.get_field_specs(params)
        return pack_fields_to_int(temp_instr, field_specs)
    
    @classmethod
    def from_word(cls, word: int, params) -> 'LoadStoreInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs(params)
        field_values = unpack_words_to_fields([word], field_specs, word_width=16)
        return cls(**field_values)
