import logging
import math
from dataclasses import dataclass, fields, field
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _from_dict(cls, data: Dict[str, Any], mapping: Dict[str, str]):
    required = set(mapping.keys())
    seen = set(data.keys())
    missing = required - seen
    extra = seen - required
    if missing or extra:
        logger.error(f'{cls.__name__}: missing fields {missing}. Extra fields {extra}')
    assert not missing
    assert not extra

    kwargs = {}
    field_types = {f.name: f.type for f in fields(cls)}
    for camel_key, snake_key in mapping.items():
        value = data[camel_key]
        field_type = field_types[snake_key]
        if isinstance(value, dict) and hasattr(field_type, "from_dict"):
            value = field_type.from_dict(value)
        kwargs[snake_key] = value
    return cls(**kwargs)


def _identity_mapping(cls) -> Dict[str, str]:
    return {f.name: f.name for f in fields(cls)}


@dataclass
class RfSliceParams:
    maskReqForwardBuffer: bool = False
    maskReqBackwardBuffer: bool = False
    maskRespForwardBuffer: bool = False
    maskRespBackwardBuffer: bool = False
    indexReqForwardBuffer: bool = False
    indexReqBackwardBuffer: bool = False
    indexRespForwardBuffer: bool = False
    indexRespBackwardBuffer: bool = False
    dataReqForwardBuffer: bool = False
    dataReqBackwardBuffer: bool = False
    dataRespForwardBuffer: bool = False
    dataRespBackwardBuffer: bool = False
    localExecReqForwardBuffer: bool = False
    localExecReqBackwardBuffer: bool = False
    localExecRespForwardBuffer: bool = False
    localExecRespBackwardBuffer: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RfSliceParams':
        return _from_dict(cls, data, _identity_mapping(cls))


@dataclass
class SynchronizerParams:
    maxConcurrentSyncs: int = 4
    resultOutputReg: bool = False
    portOutOutputReg: bool = False
    minPipelineReg: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SynchronizerParams':
        return _from_dict(cls, data, _identity_mapping(cls))


@dataclass
class NetworkNodeParams:
    iaForwardBuffer: bool = False
    iaBackwardBuffer: bool = True
    abForwardBuffer: bool = True
    abBackwardBuffer: bool = True
    boForwardBuffer: bool = False
    boBackwardBuffer: bool = True
    hiForwardBuffer: bool = True
    hiBackwardBuffer: bool = True
    hoForwardBuffer: bool = True
    hoBackwardBuffer: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NetworkNodeParams':
        return _from_dict(cls, data, _identity_mapping(cls))


@dataclass
class IssueUnitParams:
    exForwardBuffer: bool = False
    exBackwardBuffer: bool = False
    tlbReqForwardBuffer: bool = False
    tlbReqBackwardBuffer: bool = False
    tlbRespInputReg: bool = False
    toIdentTrackerForwardBuffer: bool = False
    toIdentTrackerBackwardBuffer: bool = False
    comOutputReg: bool = False
    killInputReg: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IssueUnitParams':
        return _from_dict(cls, data, _identity_mapping(cls))


@dataclass
class JteStateParams:
    inputReqFB: bool = True
    inputReqBB: bool = True
    inputRespFB: bool = True
    inputRespBB: bool = True
    initiatorDispatchFB: bool = False
    initiatorDispatchBB: bool = False
    receiverUpdateFB: bool = False
    receiverUpdateBB: bool = False
    slotToRegReqFB: bool = False
    slotToRegReqBB: bool = False
    slotToRegRespFB: bool = False
    slotToRegRespBB: bool = False
    createBuffer: bool = True
    clearBuffer: bool = True
    initiatorCommitBuffer: bool = False
    dispatchABFB: bool = True
    dispatchABBB: bool = True
    dispatchBCFB: bool = True
    dispatchBCBB: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JteStateParams':
        return _from_dict(cls, data, _identity_mapping(cls))


