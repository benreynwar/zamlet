from dataclasses import dataclass
from typing import List, Tuple

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields
from fmvpu.amlet.control_instruction import ControlInstruction
from fmvpu.amlet.alu_instruction import ALUInstruction
from fmvpu.amlet.alu_lite_instruction import ALULiteInstruction
from fmvpu.amlet.ldst_instruction import LoadStoreInstruction
from fmvpu.amlet.packet_instruction import PacketInstruction


@dataclass
class VLIWInstruction:
    """VLIW Instruction containing multiple execution units"""
    control: ControlInstruction = None
    alu: ALUInstruction = None
    alu_lite: ALULiteInstruction = None
    load_store: LoadStoreInstruction = None
    packet: PacketInstruction = None
    
    def __post_init__(self):
        # Initialize empty instructions if not provided
        if self.control is None:
            self.control = ControlInstruction()
        if self.alu is None:
            self.alu = ALUInstruction()
        if self.alu_lite is None:
            self.alu_lite = ALULiteInstruction()
        if self.load_store is None:
            self.load_store = LoadStoreInstruction()
        if self.packet is None:
            self.packet = PacketInstruction()
    
    def encode(self) -> int:
        """Encode VLIW instruction to a word"""
        # This is a simplified encoding - the actual implementation would
        # pack these into appropriate bit fields within the VLIW word
        encoded = 0
        
        # Pack each sub-instruction into different bit ranges
        # Using a 128-bit VLIW word divided into sections
        encoded |= (self.control.encode() & 0xFFFF) << 96   # 16 bits for control
        encoded |= (self.alu.encode() & 0xFFFFFFFF) << 64    # 32 bits for ALU
        encoded |= (self.alu_lite.encode() & 0xFFFFFFFF) << 32  # 32 bits for ALU Lite
        encoded |= (self.load_store.encode() & 0xFFFF) << 16    # 16 bits for load/store
        encoded |= (self.packet.encode() & 0xFFFF)              # 16 bits for packet
        
        return encoded
    
    @classmethod
    def from_word(cls, word: int) -> 'VLIWInstruction':
        """Parse VLIW instruction from word"""
        # Extract each sub-instruction from bit ranges
        control_bits = (word >> 96) & 0xFFFF
        alu_bits = (word >> 64) & 0xFFFFFFFF
        alu_lite_bits = (word >> 32) & 0xFFFFFFFF
        load_store_bits = (word >> 16) & 0xFFFF
        packet_bits = word & 0xFFFF
        
        return cls(
            control=ControlInstruction.from_word(control_bits),
            alu=ALUInstruction.from_word(alu_bits),
            alu_lite=ALULiteInstruction.from_word(alu_lite_bits),
            load_store=LoadStoreInstruction.from_word(load_store_bits),
            packet=PacketInstruction.from_word(packet_bits)
        )


# Convenience functions for creating common VLIW instructions
def create_halt_instruction() -> VLIWInstruction:
    """Create a VLIW instruction that halts execution"""
    from fmvpu.amlet.control_instruction import ControlModes
    control = ControlInstruction(halt=True)
    return VLIWInstruction(control=control)


def create_load_instruction(addr_reg: int, dest_reg: int) -> VLIWInstruction:
    """Create a VLIW instruction with load operation"""
    from fmvpu.amlet.ldst_instruction import LoadStoreModes
    load_store = LoadStoreInstruction(
        mode=LoadStoreModes.LOAD,
        addr=addr_reg,
        reg=dest_reg
    )
    return VLIWInstruction(load_store=load_store)


def create_store_instruction(addr_reg: int, src_reg: int) -> VLIWInstruction:
    """Create a VLIW instruction with store operation"""
    from fmvpu.amlet.ldst_instruction import LoadStoreModes
    load_store = LoadStoreInstruction(
        mode=LoadStoreModes.STORE,
        addr=addr_reg,
        reg=src_reg
    )
    return VLIWInstruction(load_store=load_store)


def create_alu_instruction(mode, src1_reg: int, src2_reg: int, dest_reg: int) -> VLIWInstruction:
    """Create a VLIW instruction with ALU operation"""
    from fmvpu.amlet.alu_instruction import ALUModes
    alu = ALUInstruction(
        mode=mode,
        src1=src1_reg,
        src2=src2_reg,
        dst=dest_reg
    )
    return VLIWInstruction(alu=alu)


def create_packet_send_instruction(target_reg: int, length_reg: int, channel: int = 0) -> VLIWInstruction:
    """Create a VLIW instruction with packet send operation"""
    from fmvpu.amlet.packet_instruction import PacketModes
    packet = PacketInstruction(
        mode=PacketModes.SEND,
        target=target_reg,
        length=length_reg,
        channel=channel
    )
    return VLIWInstruction(packet=packet)


def create_packet_receive_instruction(result_reg: int, channel: int = 0) -> VLIWInstruction:
    """Create a VLIW instruction with packet receive operation"""
    from fmvpu.amlet.packet_instruction import PacketModes
    packet = PacketInstruction(
        mode=PacketModes.RECEIVE,
        result=result_reg,
        channel=channel
    )
    return VLIWInstruction(packet=packet)


# Re-export common classes and enums for convenience
from fmvpu.amlet.alu_instruction import ALUModes
from fmvpu.amlet.alu_lite_instruction import ALULiteModes
from fmvpu.amlet.ldst_instruction import LoadStoreModes
from fmvpu.amlet.packet_instruction import PacketModes
from fmvpu.amlet.control_instruction import ControlModes

# Legacy aliases for backward compatibility with tests
HaltInstruction = create_halt_instruction