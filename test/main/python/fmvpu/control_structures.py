from dataclasses import dataclass
from typing import List, Tuple
import math

from params import FMVPUParams


def pack_value_to_bits(value, width: int) -> List[bool]:
    """Pack a value into a list of bits (LSB first)."""
    bits = []
    for i in range(width):
        bits.append((value >> i) & 1 == 1)
    return bits


def pack_fields_to_bits(obj, field_specs: List[Tuple[str, int]]) -> List[bool]:
    """Pack object fields into a list of bits using field specifications.
    
    Args:
        obj: Object containing the fields
        field_specs: List of (field_name, bit_width) tuples
    
    Returns:
        List of bits (LSB first), packed in reverse field order to match Chisel's asUInt behavior
    """
    all_bits = []
    
    # Pack fields in reverse order to match Chisel's Bundle.asUInt behavior
    for field_name, bit_width in reversed(field_specs):
        value = getattr(obj, field_name)
        
        if isinstance(value, bool):
            all_bits.append(value)
        elif isinstance(value, int):
            all_bits.extend(pack_value_to_bits(value, bit_width))
        elif isinstance(value, list):
            if isinstance(value[0], bool):
                all_bits.extend(value)
            elif isinstance(value[0], int):
                for item in value:
                    all_bits.extend(pack_value_to_bits(item, bit_width // len(value)))
            else:
                raise ValueError(f"Unsupported list type for field {field_name}")
        else:
            raise ValueError(f"Unsupported field type for {field_name}: {type(value)}")
    
    return all_bits


def pack_bits_to_words(bits: List[bool], word_width: int = 32) -> List[int]:
    """Pack a list of bits into words."""
    words = []
    for i in range(0, len(bits), word_width):
        word = 0
        for j in range(min(word_width, len(bits) - i)):
            if bits[i + j]:
                word |= (1 << j)
        words.append(word)
    return words


def pack_fields_to_words(obj, field_specs: List[Tuple[str, int]], word_width: int = 32) -> List[int]:
    """Pack object fields into words using field specifications."""
    bits = pack_fields_to_bits(obj, field_specs)
    return pack_bits_to_words(bits, word_width)


def calculate_total_width(field_specs: List[Tuple[str, int]]) -> int:
    """Calculate total width in bits from field specifications."""
    return sum(width for _, width in field_specs)


@dataclass
class ChannelSlowControl:
    """Python mirror of the Scala ChannelSlowControl bundle."""
    is_packet_mode: bool
    delays: List[int]  # 4 elements for N,S,W,E directions
    is_output_delay: bool
    n_drive: List[bool]  # per channel
    s_drive: List[bool]  # per channel  
    w_drive: List[bool]  # per channel
    e_drive: List[bool]  # per channel
    ns_input_sel_delay: int
    we_input_sel_delay: int
    ns_crossbar_sel_delay: int
    we_crossbar_sel_delay: int

    @classmethod
    def default(cls, params: FMVPUParams) -> 'ChannelSlowControl':
        """Create default ChannelSlowControl with packet mode enabled."""
        return cls(
            is_packet_mode=True,
            delays=[0, 0, 0, 0],
            is_output_delay=False,
            n_drive=[False] * params.n_channels,
            s_drive=[False] * params.n_channels,
            w_drive=[False] * params.n_channels,
            e_drive=[False] * params.n_channels,
            ns_input_sel_delay=0,
            we_input_sel_delay=0,
            ns_crossbar_sel_delay=0,
            we_crossbar_sel_delay=0
        )

    @classmethod
    def static_mode(cls, params: FMVPUParams) -> 'ChannelSlowControl':
        """Create ChannelSlowControl configured for static mode."""
        return cls(
            is_packet_mode=False,
            delays=[0, 0, 0, 0],
            is_output_delay=False,
            n_drive=[True] * params.n_channels,  # Enable all drives for static mode
            s_drive=[True] * params.n_channels,
            w_drive=[True] * params.n_channels,
            e_drive=[True] * params.n_channels,
            ns_input_sel_delay=0,
            we_input_sel_delay=0,
            ns_crossbar_sel_delay=0,
            we_crossbar_sel_delay=0
        )

    @classmethod
    def get_field_specs(cls, params: FMVPUParams) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        delay_field_bits = math.ceil(math.log2(params.network_memory_depth + 1))
        control_delay_bits = math.ceil(math.log2(params.max_network_control_delay + 1))
        
        return [
            ('is_packet_mode', 1),
            ('delays', 4 * delay_field_bits),
            ('is_output_delay', 1),
            ('n_drive', params.n_channels),
            ('s_drive', params.n_channels),
            ('w_drive', params.n_channels),
            ('e_drive', params.n_channels),
            ('ns_input_sel_delay', control_delay_bits),
            ('we_input_sel_delay', control_delay_bits),
            ('ns_crossbar_sel_delay', control_delay_bits),
            ('we_crossbar_sel_delay', control_delay_bits),
        ]

    @classmethod
    def width_bits(cls, params: FMVPUParams) -> int:
        """Calculate width in bits."""
        return calculate_total_width(cls.get_field_specs(params))

    def to_words(self, params: FMVPUParams) -> List[int]:
        """Convert to list of words."""
        return pack_fields_to_words(self, self.get_field_specs(params), params.width)


@dataclass
class GeneralSlowControl:
    """Python mirror of the Scala GeneralSlowControl bundle."""
    drf_sel_delay: int
    ddm_sel_delay: int

    @classmethod
    def default(cls) -> 'GeneralSlowControl':
        """Create default GeneralSlowControl."""
        return cls(
            drf_sel_delay=0,
            ddm_sel_delay=0
        )

    @classmethod
    def get_field_specs(cls, params: FMVPUParams) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        delay_bits = math.ceil(math.log2(params.max_network_control_delay + 1))
        
        return [
            ('drf_sel_delay', delay_bits),
            ('ddm_sel_delay', delay_bits),
        ]

    @classmethod
    def width_bits(cls, params: FMVPUParams) -> int:
        """Calculate width in bits."""
        return calculate_total_width(cls.get_field_specs(params))

    def to_words(self, params: FMVPUParams) -> List[int]:
        """Convert to list of words."""
        return pack_fields_to_words(self, self.get_field_specs(params), params.width)


@dataclass
class NetworkSlowControl:
    """Python mirror of the Scala NetworkSlowControl bundle."""
    channels: List[ChannelSlowControl]
    general: GeneralSlowControl

    @classmethod
    def default(cls, params: FMVPUParams) -> 'NetworkSlowControl':
        """Create default NetworkSlowControl with all channels in packet mode."""
        return cls(
            channels=[ChannelSlowControl.default(params) for _ in range(params.n_channels)],
            general=GeneralSlowControl.default()
        )


@dataclass
class ChannelFastControl:
    """Python mirror of the Scala ChannelFastControl bundle."""
    ns_input_sel: bool
    we_input_sel: bool
    ns_crossbar_sel: int
    we_crossbar_sel: int

    @classmethod
    def default(cls) -> 'ChannelFastControl':
        """Create default ChannelFastControl."""
        return cls(
            ns_input_sel=False,
            we_input_sel=False,
            ns_crossbar_sel=0,
            we_crossbar_sel=0
        )

    @classmethod
    def get_field_specs(cls, params: FMVPUParams) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        crossbar_sel_bits = math.ceil(math.log2(params.n_channels + 2))
        
        return [
            ('ns_input_sel', 1),
            ('we_input_sel', 1),
            ('ns_crossbar_sel', crossbar_sel_bits),
            ('we_crossbar_sel', crossbar_sel_bits),
        ]

    @classmethod
    def width_bits(cls, params: FMVPUParams) -> int:
        """Calculate width in bits."""
        return calculate_total_width(cls.get_field_specs(params))

    def to_words(self, params: FMVPUParams) -> List[int]:
        """Convert to list of words."""
        return pack_fields_to_words(self, self.get_field_specs(params), params.width)


@dataclass
class GeneralFastControl:
    """Python mirror of the Scala GeneralFastControl bundle."""
    drf_sel: int
    ddm_sel: int

    @classmethod
    def default(cls) -> 'GeneralFastControl':
        """Create default GeneralFastControl."""
        return cls(
            drf_sel=0,
            ddm_sel=0
        )

    @classmethod
    def get_field_specs(cls, params: FMVPUParams) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing."""
        sel_bits = math.ceil(math.log2(params.n_channels * 2))
        
        return [
            ('drf_sel', sel_bits),
            ('ddm_sel', sel_bits),
        ]

    @classmethod
    def width_bits(cls, params: FMVPUParams) -> int:
        """Calculate width in bits."""
        return calculate_total_width(cls.get_field_specs(params))

    def to_words(self, params: FMVPUParams) -> List[int]:
        """Convert to list of words."""
        return pack_fields_to_words(self, self.get_field_specs(params), params.width)


@dataclass
class NetworkFastControl:
    """Python mirror of the Scala NetworkFastControl bundle."""
    channels: List[ChannelFastControl]
    general: GeneralFastControl

    @classmethod
    def default(cls, params: FMVPUParams) -> 'NetworkFastControl':
        """Create default NetworkFastControl."""
        return cls(
            channels=[ChannelFastControl.default() for _ in range(params.n_channels)],
            general=GeneralFastControl.default()
        )

    def to_words(self, params: FMVPUParams) -> List[int]:
        """Convert to list of words."""
        config_words = []
        # Pack general config first, then all channels
        config_words.extend(self.general.to_words(params))
        for channel_config in self.channels:
            config_words.extend(channel_config.to_words(params))
        return config_words
