from dataclasses import dataclass
import math
from typing import Dict, Any


@dataclass
class AmletParams:
    """Python mirror of Scala AmletParams"""
    # Width of the words in the ALU and Network
    width: int = 32
    
    # The width of the register rename tag identifier
    reg_tag_width: int = 2
    
    # Similar but for masks
    m_ident_width: int = 3
    
    # Width of the words in the ALULite
    a_width: int = 16
    
    # Number of data registers
    n_d_regs: int = 16
    
    # Number of address registers
    n_a_regs: int = 16

    # Number of global registers
    n_g_regs: int = 16
    
    # Depth of the data memory
    data_memory_depth: int = 64
    
    # Number of result bus ports for completion events
    n_result_ports: int = 4
    
    # Maximum number of nested loop levels supported
    n_loop_levels: int = 4
    
    # Width of coordinates
    x_pos_width: int = 8
    y_pos_width: int = 8
    
    # Width to describe length of a packet
    packet_length_width: int = 8
    
    # ALU configuration
    alu_latency: int = 1
    n_alu_rs_slots: int = 4
    
    # ALULite configuration
    n_alu_lite_rs_slots: int = 4
    
    # ALU Predicate configuration
    alu_predicate_latency: int = 1
    n_alu_predicate_rs_slots: int = 4
    
    # Predicate register configuration
    n_p_regs: int = 16
    n_p_tags: int = 4
    
    # Load Store configuration
    n_load_store_rs_slots: int = 4
    
    # Packet configuration
    n_send_packet_rs_slots: int = 2
    n_receive_packet_rs_slots: int = 2
    n_packet_out_idents: int = 4
    
    # Network configuration
    n_channels: int = 2

    instr_addr_width: int = 16
    
    @property
    def n_write_idents(self) -> int:
        return 1 << self.reg_tag_width
    
    @property
    def a_reg_width(self) -> int:
        return math.ceil(math.log2(self.n_a_regs))
    
    @property
    def d_reg_width(self) -> int:
        return math.ceil(math.log2(self.n_d_regs))
    
    @property
    def b_reg_width(self) -> int:
        return max(self.a_reg_width, self.d_reg_width) + 1
    
    @property
    def p_reg_width(self) -> int:
        return math.ceil(math.log2(self.n_p_regs))
    
    @property
    def addr_width(self) -> int:
        return math.ceil(math.log2(self.data_memory_depth))

    @property
    def reg_cutoff(self) -> int:
        return max([self.n_a_regs, self.n_d_regs, self.n_g_regs])
    
    # Field mapping from camelCase JSON to snake_case Python
    _FIELD_MAPPING = {
        'width': 'width',
        'regTagWidth': 'reg_tag_width',
        'mIdentWidth': 'm_ident_width',
        'aWidth': 'a_width',
        'nDRegs': 'n_d_regs',
        'nARegs': 'n_a_regs',
        'nGRegs': 'n_g_regs',
        'dataMemoryDepth': 'data_memory_depth',
        'nResultPorts': 'n_result_ports',
        'nLoopLevels': 'n_loop_levels',
        'xPosWidth': 'x_pos_width',
        'yPosWidth': 'y_pos_width',
        'packetLengthWidth': 'packet_length_width',
        'aluLatency': 'alu_latency',
        'nAluRSSlots': 'n_alu_rs_slots',
        'nAluLiteRSSlots': 'n_alu_lite_rs_slots',
        'aluPredicateLatency': 'alu_predicate_latency',
        'nAluPredicateRSSlots': 'n_alu_predicate_rs_slots',
        'nPRegs': 'n_p_regs',
        'nPTags': 'n_p_tags',
        'nLoadStoreRSSlots': 'n_load_store_rs_slots',
        'nSendPacketRSSlots': 'n_send_packet_rs_slots',
        'nReceivePacketRSSlots': 'n_receive_packet_rs_slots',
        'nPacketOutIdents': 'n_packet_out_idents',
        'nChannels': 'n_channels',
        'instrAddrWidth': 'instr_addr_width',
    }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AmletParams':
        """Create AmletParams from dictionary with camelCase field names."""
        converted_data = {}
        for camel_key, snake_key in cls._FIELD_MAPPING.items():
            if camel_key in data:
                converted_data[snake_key] = data[camel_key]
        return cls(**converted_data)
