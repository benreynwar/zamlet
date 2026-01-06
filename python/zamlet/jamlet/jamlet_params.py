from dataclasses import dataclass
from typing import Dict, Any, List, Tuple
import math


@dataclass
class JamletParams:
    """Python mirror of Scala JamletParams for hardware tests."""
    # Position widths
    x_pos_width: int = 8
    y_pos_width: int = 8

    # Grid dimensions
    k_cols: int = 2
    k_rows: int = 1
    j_cols: int = 1
    j_rows: int = 1

    # Word width
    word_bytes: int = 8

    # SRAM configuration
    sram_depth: int = 256
    cache_slot_words: int = 16

    # Register file slice
    rf_slice_words: int = 48

    # Address and index widths
    mem_addr_width: int = 48
    page_words_per_jamlet: int = 4
    element_index_width: int = 22

    # WitemTable configuration
    witem_table_depth: int = 16

    # Instruction identifier
    ident_width: int = 7

    # Network configuration
    n_a_channels: int = 1
    n_b_channels: int = 1

    # Derived properties
    @property
    def j_in_k(self) -> int:
        return self.j_cols * self.j_rows

    @property
    def k_in_l(self) -> int:
        return self.k_cols * self.k_rows

    @property
    def j_in_l(self) -> int:
        return self.j_in_k * self.k_in_l

    @property
    def j_total_cols(self) -> int:
        return self.j_cols * self.k_cols

    @property
    def j_total_rows(self) -> int:
        return self.j_rows * self.k_rows

    @property
    def word_width(self) -> int:
        return self.word_bytes * 8

    @property
    def sram_addr_width(self) -> int:
        return (self.sram_depth - 1).bit_length()

    @property
    def rf_addr_width(self) -> int:
        return (self.rf_slice_words - 1).bit_length()

    @property
    def n_cache_slots(self) -> int:
        return self.sram_depth // self.cache_slot_words

    @property
    def cache_slot_width(self) -> int:
        return (self.n_cache_slots - 1).bit_length()

    @property
    def log2_j_in_l(self) -> int:
        return self.j_in_l.bit_length() - 1

    @property
    def log2_word_width(self) -> int:
        return self.word_width.bit_length() - 1

    @property
    def log2_word_bytes(self) -> int:
        return self.word_bytes.bit_length() - 1

    @property
    def base_bit_addr_width(self) -> int:
        """Width of baseBitAddr field = log2Ceil(wordWidth * jInL)."""
        return (self.word_width * self.j_in_l - 1).bit_length()

    # Field mapping from camelCase JSON to snake_case Python
    _FIELD_MAPPING = {
        'xPosWidth': 'x_pos_width',
        'yPosWidth': 'y_pos_width',
        'kCols': 'k_cols',
        'kRows': 'k_rows',
        'jCols': 'j_cols',
        'jRows': 'j_rows',
        'wordBytes': 'word_bytes',
        'sramDepth': 'sram_depth',
        'cacheSlotWords': 'cache_slot_words',
        'rfSliceWords': 'rf_slice_words',
        'memAddrWidth': 'mem_addr_width',
        'pageWordsPerJamlet': 'page_words_per_jamlet',
        'elementIndexWidth': 'element_index_width',
        'witemTableDepth': 'witem_table_depth',
        'identWidth': 'ident_width',
        'nAChannels': 'n_a_channels',
        'nBChannels': 'n_b_channels',
    }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JamletParams':
        """Create JamletParams from dictionary with camelCase field names."""
        converted_data = {}
        for camel_key, snake_key in cls._FIELD_MAPPING.items():
            if camel_key in data:
                converted_data[snake_key] = data[camel_key]
        return cls(**converted_data)
