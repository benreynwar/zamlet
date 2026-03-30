import logging
import math
from dataclasses import dataclass
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass
class ZamletParams:
    #k_cols: int = 2
    #k_rows: int = 2

    #j_cols: int = 2
    #j_rows: int = 2

    k_cols: int = 2
    k_rows: int = 1

    j_cols: int = 1
    j_rows: int = 1

    n_vregs: int = 40
    cache_slot_words_per_jamlet: int = 2
    word_bytes: int = 8
    page_words_per_jamlet: int = 64
    scalar_memory_bytes: int = 8 << 20
    kamlet_memory_bytes: int = 1 << 20
    #jamlet_sram_bytes: int = 1 << 10
    sram_depth: int = 8
    tohost_addr: int = 0x80001000
    fromhost_addr: int = 0x80001040
    receive_buffer_depth: int = 16
    router_output_buffer_length: int = 2
    router_input_buffer_length: int = 2
    instruction_queue_length: int = 16
    n_ident_query_slots: int = 8
    n_a_channels: int = 1
    n_b_channels: int = 1


    instruction_buffer_length: int = 16
    instructions_in_packet: int = 4
    n_response_idents: int = 32
    #n_waiting: int = 16
    n_response_tags: int = 8
    max_response_tags: int = 512
    sync_ident_width: int = 10
    sync_bus_width: int = 11

    # The number of outstanding instructions or responses waiting
    witem_table_depth: int = 16
    # Number of witem slots reserved for message handlers (not used by kinstructions)
    n_items_reserved: int = 8
    # The number of outstanding cache read_line and write_line allowed
    n_cache_requests: int = 16
    # Number of gathering slots in memlet for WRITE_LINE_READ_LINE operations
    n_memlet_gathering_slots: int = 4

    # Max in-flight channel 1+ packets per jamlet (0 = unlimited).
    # Limits how many request packets a jamlet can have outstanding in the
    # network. May be useful for limiting congestion.
    max_in_flight_ch1: int = 0

    # Ordered indexed operation buffer parameters (for scalar memory targets)
    n_ordered_buffers: int = 2
    ordered_buffer_capacity: int = 16

    # Bit widths for RTL header encoding/decoding
    x_pos_width: int = 8
    y_pos_width: int = 8
    ident_width: int = 7
    rf_slice_words: int = 48
    mem_addr_width: int = 48
    element_index_width: int = 22
    n_response_buffer_slots: int = 4
    mem_beat_words: int = 1
    mem_axi_id_bits: int = 4
    lamlet_dispatch_queue_depth: int = 8

    def __post_init__(self):
        # Page must be bigger than a vector
        assert self.page_bytes > 0
        assert self.page_bytes % self.maxvl_bytes == 0
        # Vector must be a multiple of words per jamlet
        assert self.maxvl_bytes > 0
        assert self.maxvl_bytes % (self.k_cols*self.k_rows*self.j_cols*self.j_rows*self.word_bytes) == 0
        # Cache line must be bigger than 1 word per jamlet in a kamlet
        assert self.cache_line_bytes > 0
        assert self.cache_line_bytes % (self.j_cols*self.j_rows*self.word_bytes) == 0
        # Page must be bigger than a cache line
        assert self.page_bytes >= self.k_in_l * self.cache_line_bytes
        assert self.page_bytes % (self.k_in_l * self.cache_line_bytes) == 0
        # Sync ident must fit in one bus cycle (data_width = sync_bus_width - 1)
        assert self.sync_ident_width + 1 <= self.sync_bus_width
        # Ident space must cover all response tags + ident query
        assert (1 << self.sync_ident_width) > self.max_response_tags
        # Sane scalar memory
        assert self.scalar_memory_bytes > self.cache_line_bytes
        assert self.scalar_memory_bytes % self.cache_line_bytes == 0
        # Sane kamlet memory
        assert self.kamlet_memory_bytes > self.cache_line_bytes
        assert self.kamlet_memory_bytes % self.cache_line_bytes == 0

    @property
    def cache_slot_words(self) -> int:
        return self.cache_slot_words_per_jamlet * self.j_in_k

    @property
    def cache_line_bytes(self) -> int:
        return self.cache_slot_words * self.word_bytes

    @property
    def k_vline_bytes(self) -> int:
        return self.j_in_k * self.word_bytes

    @property
    def maxvl_bytes(self):
        return self.j_in_l * self.word_bytes

    @property
    def k_in_l(self):
        return self.k_cols * self.k_rows

    @property
    def j_in_k(self):
        return self.j_cols * self.j_rows

    @property
    def j_in_l(self):
        return self.j_in_k * self.k_in_l

    @property
    def vline_bytes(self):
        return self.j_in_l * self.word_bytes

    @property
    def send_read_line_j_index(self):
        return 1 % self.j_in_k

    @property
    def jamlet_sram_bytes(self):
        return self.sram_depth * self.word_bytes

    @property
    def sram_addr_width(self):
        return int(math.log2(self.sram_depth))

    @property
    def vlines_in_cache_line(self):
        logger.warning(
            "vlines_in_cache_line is deprecated, use cache_slot_words_per_jamlet instead"
        )
        return self.cache_slot_words_per_jamlet

    @property
    def page_bytes(self):
        return self.page_words_per_jamlet * self.word_bytes * self.j_in_l

    @property
    def n_items(self):
        logger.warning("n_items is deprecated, use witem_table_depth instead")
        return self.witem_table_depth

    @property
    def n_channels(self):
        return self.n_a_channels + self.n_b_channels

    @property
    def word_width(self) -> int:
        return self.word_bytes * 8

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
    def base_bit_addr_width(self) -> int:
        return (self.word_width * self.j_in_l - 1).bit_length()

    @property
    def west_offset(self) -> int:
        """Number of memlet columns on the left (west) side of the grid.

        Routing coords place these at x=0..west_offset-1, so the jamlet
        grid starts at routing x = west_offset.
        """
        n_left_cols = self.k_cols // 2
        n_left_memlets = n_left_cols * self.k_rows
        edge_height = self.k_rows * self.j_rows
        return (n_left_memlets + edge_height - 1) // edge_height

    @property
    def north_offset(self) -> int:
        """Number of rows above the jamlet grid (lamlet row).

        Routing coords place the lamlet at y=0, so the jamlet grid
        starts at routing y = north_offset.
        """
        return 1

    def jamlet_to_routing(self, jx: int, jy: int):
        """Convert jamlet coordinates to routing coordinates."""
        return (jx + self.west_offset, jy + self.north_offset)

    def kamlet_monitor_coords(self, routing_x: int, routing_y: int):
        """Get the (x, y) key used to identify a kamlet in monitor spans,
        given any jamlet routing coord within that kamlet."""
        jx = routing_x - self.west_offset
        jy = routing_y - self.north_offset
        return (
            (jx // self.j_cols) * self.j_cols + self.west_offset,
            (jy // self.j_rows) * self.j_rows + self.north_offset,
        )

    @property
    def _base_header_width(self) -> int:
        return 2 * self.x_pos_width + 2 * self.y_pos_width + 4 + 6 + 1

    @property
    def abstract_ident_header_fields(self):
        return [
            ('target_x', self.x_pos_width),
            ('target_y', self.y_pos_width),
            ('source_x', self.x_pos_width),
            ('source_y', self.y_pos_width),
            ('length', 4),
            ('message_type', 6),
            ('send_type', 1),
            ('ident', self.ident_width),
        ]

    @property
    def ident_header_fields(self):
        used = self._base_header_width + self.ident_width
        return self.abstract_ident_header_fields + [
            ('_padding', self.word_bytes * 8 - used),
        ]

    @property
    def address_header_fields(self):
        used = self._base_header_width + self.ident_width + self.sram_addr_width
        return self.abstract_ident_header_fields + [
            ('address', self.sram_addr_width),
            ('_padding', self.word_bytes * 8 - used),
        ]

    _FIELD_MAPPING = {
        'xPosWidth': 'x_pos_width',
        'yPosWidth': 'y_pos_width',
        'kCols': 'k_cols',
        'kRows': 'k_rows',
        'jCols': 'j_cols',
        'jRows': 'j_rows',
        'wordBytes': 'word_bytes',
        'sramDepth': 'sram_depth',
        'cacheSlotWordsPerJamlet': 'cache_slot_words_per_jamlet',
        'rfSliceWords': 'rf_slice_words',
        'memAddrWidth': 'mem_addr_width',
        'pageWordsPerJamlet': 'page_words_per_jamlet',
        'elementIndexWidth': 'element_index_width',
        'witemTableDepth': 'witem_table_depth',
        'identWidth': 'ident_width',
        'nMemletGatheringSlots': 'n_memlet_gathering_slots',
        'nResponseBufferSlots': 'n_response_buffer_slots',
        'memBeatWords': 'mem_beat_words',
        'memAxiIdBits': 'mem_axi_id_bits',
        'maxResponseTags': 'max_response_tags',
        'instructionQueueLength': 'instruction_queue_length',
        'lamletDispatchQueueDepth': 'lamlet_dispatch_queue_depth',
        'nAChannels': 'n_a_channels',
        'nBChannels': 'n_b_channels',
    }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ZamletParams':
        """Create ZamletParams from dictionary with camelCase field names."""
        converted = {}
        for camel_key, snake_key in cls._FIELD_MAPPING.items():
            if camel_key in data:
                converted[snake_key] = data[camel_key]
        return cls(**converted)