@dataclass
class JteInitiatorParams:
    inputFB: bool = False
    inputBB: bool = False
    rfDataReqFB: bool = True
    rfDataReqBB: bool = True
    rfMaskReqFB: bool = True
    rfMaskReqBB: bool = True
    rfIndexReqFB: bool = True
    rfIndexReqBB: bool = True
    abFB: bool = True
    abBB: bool = True
    bcFB: bool = True
    bcBB: bool = True
    rfMaskRespFB: bool = True
    rfMaskRespBB: bool = True
    rfDataRespFB: bool = True
    rfDataRespBB: bool = True
    rfIndexRespFB: bool = True
    rfIndexRespBB: bool = True
    cdFB: bool = True
    cdBB: bool = True
    deFB: bool = True
    deBB: bool = True
    tlbReqFB: bool = True
    tlbReqBB: bool = True
    orderingReqFB: bool = True
    orderingReqBB: bool = True
    efFB: bool = True
    efBB: bool = True
    fgFB: bool = True
    fgBB: bool = True
    ghFB: bool = True
    ghBB: bool = True
    tlbRespFB: bool = True
    tlbRespBB: bool = True
    orderingRespFB: bool = True
    orderingRespBB: bool = True
    commitBuffer: bool = False
    hiFB: bool = True
    hiBB: bool = True
    packetFB: bool = True
    packetBB: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JteInitiatorParams':
        return _from_dict(cls, data, _identity_mapping(cls))


@dataclass
class JteReceiverParams:
    packetFB: bool = True
    packetBB: bool = True
    slotToRegReqFB: bool = False
    slotToRegReqBB: bool = False
    abFB: bool = True
    abBB: bool = True
    slotToRegRespFB: bool = False
    slotToRegRespBB: bool = False
    rfWriteReqFB: bool = True
    rfWriteReqBB: bool = True
    bcFB: bool = True
    bcBB: bool = True
    rfWriteRespFB: bool = True
    rfWriteRespBB: bool = True
    cdFB: bool = True
    cdBB: bool = True
    updateMsgFB: bool = False
    updateMsgBB: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JteReceiverParams':
        return _from_dict(cls, data, _identity_mapping(cls))


@dataclass
class JteHandlerParams:
    packetInFB: bool = True
    packetInBB: bool = True
    abFB: bool = True
    abBB: bool = True
    cacheLineReqFB: bool = True
    cacheLineReqBB: bool = True
    bcFB: bool = True
    bcBB: bool = True
    cdFB: bool = True
    cdBB: bool = True
    cacheLineRespFB: bool = True
    cacheLineRespBB: bool = True
    deFB: bool = True
    deBB: bool = True
    sramReqFB: bool = True
    sramReqBB: bool = True
    efFB: bool = True
    efBB: bool = True
    fgFB: bool = True
    fgBB: bool = True
    sramRespFB: bool = True
    sramRespBB: bool = True
    ghFB: bool = True
    ghBB: bool = True
    packetOutFB: bool = True
    packetOutBB: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JteHandlerParams':
        return _from_dict(cls, data, _identity_mapping(cls))


@dataclass
class SramParams:
    localA: bool = True
    localB: bool = False
    localC: bool = True
    jteAFB: bool = True
    jteABB: bool = True
    jteBFB: bool = False
    jteBBB: bool = False
    jteCFB: bool = True
    jteCBB: bool = True

    @property
    def local_response_latency(self) -> int:
        return sum((self.localA, self.localB, self.localC))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SramParams':
        return _from_dict(cls, data, _identity_mapping(cls))


