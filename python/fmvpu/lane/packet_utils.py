from typing import List, Tuple
from collections import deque
import logging
from random import Random
from dataclasses import dataclass
from enum import IntEnum

from cocotb.triggers import RisingEdge, ReadOnly

from fmvpu.control_structures import pack_fields_to_words, unpack_words_to_fields
from fmvpu.lane.lane_params import LaneParams


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
    """Packet header structure"""
    length: int  # 8 bits
    dest_x: int = 0  # 5 bits (assuming 32 max)
    dest_y: int = 0  # 5 bits
    mode: PacketHeaderModes = PacketHeaderModes.NORMAL  # 1 bit (0=normal, 1=command)
    forward: bool = False  # 1 bit
    is_broadcast: bool = False  # 1 bit  
    append_length: int = 0 # 8 bits
    
    @classmethod
    def get_field_specs(cls) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        return [
            ('length', 8),
            ('dest_x', 5),
            ('dest_y', 5),
            ('mode', 2),
            ('forward', 1),
            ('is_broadcast', 1),
            ('append_length', 8),
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


def create_register_write_packet(register: int, value: int, dest_x: int = 0, dest_y: int = 0, params: LaneParams = LaneParams()) -> list[int]:
    """Create a command packet to write a value to a register"""
    header = PacketHeader(
        length=1,  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=PacketHeaderModes.COMMAND
    )
    command_word = create_register_write_command(register, value, params)
    return [header.encode(), command_word]


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


def packet_to_str(packet):
    header = PacketHeader.from_word(packet[0])
    as_str = f'{header} {packet[1:]}'
    return as_str


class PacketReceiver:
    """Receives packets from a single network output"""
    
    def __init__(self, dut, seed: int, valid_signal, ready_signal, data_signal, isheader_signal, params: LaneParams = LaneParams(), p_ready=0.5, name=''):
        self.dut = dut
        self.valid_signal = valid_signal
        self.ready_signal = ready_signal
        self.data_signal = data_signal
        self.isheader_signal = isheader_signal
        self.params = params
        self.received_packets: deque[List[int]] = deque()
        self.rnd = Random(seed)
        self.p_ready = p_ready
        self.name = name

    def has_packet(self) -> bool:
        return len(self.received_packets) > 0
        
    def get_packet(self) -> List[int]:
        """Get the next received packet"""
        if self.received_packets:
            return self.received_packets.popleft()
        return None
        
    async def receive_packets(self):
        """Receive packets from the network output"""
        self.ready_signal.value = 1
        
        current_packet = None
        remaining_words = 0
        
        while True:
            await RisingEdge(self.dut.clock)
            if self.rnd.random() > self.p_ready:
                self.ready_signal.value = 0
            else:
                self.ready_signal.value = 1
            await ReadOnly()
            if (self.valid_signal.value == 1) and (self.ready_signal.value == 1):
                word = int(self.data_signal.value)

                if current_packet is None:
                    assert self.isheader_signal.value == 1, "Expected header bit to be set for first word"
                    header = PacketHeader.from_word(word)
                    remaining_words = header.length
                    logger.info(f'{self.name}: Got a packet header with length {header.length} dest ({header.dest_x}, {header.dest_y})')
                    current_packet = [word]
                else:
                    current_packet.append(word)
                    remaining_words -= 1
                if remaining_words == 0:
                    self.received_packets.append(current_packet)
                    current_packet = None

