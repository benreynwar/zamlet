from dataclasses import dataclass
import math
from typing import Dict, Any


@dataclass
class LaneParams:
    """Python mirror of Scala LaneParams"""
    width: int = 32
    write_ident_width: int = 2
    n_regs: int = 8
    instruction_memory_depth: int = 64
    data_memory_depth: int = 64
    n_write_ports: int = 3
    
    # Instruction field widths
    alu_mode_width: int = 4
    ldst_mode_width: int = 2
    packet_mode_width: int = 3
    x_pos_width: int = 5
    y_pos_width: int = 5
    packet_length_width: int = 8
    address_width: int = 8
    instr_addr_width: int = 10
    
    # Special register assignments
    packet_word_out_reg_addr: int = 0
    accum_reg_addr: int = 1
    mask_reg_addr: int = 2
    base_addr_reg_addr: int = 3
    channel_reg_addr: int = 4
    
    # ALU configuration
    alu_latency: int = 1
    n_alu_rs_slots: int = 4
    
    # Load/Store configuration
    n_ldst_rs_slots: int = 4
    
    # Packet configuration
    n_packet_rs_slots: int = 2
    n_packet_out_idents: int = 4
    
    # Network configuration
    n_channels: int = 2
    
    instruction_width: int = 16
    
    @property
    def n_write_idents(self) -> int:
        return 1 << self.write_ident_width
    
    @property 
    def reg_addr_width(self) -> int:
        return math.ceil(math.log2(self.n_regs))
    
    @property
    def reg_with_ident_width(self) -> int:
        return self.reg_addr_width + self.write_ident_width
    
    @property
    def target_width(self) -> int:
        return self.x_pos_width + self.y_pos_width
    
    # Field mapping from camelCase JSON to snake_case Python
    _FIELD_MAPPING = {
        'width': 'width',
        'writeIdentWidth': 'write_ident_width',
        'nRegs': 'n_regs',
        'instructionMemoryDepth': 'instruction_memory_depth',
        'dataMemoryDepth': 'data_memory_depth',
        'nWritePorts': 'n_write_ports',
        'aluModeWidth': 'alu_mode_width',
        'ldstModeWidth': 'ldst_mode_width',
        'packetModeWidth': 'packet_mode_width',
        'xPosWidth': 'x_pos_width',
        'yPosWidth': 'y_pos_width',
        'packetLengthWidth': 'packet_length_width',
        'addressWidth': 'address_width',
        'instrAddrWidth': 'instr_addr_width',
        'packetWordOutRegAddr': 'packet_word_out_reg_addr',
        'accumRegAddr': 'accum_reg_addr',
        'maskRegAddr': 'mask_reg_addr',
        'baseAddrRegAddr': 'base_addr_reg_addr',
        'channelRegAddr': 'channel_reg_addr',
        'aluLatency': 'alu_latency',
        'nAluRsSlots': 'n_alu_rs_slots',
        'nLdstRsSlots': 'n_ldst_rs_slots',
        'nPacketRsSlots': 'n_packet_rs_slots',
        'nPacketOutIdents': 'n_packet_out_idents',
        'nChannels': 'n_channels',
        'instructionWidth': 'instruction_width',
    }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LaneParams':
        """Create LaneParams from dictionary with camelCase field names."""
        converted_data = {}
        for camel_key, snake_key in cls._FIELD_MAPPING.items():
            if camel_key in data:
                converted_data[snake_key] = data[camel_key]
        return cls(**converted_data)