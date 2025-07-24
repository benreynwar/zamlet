from typing import List, Tuple
from collections import deque
import logging
from random import Random
from dataclasses import dataclass
from enum import IntEnum

from cocotb.triggers import RisingEdge, ReadOnly

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields
from fmvpu.amlet.amlet_params import AmletParams


logger = logging.getLogger(__name__)


class PacketHeaderModes(IntEnum):
    NORMAL = 0
    COMMAND = 1
    APPEND = 2


class CommandTypes(IntEnum):
    START = 0
    WRITE_INSTRUCTION_MEMORY = 1
    WRITE_REGISTER = 2
    RESERVED = 3


@dataclass
class PacketHeader:
    """Packet header structure for amlet"""
    length: int  # packet length
    dest_x: int = 0  # destination x coordinate
    dest_y: int = 0  # destination y coordinate
    mode: PacketHeaderModes = PacketHeaderModes.NORMAL
    forward: bool = False
    is_broadcast: bool = False
    append_length: int = 0
    
    @classmethod
    def get_field_specs(cls) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('length', 8),
            ('dest_x', 8),
            ('dest_y', 8),
            ('mode', 2),
            ('forward', 1),
            ('is_broadcast', 1),
            ('append_length', 4),
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


def create_a_register_write_command_header(register: int, params: AmletParams = AmletParams()) -> int:
    """Create A-register write command header word (contains only register address)"""
    cmd = CommandTypes.WRITE_REGISTER << (params.width - 2)
    # A-registers have MSB = 0 (index < cutoff), so register address is just the register number
    reg_addr = register & ((1 << params.a_reg_width) - 1)
    cmd |= reg_addr & ((1 << params.b_reg_width) - 1)
    return cmd

def create_d_register_write_command_header(register: int, params: AmletParams = AmletParams()) -> int:
    """Create D-register write command header word (contains only register address)"""
    cmd = CommandTypes.WRITE_REGISTER << (params.width - 2)
    # D-registers have MSB = 1 (index >= cutoff), so set the cutoff bit and add register number
    cutoff = max(params.n_a_regs, params.n_d_regs)
    reg_addr = cutoff + (register & ((1 << params.d_reg_width) - 1))
    cmd |= reg_addr & ((1 << params.b_reg_width) - 1)
    return cmd


def create_instruction_memory_write_command(address: int, count: int, params: AmletParams = AmletParams()) -> int:
    """Create instruction memory write setup command word"""
    cmd = CommandTypes.WRITE_INSTRUCTION_MEMORY << (params.width - 2)
    cmd |= (count & 0xFF) << 16  # 8-bit count in bits 23-16
    cmd |= address & 0xFFFF  # 16-bit address in bits 15-0
    return cmd


def create_start_command(pc: int, params: AmletParams = AmletParams()) -> int:
    """Create start execution command word"""
    cmd = CommandTypes.START << (params.width - 2)
    cmd |= pc & ((1 << (params.width - 2)) - 1)
    return cmd


def create_d_register_write_packet(register: int, value: int, dest_x: int = 0, dest_y: int = 0, params: AmletParams = AmletParams(), is_broadcast: bool = False) -> list[int]:
    """Create a command packet to write a value to a D-register"""
    assert 0 <= register < params.n_d_regs, f"D-register {register} out of range [0, {params.n_d_regs})"
    assert 0 <= value < (1 << params.width), f"Value {value} too large for {params.width}-bit register"
    
    header = PacketHeader(
        length=2,  # Command header + data word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=PacketHeaderModes.COMMAND,
        is_broadcast=is_broadcast
    )
    command_header = create_d_register_write_command_header(register, params)
    return [header.encode(), command_header, value]

def create_a_register_write_packet(register: int, value: int, dest_x: int = 0, dest_y: int = 0, params: AmletParams = AmletParams(), is_broadcast: bool = False) -> list[int]:
    """Create a command packet to write a value to an A-register"""
    assert 0 <= register < params.n_a_regs, f"A-register {register} out of range [0, {params.n_a_regs})"
    assert 0 <= value < (1 << params.a_width), f"Value {value} too large for {params.a_width}-bit A-register"
    
    header = PacketHeader(
        length=2,  # Command header + data word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=PacketHeaderModes.COMMAND,
        is_broadcast=is_broadcast
    )
    command_header = create_a_register_write_command_header(register, params)
    return [header.encode(), command_header, value]


def pad_words_to_power_of_2(words: list[int]) -> list[int]:
    """Pad a list of words to the next power of 2 length"""
    if not words:
        return []
    
    target_length = 1
    while target_length < len(words):
        target_length *= 2
    
    # Pad with zeros
    padded_words = words.copy()
    while len(padded_words) < target_length:
        padded_words.append(0)
        
    return padded_words


