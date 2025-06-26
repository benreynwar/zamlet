from dataclasses import dataclass
import json
import math
from typing import Dict, Any
from fmvpu.test_utils import clog2


@dataclass
class FMVPUParams:
    """Python mirror of the Scala FMVPUParams case class with snake_case naming."""
    
    n_channels: int
    width: int
    # Max depth of the output buffers in the network node.
    network_memory_depth: int
    # Number of registers in the distributed register file.
    n_drf: int
    # Number of vectors stored in the distributed data memory.
    ddm_bank_depth: int
    ddm_n_banks: int
    ddm_addr_width: int
    # Number of entries in the network configuration.
    depth_network_config: int
    n_columns: int
    n_rows: int
    max_packet_length: int
    max_network_control_delay: int
    n_slow_network_control_slots: int
    n_fast_network_control_slots: int
    network_ident_width: int

    # Map camelCase JSON field names to snake_case Python field names
    _FIELD_MAPPING = {
        'nChannels': 'n_channels',
        'width': 'width',
        'networkMemoryDepth': 'network_memory_depth',
        'nDRF': 'n_drf',
        'ddmBankDepth': 'ddm_bank_depth',
        'ddmNBanks': 'ddm_n_banks',
        'ddmAddrWidth': 'ddm_addr_width',
        'depthNetworkConfig': 'depth_network_config',
        'nColumns': 'n_columns',
        'nRows': 'n_rows',
        'maxPacketLength': 'max_packet_length',
        'maxNetworkControlDelay': 'max_network_control_delay',
        'nSlowNetworkControlSlots': 'n_slow_network_control_slots',
        'nFastNetworkControlSlots': 'n_fast_network_control_slots',
        'networkIdentWidth': 'network_ident_width',
    }

    @classmethod
    def from_json(cls, json_str: str) -> 'FMVPUParams':
        """Create FMVPUParams from JSON string with camelCase field names."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_file(cls, filename: str) -> 'FMVPUParams':
        """Create FMVPUParams from JSON file with camelCase field names."""
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FMVPUParams':
        """Create FMVPUParams from dictionary with camelCase field names."""
        # Convert camelCase keys to snake_case
        converted_data = {}
        for camel_key, snake_key in cls._FIELD_MAPPING.items():
            if camel_key in data:
                converted_data[snake_key] = data[camel_key]
            else:
                raise KeyError(f"Missing required field '{camel_key}' in JSON data")
        
        return cls(**converted_data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with camelCase field names for JSON serialization."""
        # Convert snake_case keys to camelCase
        result = {}
        for camel_key, snake_key in self._FIELD_MAPPING.items():
            result[camel_key] = getattr(self, snake_key)
        
        return result

    def to_json(self, indent: int = None) -> str:
        """Convert to JSON string with camelCase field names."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_file(self, filename: str, indent: int = 2) -> None:
        """Write to JSON file with camelCase field names."""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=indent)

    @property
    def words_per_channel_slow_network_control(self) -> int:
        """Calculate words per channel slow network control."""
        from control_structures import ChannelSlowControl
        bits = ChannelSlowControl.width_bits(self)
        return (bits + self.width - 1) // self.width

    @property
    def words_per_general_slow_network_control(self) -> int:
        """Calculate words per general slow network control."""
        from control_structures import GeneralSlowControl
        bits = GeneralSlowControl.width_bits(self)
        return (bits + self.width - 1) // self.width

    @property
    def words_per_channel_fast_network_control(self) -> int:
        """Calculate words per channel fast network control."""
        from control_structures import ChannelFastControl
        bits = ChannelFastControl.width_bits(self)
        return (bits + self.width - 1) // self.width

    @property
    def words_per_general_fast_network_control(self) -> int:
        """Calculate words per general fast network control."""
        from control_structures import GeneralFastControl
        bits = GeneralFastControl.width_bits(self)
        return (bits + self.width - 1) // self.width

    @property
    def words_per_slow_network_control_slot(self) -> int:
        """Calculate words per slow network control slot (rounded up to power of 2)."""
        raw_words = self.words_per_general_slow_network_control + self.n_channels * self.words_per_channel_slow_network_control
        return 1 << math.ceil(math.log2(raw_words))

    @property
    def words_per_fast_network_control_slot(self) -> int:
        """Calculate words per fast network control slot (rounded up to power of 2)."""
        raw_words = self.words_per_general_fast_network_control + self.n_channels * self.words_per_channel_fast_network_control
        return 1 << math.ceil(math.log2(raw_words))

    @property
    def fast_network_control_offset(self) -> int:
        """Calculate offset for fast network control (after DDM space and slow control slots)."""
        # Calculate control memory start address (after DDM space)
        ddm_max_addr = self.ddm_bank_depth * self.ddm_n_banks
        control_mem_start = 1 << clog2(ddm_max_addr) if ddm_max_addr > 0 else 0
        # Add slow control slots
        return control_mem_start + self.n_slow_network_control_slots * self.words_per_slow_network_control_slot


