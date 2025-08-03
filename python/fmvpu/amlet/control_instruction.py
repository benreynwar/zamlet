from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum
import math

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields, calculate_total_width, pack_fields_to_int


class ControlModes(IntEnum):
    NONE = 0
    LOOP_IMMEDIATE = 1
    LOOP_LOCAL = 2
    LOOP_GLOBAL = 3
    INCR = 4  # Increments the index of the current loop
    END_LOOP = 5 # Removed before going to machinecode
    RESERVED6 = 6
    HALT = 7


@dataclass
class ControlInstruction:
    """Control instruction for amlet (loops, conditionals, halt)"""
    mode: ControlModes = ControlModes.NONE
    iterations: int = 0  # Immediate, A-reg index, or G-reg index (depends on mode)
    dst: int = 0   # Destination A-register (where loop index goes)
    length: int = 0  # Number of instructions in loop body
    
    @classmethod
    def get_width(cls, params) -> int:
        """Get the bit width of this instruction type based on parameters"""
        return calculate_total_width(cls.get_field_specs(params))
    
    @classmethod
    def get_field_specs(cls, params) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing.
        
        Field order must match the Scala bundle definition.
        """
        # Calculate src width based on max of A-regs and G-regs
        src_width = math.ceil(math.log2(max(params.n_a_regs, params.n_g_regs)))
        
        return [
            ('mode', 3),  # 3 bits for 8 modes
            ('iterations', src_width),  # Width based on max reg space
            ('dst', params.a_reg_width),  # A-register destination
            ('length', params.instr_addr_width),  # Instruction address width
        ]
    
    def encode(self, params) -> int:
        """Encode to instruction bits"""
        field_specs = self.get_field_specs(params)
        return pack_fields_to_int(self, field_specs)
    
    @classmethod
    def from_word(cls, word: int, params) -> 'ControlInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs(params)
        field_values = unpack_words_to_fields([word], field_specs, word_width=32)
        
        # Convert enum fields
        field_values['mode'] = ControlModes(field_values['mode'])
        
        return cls(**field_values)
    
    def __str__(self) -> str:
        if self.mode == ControlModes.NONE:
            return "control none"
        elif self.mode == ControlModes.HALT:
            return "control halt"
        elif self.mode == ControlModes.LOOP_IMMEDIATE:
            return f"control loop_immediate {self.iterations} -> a{self.dst}, (len: {self.length})"
        elif self.mode == ControlModes.LOOP_LOCAL:
            return f"control loop_local a{self.iterations} -> a{self.dst}, (len: {self.length})"
        elif self.mode == ControlModes.LOOP_GLOBAL:
            return f"control loop_global g{self.iterations} -> a{self.dst}, (len: {self.length})"
        elif self.mode == ControlModes.INCR:
            return "control incr"
        else:
            return f"control {self.mode.name.lower()}"
