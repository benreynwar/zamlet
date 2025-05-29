from dataclasses import dataclass
import json
from typing import Dict, Any


@dataclass
class FMPVUParams:
    """Python mirror of the Scala FMPVUParams case class with snake_case naming."""
    
    n_buses: int
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

    # Map camelCase JSON field names to snake_case Python field names
    _FIELD_MAPPING = {
        'nBuses': 'n_buses',
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
    }

    @classmethod
    def from_json(cls, json_str: str) -> 'FMPVUParams':
        """Create FMPVUParams from JSON string with camelCase field names."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_file(cls, filename: str) -> 'FMPVUParams':
        """Create FMPVUParams from JSON file with camelCase field names."""
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FMPVUParams':
        """Create FMPVUParams from dictionary with camelCase field names."""
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
