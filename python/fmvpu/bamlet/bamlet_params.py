from dataclasses import dataclass
from typing import Dict, Any
from fmvpu.amlet.amlet_params import AmletParams


@dataclass
class BamletParams:
    """Python mirror of Scala BamletParams"""
    # Number of amlet columns and rows
    n_amlet_columns: int = 2
    n_amlet_rows: int = 1
    
    # Amlet parameters
    amlet: AmletParams = None
    
    # Instruction address width
    instr_addr_width: int = 16
    
    # Instruction memory depth
    instruction_memory_depth: int = 64
    
    def __post_init__(self):
        if self.amlet is None:
            self.amlet = AmletParams()
    
    @property
    def n_amlets(self) -> int:
        return self.n_amlet_columns * self.n_amlet_rows
    
    @property
    def a_width(self) -> int:
        return self.amlet.a_width
    
    @property
    def n_loop_levels(self) -> int:
        return self.amlet.n_loop_levels
    
    # Field mapping from camelCase JSON to snake_case Python
    _FIELD_MAPPING = {
        'nAmletColumns': 'n_amlet_columns',
        'nAmletRows': 'n_amlet_rows',
        'amlet': 'amlet',
        'instrAddrWidth': 'instr_addr_width',
        'instructionMemoryDepth': 'instruction_memory_depth',
    }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BamletParams':
        """Create BamletParams from dictionary with camelCase field names."""
        converted_data = {}
        for camel_key, snake_key in cls._FIELD_MAPPING.items():
            if camel_key in data:
                if camel_key == 'amlet':
                    # Convert nested amlet params
                    converted_data[snake_key] = AmletParams.from_dict(data[camel_key])
                else:
                    converted_data[snake_key] = data[camel_key]
        return cls(**converted_data)