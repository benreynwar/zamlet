from dataclasses import dataclass
from typing import Dict, Any

from fmvpu.lane.lane_params import LaneParams


@dataclass
class LaneArrayParams:
    """Python mirror of Scala LaneArrayParams"""
    n_columns: int = 4
    n_rows: int = 4
    lane: LaneParams = None
    
    def __post_init__(self):
        if self.lane is None:
            self.lane = LaneParams()
    
    @property
    def n_lanes(self) -> int:
        return self.n_columns * self.n_rows
    
    # Field mapping from camelCase JSON to Python
    _FIELD_MAPPING = {
        'nColumns': 'n_columns',
        'nRows': 'n_rows',
        'lane': 'lane',
    }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LaneArrayParams':
        """Create LaneArrayParams from dictionary with camelCase field names."""
        converted_data = {}
        
        # Handle basic fields
        for camel_key, python_key in cls._FIELD_MAPPING.items():
            if camel_key in data:
                if camel_key == 'lane':
                    # Handle nested LaneParams
                    converted_data[python_key] = LaneParams.from_dict(data[camel_key])
                else:
                    converted_data[python_key] = data[camel_key]
        
        return cls(**converted_data)
