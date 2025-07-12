from dataclasses import dataclass
import math


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