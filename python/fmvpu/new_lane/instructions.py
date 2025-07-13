from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields
from fmvpu.new_lane.lane_params import LaneParams

# Instruction type constants (bits 15-14)
PACKET_INSTR_TYPE = 0x0000  # 00
LDST_INSTR_TYPE = 0x4000    # 01  
ALU_INSTR_TYPE = 0x8000     # 10
LOOP_INSTR_TYPE = 0xC000    # 11


@dataclass
class PacketInstruction:
    """Packet instruction encoding (bits 15-14 = 00)"""
    mode: int  # 3 bits (bits 13-11)
    mask: bool = 0 # 1 bit (bit 9)
    location_reg: int = 0 # 3 bits (bits 8-6)
    send_length_reg: int = 0 # 3 bits (bits 5-3)
    result_reg: int = 0 # 3 bits (bits 2-0)
    
    @classmethod
    def get_field_specs(cls) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('mode', 3),
            ('mask', 1), 
            ('location_reg', 3),
            ('send_length_reg', 3),
            ('result_reg', 3),
        ]
    
    def encode(self) -> int:
        """Encode to 16-bit instruction"""
        words = pack_fields_to_words(self, self.get_field_specs(), word_width=16)
        assert len(words) == 1, f"PacketInstruction requires {len(words)} words but should fit in 1 word"
        return words[0] | PACKET_INSTR_TYPE


@dataclass 
class ALUInstruction:
    """ALU instruction encoding (bits 15-14 = 10)"""
    mode: int  # 4 bits (bits 13-10)
    mask: bool  # 1 bit (bit 9)
    src1_reg: int  # 3 bits (bits 8-6)
    src2_reg: int  # 3 bits (bits 5-3)
    dest_reg: int  # 3 bits (bits 2-0)
    
    @classmethod
    def get_field_specs(cls) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('mode', 4),
            ('mask', 1),
            ('src1_reg', 3),
            ('src2_reg', 3), 
            ('dest_reg', 3),
        ]
    
    def encode(self) -> int:
        """Encode to 16-bit instruction"""
        words = pack_fields_to_words(self, self.get_field_specs(), word_width=16)
        assert len(words) == 1, f"ALUInstruction requires {len(words)} words but should fit in 1 word"
        instr = words[0]
        return instr | ALU_INSTR_TYPE


class PacketModes(IntEnum):
    RECEIVE = 0
    RECEIVE_AND_FORWARD = 1
    RECEIVE_FORWARD_AND_APPEND = 2
    FORWARD_AND_APPEND = 3
    SEND = 4
    GET_WORD = 5


class ALUModes(IntEnum):
    ADD = 0
    ADDI = 1
    SUB = 2
    SUBI = 3
    MULT = 4
    MULT_ACC = 5


class PacketHeaderModes(IntEnum):
    NORMAL = 0
    COMMAND = 1


class CommandTypes(IntEnum):
    START = 0
    WRITE_INSTRUCTION_MEMORY = 1
    WRITE_REGISTER = 2
    RESERVED = 3


@dataclass
class PacketHeader:
    """Packet header structure"""
    length: int  # 8 bits
    dest_x: int = 0  # 5 bits (assuming 32 max)
    dest_y: int = 0  # 5 bits
    mode: PacketHeaderModes = PacketHeaderModes.NORMAL  # 1 bit (0=normal, 1=command)
    forward: bool = False  # 1 bit
    is_broadcast: bool = False  # 1 bit  
    broadcast_direction: int = 0  # 2 bits
    
    @classmethod
    def get_field_specs(cls) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('length', 8),
            ('dest_x', 5),
            ('dest_y', 5),
            ('mode', 1),
            ('forward', 1),
            ('is_broadcast', 1),
            ('broadcast_direction', 2),
        ]
    
    def encode(self) -> int:
        """Encode to 32-bit header"""
        words = pack_fields_to_words(self, self.get_field_specs(), word_width=32)
        assert len(words) == 1, f"PacketHeader requires {len(words)} words but should fit in 1 word"
        return words[0]
    
    @classmethod
    def from_word(cls, word: int) -> 'PacketHeader':
        """Parse packet header from a 32-bit word"""
        field_specs = cls.get_field_specs()
        field_values = unpack_words_to_fields([word], field_specs, word_width=32)
        return cls(**field_values)


def create_register_write_command(register: int, value: int, params: LaneParams = LaneParams()) -> int:
    """Create register write command word (type 2)"""
    cmd = CommandTypes.WRITE_REGISTER << (params.width - 2)  # Command type in upper 2 bits
    cmd |= (register & ((1 << params.reg_addr_width) - 1)) << (params.width - 2 - params.reg_addr_width)  # Register address
    cmd |= value & ((1 << (params.width - 2 - params.reg_addr_width)) - 1)  # Value in remaining bits
    return cmd


def create_instruction_memory_write_command(address: int, instruction: int, params: LaneParams = LaneParams()) -> int:
    """Create instruction memory write command word (type 1)"""
    cmd = CommandTypes.WRITE_INSTRUCTION_MEMORY << (params.width - 2)  # Command type in upper 2 bits
    cmd |= (instruction & ((1 << params.instruction_width) - 1)) << params.instr_addr_width  # Instruction
    cmd |= address & ((1 << params.instr_addr_width) - 1)  # Address
    return cmd


def create_start_command(pc: int, params: LaneParams = LaneParams()) -> int:
    """Create start execution command word (type 0)"""
    cmd = CommandTypes.START << (params.width - 2)  # Command type in upper 2 bits
    cmd |= pc & ((1 << (params.width - 2)) - 1)  # PC address in remaining bits
    return cmd


@dataclass
class HaltInstruction:
    """HALT instruction encoding (bits 15-14 = 11, bits 13-12 = 01, bits 11-10 = 00)"""
    
    def encode(self) -> int:
        """Encode to 16-bit instruction"""
        # Bits 15-14 = 11 (LOOP_INSTR_TYPE)
        # Bits 13-12 = 01 
        # Bits 11-10 = 00 (mode)
        # Bits 9-0 = unused (0)
        return LOOP_INSTR_TYPE | (0x01 << 12) | (0x00 << 10)
