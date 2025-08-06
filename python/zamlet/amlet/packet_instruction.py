import logging
from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from zamlet.control_structures import unpack_words_to_fields
from zamlet.control_structures import calculate_total_width, pack_fields_to_int
from zamlet.utils import clog2


logger = logging.getLogger(__name__)


class PacketModes(IntEnum):
    NONE = 0
    RECEIVE = 1
    RECEIVE_AND_FORWARD = 2
    RECEIVE_FORWARD_AND_APPEND = 3
    FORWARD_AND_APPEND = 4
    SEND = 5
    GET_WORD = 6
    BROADCAST = 7
    UNUSED8 = 8
    UNUSED9 = 9
    RECEIVE_AND_FORWARD_CONTINUOUSLY = 10
    RECEIVE_FORWARD_AND_APPEND_CONTINUOUSLY = 11
    FORWARD_AND_APPEND_CONTINUOUSLY = 12
    SEND_AND_FORWARD_AGAIN = 13
    UNUSED14 = 14
    UNUSED15 = 15


@dataclass
class PacketInstruction:
    """Packet instruction for amlet (send/receive packets)"""
    mode: PacketModes = PacketModes.NONE
    result: int = None  # Result register (b-type register) 
    length: int = 0   # Length register (a-type register)
    target: int = 0   # Target register (a-type register)
    predicate: int = 0  # P-register for predicate
    channel: int = 0  # Channel number
    a_dst: int = None
    d_dst: int = None

    def __post_init__(self):
        """Set result based on a_dst or d_dst if specified"""
        if self.mode not in (PacketModes.NONE, PacketModes.SEND):
            count = (self.a_dst is not None) + (self.d_dst is not None) + (self.result is not None)
            if count != 1:
                raise ValueError("Must specifiy exactly 1 of a_dst, d_dst and result")
    
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
            ('mode', 4),     # 4 bits to support up to 15
            ('result', params.b_reg_width),
            ('length', params.a_reg_width),
            ('target', params.a_reg_width),
            ('predicate', params.p_reg_width),
            ('channel', clog2(params.n_channels)),
        ]
    
    def encode(self, params) -> int:
        """Encode to instruction bits"""
        # Determine the actual result value
        if self.a_dst is not None:
            # A-registers map directly to B-register space
            actual_result = self.a_dst
        elif self.d_dst is not None:
            # D-registers map to B-register space starting at cutoff
            cutoff = max(params.n_a_regs, params.n_d_regs)
            actual_result = cutoff + self.d_dst
        elif self.result is not None:
            actual_result = self.result
        else:
            actual_result = 0
        
        # Create a temporary object for encoding
        temp_instr = type(self)(
            mode=self.mode,
            result=actual_result,
            length=self.length,
            target=self.target,
            predicate=self.predicate,
            channel=self.channel
        )
        
        field_specs = self.get_field_specs(params)
        return pack_fields_to_int(temp_instr, field_specs)
    
    @classmethod
    def from_word(cls, word: int, params) -> 'PacketInstruction':
        """Parse instruction from word"""
        field_specs = cls.get_field_specs(params)
        field_values = unpack_words_to_fields([word], field_specs, word_width=32)
        return cls(**field_values)
