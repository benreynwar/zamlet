from typing import List, Tuple
from collections import deque
import logging
from random import Random
from dataclasses import dataclass, fields
from enum import IntEnum

from cocotb.triggers import RisingEdge, ReadOnly

from zamlet.control_structures import pack_fields_to_words, unpack_words_to_fields
from zamlet.amlet.amlet_params import AmletParams


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


def create_register_write_command_header(reg_type: str, register: int, params: AmletParams = AmletParams()) -> int:
    """Create register write command header word"""
    # Validate and encode based on register type
    if reg_type == 'a':
        type_bits = 0
        assert 0 <= register < params.n_a_regs
    elif reg_type == 'd':
        type_bits = 1
        assert 0 <= register < params.n_d_regs
    elif reg_type == 'p':
        type_bits = 2
        assert 0 <= register < params.n_p_regs
    elif reg_type == 'g':
        type_bits = 3
        assert 0 <= register < params.n_g_regs
    else:
        assert False, f"Invalid register type '{reg_type}'. Must be 'a', 'd', 'p', or 'g'"
    
    # Encode register address with 2-bit type prefix
    encoded_register = (type_bits << (params.reg_width - 2)) | register
    
    cmd = CommandTypes.WRITE_REGISTER << (params.width - 2)
    cmd |= encoded_register
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


def create_register_write_packet(register: int, value: int, reg_type: str, dest_x: int = 0, dest_y: int = 0, params: AmletParams = AmletParams(), is_broadcast: bool = False) -> list[int]:
    """Create a command packet to write a value to a register
    
    Args:
        register: Register index within the register type
        value: Value to write 
        reg_type: Register type - 'a', 'd', 'p', or 'g'
    """
    header = PacketHeader(
        length=2,  # Command header + data word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=PacketHeaderModes.COMMAND,
        is_broadcast=is_broadcast
    )
    command_header = create_register_write_command_header(reg_type, register, params)
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

    logger.info(f'create_instruction_write_packet: packet has length {1 + len(instruction_words)}')
    logger.info(f'content is {[hex(x) for x in instruction_words]}')
    
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
    
    def __init__(self, dut, seed, valid_signal, ready_signal, data_signal, isheader_signal,
                 p_valid=0.5, name='none'):
        self.dut = dut
        self.valid_signal = valid_signal
        self.ready_signal = ready_signal
        self.data_signal = data_signal
        self.isheader_signal = isheader_signal
        self.packet_queue: deque[List[int]] = deque()
        self.p_valid = p_valid
        self.rnd = Random(seed)
        self.empty = True
        self.name = name
        
    def add_packet(self, packet: List[int]):
        """Add packet to the queue"""
        logger.info(f'Added a packet to {self.name}.  {packet}')
        self.packet_queue.append(packet)
        self.empty = False
        
    async def drive_packets(self):
        await RisingEdge(self.dut.clock)
        """Drive packets from queue into the network input"""

        while True:
            if self.packet_queue:
                self.empty = False
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
            else:
                self.empty = True
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


def make_coord_register(x: int, y: int, params: AmletParams = AmletParams()) -> int:
    """Create coordinate register value: (y << x_pos_width) | x"""
    return (y << params.x_pos_width) | x


def make_write_args_packets(params: AmletParams, args, regs, broadcast_coord, amlet_coords=None):
    """
    `args` is a dataclass with arguments for the kernel.
    `regs` is a dataclass with registers for the kernel.
    """
    cutoff = max(params.n_a_regs, params.n_d_regs)
    # Arguments that are the same for all the amlets and can be broadcast
    broadcast_key_value_pairs = []
    # Arguments that need to be sent individually to each amlet.
    if amlet_coords is None:
        unique_key_value_pairs = None
    else:
        unique_key_value_pairs = [[] for i in range(len(amlet_coords))]
    for field in fields(args):
        reg_index = getattr(regs, field.name)
        value = getattr(args, field.name)
        if field.name[0:2] == 'a_':
            reg_key = ('a', reg_index)
        elif field.name[0:2] == 'd_':
            reg_key = ('d', reg_index)
        elif field.name[0:2] == 'g_':
            reg_key = ('g', reg_index)
        else:
            raise ValueError(f'Field must start width a_ or d_ but name is {field.name}')
        if isinstance(value, list):
            assert amlet_coords is not None
            assert len(amlet_coords) == len(value)
            for index, subvalue in enumerate(value):
                if field.name[0:2] in ('a_', 'g_'):
                    assert 0 <= subvalue < pow(2, params.a_width)
                else:
                    assert 0 <= subvalue < pow(2, params.width)
                unique_key_value_pairs[index].append((reg_key, subvalue))
        else:
            if field.name[0:2] in ('a_', 'g_'):
                assert 0 <= value < pow(2, params.a_width)
            else:
                assert 0 <= value < pow(2, params.width)
            broadcast_key_value_pairs.append((reg_key, value))
    header = PacketHeader(
        length=2*len(broadcast_key_value_pairs),
        dest_x=broadcast_coord[0],
        dest_y=broadcast_coord[1],
        mode=PacketHeaderModes.COMMAND,
        is_broadcast=True,
    )
    broadcast_packet = [header.encode()]
    for reg_key, value in broadcast_key_value_pairs:
        reg_type, register = reg_key
        command_header = create_register_write_command_header(reg_type, register, params)
        broadcast_packet += [command_header, value]
    unique_packets = []
    for coords, key_value_pairs in zip(amlet_coords, unique_key_value_pairs):
        header = PacketHeader(
            length=2*len(key_value_pairs),
            dest_x=coords[0],
            dest_y=coords[1],
            mode=PacketHeaderModes.COMMAND,
            is_broadcast=False,
        )
        packet = [header.encode()]
        for reg_key, value in key_value_pairs:
            reg_type, register = reg_key
            command_header = create_register_write_command_header(reg_type, register, params)
            packet += [command_header, value]
        unique_packets.append(packet)
    return broadcast_packet, unique_packets