def create_instruction_write_packet(instructions: list, base_address: int = 0, dest_x: int = 0, dest_y: int = 0, params: AmletParams = AmletParams()) -> list[int]:
    """Create a command packet to write multiple VLIWInstructions to instruction memory"""
    # Convert VLIWInstructions to words and pad each to power of 2 length
    instruction_words = []
    for instruction in instructions:
        words = instruction.to_words(params)
        padded_words = pad_words_to_power_of_2(words)
        instruction_words.extend(padded_words)
    
    # Create header: 1 setup command + len(instruction_words) data words  
    header = PacketHeader(
        length=1 + len(instruction_words),
        dest_x=dest_x,
        dest_y=dest_y,
        mode=PacketHeaderModes.COMMAND
    )
    
    # Create setup command word: [cmd_type][count][address]
    setup_command = create_instruction_memory_write_command(base_address, len(instruction_words), params)
    
    return [header.encode()] + [setup_command] + instruction_words


def create_start_packet(pc: int, dest_x: int = 0, dest_y: int = 0, params: AmletParams = AmletParams()) -> list[int]:
    """Create a command packet to start execution at a given PC"""
    header = PacketHeader(
        length=1,  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=PacketHeaderModes.COMMAND
    )
    command_word = create_start_command(pc, params)
    return [header.encode(), command_word]


def create_data_packet(data: list[int], dest_x: int = 0, dest_y: int = 0, forward: bool = False, append_length: int = 0) -> list[int]:
    """Create a data packet"""
    header = PacketHeader(
        length=len(data),
        dest_x=dest_x,
        dest_y=dest_y,
        mode=PacketHeaderModes.NORMAL,
        forward=forward,
        append_length=append_length,
    )
    return [header.encode()] + data


class PacketDriver:
    """Drives packets into a single network input"""
    
    def __init__(self, dut, seed, valid_signal, ready_signal, data_signal, isheader_signal, p_valid=0.5):
        self.dut = dut
        self.valid_signal = valid_signal
        self.ready_signal = ready_signal
        self.data_signal = data_signal
        self.isheader_signal = isheader_signal
        self.packet_queue: deque[List[int]] = deque()
        self.p_valid = p_valid
        self.rnd = Random(seed)
        
    def add_packet(self, packet: List[int]):
        """Add packet to the queue"""
        self.packet_queue.append(packet)
        
    async def drive_packets(self):
        await RisingEdge(self.dut.clock)
        """Drive packets from queue into the network input"""

        while True:
            if self.packet_queue:
                packet = self.packet_queue.popleft()
                
                for index, word in enumerate(packet):
                    # Set data, isheader, and valid
                    self.data_signal.value = word
                    self.isheader_signal.value = 1 if index == 0 else 0  # First word is header
                    while self.rnd.random() > self.p_valid:
                        self.valid_signal.value = 0
                        await RisingEdge(self.dut.clock)

                    self.valid_signal.value = 1
                    
                    # Wait for ready or just send
                    while True:
                        await ReadOnly()
                        if self.ready_signal.value == 1:
                            break
                        await RisingEdge(self.dut.clock)
                    await RisingEdge(self.dut.clock)
                    self.valid_signal.value = 0
            await RisingEdge(self.dut.clock)


class PacketReceiver:
    """Receives packets from a single network output"""
    
    def __init__(self, name, dut, seed, valid_signal, ready_signal, data_signal, isheader_signal, p_ready=0.5):
        self.name = name
        self.dut = dut
        self.valid_signal = valid_signal
        self.ready_signal = ready_signal
        self.data_signal = data_signal
        self.isheader_signal = isheader_signal
        self.received_packets: deque[List[int]] = deque()
        self.current_packet: List[int] = []
        self.rnd = Random(seed)
        self.p_ready = p_ready
        
    def has_packet(self) -> bool:
        """Check if a complete packet is available"""
        return len(self.received_packets) > 0
        
    def get_packet(self) -> List[int]:
        """Get the next complete packet"""
        return self.received_packets.popleft()
        
    async def receive_packets(self):
        """Receive packets from the network output"""
        while True:
            await RisingEdge(self.dut.clock)
            self.ready_signal.value = 1 if self.rnd.random() < self.p_ready else 0
            await ReadOnly()
            
            if (self.valid_signal.value == 1) and (self.ready_signal.value == 1):
                word = int(self.data_signal.value)
                is_header = int(self.isheader_signal.value)
                
                if is_header:
                    # Start of new packet
                    if self.current_packet:
                        # Save previous packet if exists
                        self.received_packets.append(self.current_packet)
                    self.current_packet = [word]
                    # Decode header to get expected length
                    header = PacketHeader.from_word(word)
                    self.expected_length = header.length + 1  # +1 for header
                else:
                    # Continue current packet
                    if self.current_packet:
                        self.current_packet.append(word)
                        
                # Check if packet is complete
                if len(self.current_packet) >= self.expected_length:
                    self.received_packets.append(self.current_packet)
                    self.current_packet = []


def packet_to_str(packet):
    """Convert packet to string for debugging"""
    if not packet:
        return "Empty packet"
    
    header = PacketHeader.from_word(packet[0])
    result = f"Packet(len={header.length}, dest=({header.dest_x},{header.dest_y}), mode={header.mode})"
    if len(packet) > 1:
        result += f" data={packet[1:]}"
    return result