@dataclass
class JceParams:
    opFB: bool = True
    opBB: bool = True
    sramReadReqFB: bool = True
    sramReadReqBB: bool = True
    abFB: bool = True
    abBB: bool = True
    bcFB: bool = True
    bcBB: bool = True
    sramReadRespFB: bool = True
    sramReadRespBB: bool = True
    cdFB: bool = True
    cdBB: bool = True
    packetOutFB: bool = True
    packetOutBB: bool = True
    packetInFB: bool = True
    packetInBB: bool = True
    sramWriteReqFB: bool = True
    sramWriteReqBB: bool = True
    sramWriteRespFB: bool = True
    sramWriteRespBB: bool = True
    rxABFB: bool = True
    rxABBB: bool = True
    rxBCFB: bool = True
    rxBCBB: bool = True
    rxDoneFB: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JceParams':
        return _from_dict(cls, data, _identity_mapping(cls))


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

    word_bytes: int = 8
    log2_cache_slot_words_per_jamlet: int = 2
    log2_page_words_per_jamlet: int = 6
    scalar_memory_bytes: int = 8 << 20
    kamlet_memory_bytes: int = 1 << 20
    #jamlet_sram_bytes: int = 1 << 10
    sram_depth: int = 128
    tohost_addr: int = 0x80001000
    fromhost_addr: int = 0x80001040
    receive_buffer_depth: int = 16
    router_output_buffer_length: int = 2
    router_input_buffer_length: int = 2
    instruction_queue_length: int = 64
    reservation_station_depth: int = 16
    n_ident_query_slots: int = 8
    # Minimum cycles between IdentQueries issued due to ident pressure.
    # Prevents flooding the network with back-to-back queries while a
    # response is in flight.
    ident_query_min_cycles: int = 64
    n_a_channels: int = 1
    n_b_channels: int = 1


    instruction_buffer_length: int = 64
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
    writeset_width: int = 4
    rf_slice_words: int = 48
    mem_addr_width: int = 48
    element_index_width: int = 22
    log2_n_params: int = 4
    n_response_buffer_slots: int = 4
    mem_beat_words: int = 1
    mem_axi_id_bits: int = 4
    lamlet_dispatch_queue_depth: int = 8
    ident_tracker_out_forward_buffer: bool = True
    ident_tracker_out_backward_buffer: bool = True
    network_node_params: NetworkNodeParams = field(default_factory=NetworkNodeParams)
    issue_unit_params: IssueUnitParams = field(default_factory=IssueUnitParams)
    synchronizer_params: SynchronizerParams = field(default_factory=SynchronizerParams)
    rf_slice_params: RfSliceParams = field(default_factory=RfSliceParams)
    jte_state_params: JteStateParams = field(default_factory=JteStateParams)
    jte_initiator_params: JteInitiatorParams = field(default_factory=JteInitiatorParams)
    jte_receiver_params: JteReceiverParams = field(default_factory=JteReceiverParams)
    jte_handler_params: JteHandlerParams = field(default_factory=JteHandlerParams)
    sram_params: SramParams = field(default_factory=SramParams)
    jce_params: JceParams = field(default_factory=JceParams)
    message_length_width: int = 4
    message_type_width: int = 6

    # Experiment: if True, lamlet skips the on-chip network for kinstr
    # dispatch and enqueues kinstructions directly into the target
    # kamlet instruction_queue, respecting its capacity as back-pressure.
    # Used to measure whether network traffic from kinstr packets is
    # bottlenecking kernels. Leaves packet-based dispatch code intact.
    bypass_kinstr_network: bool = False

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
    def n_arch_vregs(self) -> int:
        """Number of architectural vector registers exposed by the ISA.
        Fixed by RVV at 32. Arch indices in [n_arch_vregs, rf_slice_words) are
        scratch names used by compound lamlet ops."""
        return 32

    @property
    def page_words_per_jamlet(self) -> int:
        return 1 << self.log2_page_words_per_jamlet

    @property
    def cache_slot_words_per_jamlet(self) -> int:
        return 1 << self.log2_cache_slot_words_per_jamlet

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
    def log2_j_in_k(self) -> int:
        return int(math.log2(self.j_in_k))

    @property
    def log2_j_in_l(self) -> int:
        return int(math.log2(self.j_in_l))

    @property
    def log2_word_bytes(self) -> int:
        return int(math.log2(self.word_bytes))

    @property
    def log2_cache_slot_words_per_kamlet(self) -> int:
        return self.log2_cache_slot_words_per_jamlet + self.log2_j_in_k

    @property
    def end_element_index_width(self) -> int:
        return self.log2_j_in_l + self.log2_word_bytes + 1

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
    def stripe_bytes(self):
        return self.word_bytes * self.j_in_l

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
    def abstract_base_header_fields(self):
        used = self._base_header_width
        return [
            ('target_x', self.x_pos_width),
            ('target_y', self.y_pos_width),
            ('source_x', self.x_pos_width),
            ('source_y', self.y_pos_width),
            ('length', 4),
            ('message_type', 6),
            ('send_type', 1),
        ]

    @property
    def base_header_fields(self):
        used = self._base_header_width
        return self.abstract_base_header_fields + [
            ('_padding', self.word_bytes * 8 - self._base_header_width),
        ]

    @property
    def _ident_header_width(self) -> int:
        return self._base_header_width + self.ident_width

    @property
    def abstract_ident_header_fields(self):
        return self.abstract_base_header_fields + [
            ('ident', self.ident_width),
        ]

    @property
    def ident_header_fields(self):
        return self.abstract_ident_header_fields + [
            ('_padding', self.word_bytes * 8 - self._ident_header_width),
        ]

    @property
    def _address_header_width(self) -> int:
        return self._ident_header_width + self.sram_addr_width

    @property
    def address_header_fields(self):
        return self.abstract_ident_header_fields + [
            ('address', self.sram_addr_width),
            ('_padding', self.word_bytes * 8 - self._address_header_width),
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
        'log2CacheSlotWordsPerJamlet': 'log2_cache_slot_words_per_jamlet',
        'rfSliceWords': 'rf_slice_words',
        'memAddrWidth': 'mem_addr_width',
        'log2PageWordsPerJamlet': 'log2_page_words_per_jamlet',
        'elementIndexWidth': 'element_index_width',
        'log2NParams': 'log2_n_params',
        'witemTableDepth': 'witem_table_depth',
        'identWidth': 'ident_width',
        'writesetWidth': 'writeset_width',
        'nMemletGatheringSlots': 'n_memlet_gathering_slots',
        'nResponseBufferSlots': 'n_response_buffer_slots',
        'memBeatWords': 'mem_beat_words',
        'memAxiIdBits': 'mem_axi_id_bits',
        'maxResponseTags': 'max_response_tags',
        'instructionQueueLength': 'instruction_queue_length',
        'reservationStationDepth': 'reservation_station_depth',
        'lamletDispatchQueueDepth': 'lamlet_dispatch_queue_depth',
        'identTrackerOutForwardBuffer': 'ident_tracker_out_forward_buffer',
        'identTrackerOutBackwardBuffer': 'ident_tracker_out_backward_buffer',
        'nAChannels': 'n_a_channels',
        'nBChannels': 'n_b_channels',
        'networkNodeParams': 'network_node_params',
        'issueUnitParams': 'issue_unit_params',
        'synchronizerParams': 'synchronizer_params',
        'rfSliceParams': 'rf_slice_params',
        'jteStateParams': 'jte_state_params',
        'jteInitiatorParams': 'jte_initiator_params',
        'jteReceiverParams': 'jte_receiver_params',
        'jteHandlerParams': 'jte_handler_params',
        'sramParams': 'sram_params',
        'jceParams': 'jce_params',
        'messageLengthWidth': 'message_length_width',
        'messageTypeWidth': 'message_type_width',
    }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ZamletParams':
        """Create ZamletParams from dictionary with camelCase field names."""
        return _from_dict(cls, data, cls._FIELD_MAPPING)
