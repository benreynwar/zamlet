from enum import Enum, IntEnum
import dataclasses
from dataclasses import dataclass
from types import SimpleNamespace

from zamlet.addresses import TLBFaultType, VectorFaultInfo
from zamlet.control_structures import pack_fields_to_int, unpack_int_to_fields


class SendType(IntEnum):
    SINGLE = 0
    BROADCAST = 1


class MessageType(IntEnum):
    SEND = 0
    INSTRUCTIONS = 1
    WRITE_LINE_DATA = 2

    # Jamlet tells a memory to write some cache line
    WRITE_LINE_ADDR = 4
    WRITE_LINE_RESP = 5
    # Kamlet tells a memory to read a cache line
    READ_LINE_ADDR = 6
    READ_LINE_RESP = 7
    # Kamlet tells a memory to write a cache line and read another one
    WRITE_LINE_READ_LINE_ADDR = 8
    WRITE_LINE_READ_LINE_RESP = 9

    # A request to read a single byte from VPU memory
    READ_BYTE = 10
    READ_BYTE_RESP = 11

    # Model-only types (not in RTL, reserved 12-15)
    READ_WORDS = 12
    READ_WORDS_RESP = 13
    LOAD_BYTE_RESP = 14
    LOAD_WORDS_RESP = 15

    # Sending data to another jamlet to be written to a register.
    LOAD_J2J_WORDS_REQ = 16
    LOAD_J2J_WORDS_RESP = 17
    LOAD_J2J_WORDS_DROP = 18
    LOAD_J2J_WORDS_RETRY = 19

    # Sending data to another jamlet to tell it to store it.
    STORE_J2J_WORDS_REQ = 20
    STORE_J2J_WORDS_RESP = 21
    STORE_J2J_WORDS_DROP = 22
    STORE_J2J_WORDS_RETRY = 23

    # Load a partial word from cache to register (for unaligned loads)
    LOAD_WORD_REQ = 24
    LOAD_WORD_RESP = 25
    LOAD_WORD_DROP = 26
    LOAD_WORD_RETRY = 27

    # Store a partial word from register to cache (for unaligned stores)
    STORE_WORD_REQ = 28
    STORE_WORD_RESP = 29
    STORE_WORD_DROP = 30
    STORE_WORD_RETRY = 31

    # Load and Store with arbitrary addresses
    READ_MEM_WORD_REQ = 32
    READ_MEM_WORD_RESP = 33
    READ_MEM_WORD_DROP = 34

    WRITE_MEM_WORD_REQ = 36
    WRITE_MEM_WORD_RESP = 37
    WRITE_MEM_WORD_DROP = 38
    WRITE_MEM_WORD_RETRY = 39

    # Memlet drop types
    WRITE_LINE_READ_LINE_ADDR_DROP = 42
    READ_LINE_ADDR_DROP = 43
    WRITE_LINE_ADDR_DROP = 44
    WRITE_LINE_DATA_DROP = 45

    # Ordered indexed load/store responses (jamlet -> lamlet)
    LOAD_INDEXED_ELEMENT_RESP = 51
    STORE_INDEXED_ELEMENT_RESP = 53

    # Read from register file (for vrgather)
    READ_REG_ELEMENT_REQ = 54
    READ_REG_ELEMENT_RESP = 55
    READ_REG_ELEMENT_DROP = 56

    # Read register word (kamlet -> lamlet, for vmv.x.s)
    READ_REG_WORD_RESP = 57

# What channel do different messages travel on.

CHANNEL_MAPPING = {
    # Which messages types can always be consumed
    MessageType.READ_LINE_RESP: 0,
    MessageType.WRITE_LINE_RESP: 0,
    MessageType.WRITE_LINE_READ_LINE_RESP: 0,
    MessageType.READ_BYTE_RESP: 0,
    MessageType.LOAD_J2J_WORDS_RESP: 0,
    MessageType.LOAD_J2J_WORDS_DROP: 0,
    MessageType.STORE_J2J_WORDS_RESP: 0,
    MessageType.STORE_J2J_WORDS_DROP: 0,
    MessageType.STORE_J2J_WORDS_RETRY: 0,
    MessageType.LOAD_WORD_RESP: 0,
    MessageType.LOAD_WORD_DROP: 0,
    MessageType.STORE_WORD_RESP: 0,
    MessageType.STORE_WORD_DROP: 0,
    MessageType.STORE_WORD_RETRY: 0,


    # Which channel require to send a always consumable message for them to be consumed
    MessageType.WRITE_LINE_READ_LINE_ADDR_DROP: 0,
    MessageType.READ_LINE_ADDR_DROP: 0,
    MessageType.WRITE_LINE_ADDR_DROP: 0,
    MessageType.WRITE_LINE_DATA_DROP: 0,

    MessageType.READ_LINE_ADDR: 1,
    MessageType.WRITE_LINE_ADDR: 1,
    MessageType.WRITE_LINE_DATA: 1,
    MessageType.WRITE_LINE_READ_LINE_ADDR: 1,
    MessageType.LOAD_J2J_WORDS_REQ: 1,
    MessageType.STORE_J2J_WORDS_REQ: 1,
    MessageType.LOAD_WORD_REQ: 1,
    MessageType.STORE_WORD_REQ: 1,
    MessageType.READ_MEM_WORD_REQ: 1,

    MessageType.READ_MEM_WORD_RESP: 0,
    MessageType.READ_MEM_WORD_DROP: 0,

    MessageType.WRITE_MEM_WORD_REQ: 1,
    MessageType.WRITE_MEM_WORD_RESP: 0,
    MessageType.WRITE_MEM_WORD_DROP: 0,
    MessageType.WRITE_MEM_WORD_RETRY: 0,

    MessageType.READ_REG_WORD_RESP: 0,

    MessageType.READ_REG_ELEMENT_REQ: 1,
    MessageType.READ_REG_ELEMENT_RESP: 0,
    MessageType.READ_REG_ELEMENT_DROP: 0,

    # Ordered indexed load/store responses
    MessageType.LOAD_INDEXED_ELEMENT_RESP: 0,
    MessageType.STORE_INDEXED_ELEMENT_RESP: 0,

    # This is always consumable because we will explicitly track how much buffer room there is.
    MessageType.INSTRUCTIONS: 0,

    # Send is always consumable becaue we track how many slots are available.
    MessageType.SEND: 0,
    }


@dataclass
class Header:
    # Limited to 64 bit  total
    # Here we specify 43 bits of it.
    target_x: int    # 8 bits
    target_y: int    # 8 bits
    source_x: int    # 8 bits
    source_y: int    # 8 bits
    length: int      # 4 bits
    message_type: MessageType  # 6 bits
    send_type: SendType        # 1 bit

    def encode(self, params) -> int:
        return pack_fields_to_int(self, params.base_header_fields)

    def copy(self):
        return dataclasses.replace(self)


@dataclass
class IdentHeader(Header):
    # ident is used to tie requests and responses together
    ident: int     # 7 bits

    def encode(self, params) -> int:
        return pack_fields_to_int(self, params.ident_header_fields)

    @classmethod
    def decode(cls, value: int, params) -> 'IdentHeader':
        return cls(**unpack_int_to_fields(value, params.ident_header_fields))


@dataclass
class TaggedHeader(IdentHeader):
    # Used to distinguish replys when we expect lots
    # of replys.  Maybe simpler that using source_x, source_y?
    # 12 bits remaining
    tag: int     # 4 bits


@dataclass
class MaskedTaggedHeader(TaggedHeader):
    mask: int = 0  # 12 bits - per-word mask for J2J operations


@dataclass
class RegElementHeader(TaggedHeader):
    # For READ_REG_ELEMENT_REQ/RESP - fits in the 12 remaining bits
    # src_vline_offset is the vline offset within the source vector register
    # (e.g. vs2 for vrgather). The receiver looks up the matching phys reg in
    # its own witem's vs2_pregs[src_vline_offset] — sending arch reg indices
    # across kamlets would require the receiver to also have access to its
    # kamlet's rename table, while vline offsets are universally meaningful
    # (purely a function of the gather index and elements_in_vline).
    src_vline_offset: int = 0  # 6 bits - source vline offset within vs2
    src_byte_offset: int = 0   # 3 bits - byte offset within register word
    n_bytes: int = 0           # 3 bits - number of bytes to read


def _jte_slot_width(params) -> int:
    return (params.witem_table_depth - 1).bit_length()


def _indexed_dst_width(params) -> int:
    return params.x_pos_width + params.y_pos_width


def _jte_tail_width(params) -> int:
    return 3 * params.log2_word_bytes + _jte_slot_width(params)


def _jte_tail_fields(params) -> list[tuple[str, int]]:
    return [
        ('n_bytes_encoded', params.log2_word_bytes),
        ('dst_offset', params.log2_word_bytes),
        ('src_offset', params.log2_word_bytes),
        ('slot', _jte_slot_width(params)),
    ]


def _encode_jte_n_bytes(n_bytes: int, params) -> int:
    assert 1 <= n_bytes <= params.word_bytes
    return 0 if n_bytes == params.word_bytes else n_bytes


def _decode_jte_n_bytes(n_bytes_encoded: int, params) -> int:
    return params.word_bytes if n_bytes_encoded == 0 else n_bytes_encoded


def _decode_header_enums(fields: dict[str, int]) -> None:
    fields['message_type'] = MessageType(fields['message_type'])
    fields['send_type'] = SendType(fields['send_type'])


@dataclass
class JteHeader(IdentHeader):
    n_bytes: int
    dst_offset: int
    src_offset: int
    slot: int

    @staticmethod
    def fields(params):
        used = params._ident_header_width + _jte_tail_width(params)
        return params.abstract_ident_header_fields + _jte_tail_fields(params) + [
            ('_padding', params.word_width - used),
        ]

    def encode(self, params) -> int:
        values = dataclasses.asdict(self)
        values['n_bytes_encoded'] = _encode_jte_n_bytes(self.n_bytes, params)
        return pack_fields_to_int(SimpleNamespace(**values), self.fields(params))

    @classmethod
    def decode(cls, value: int, params) -> 'JteHeader':
        fields = unpack_int_to_fields(value, cls.fields(params))
        fields.pop('_padding', None)
        fields['n_bytes'] = _decode_jte_n_bytes(fields.pop('n_bytes_encoded'), params)
        _decode_header_enums(fields)
        return cls(**fields)


@dataclass
class JteIHeader:
    dst_index: int
    source_x: int
    source_y: int
    length: int
    message_type: MessageType
    send_type: SendType
    ident: int
    n_bytes: int
    dst_offset: int
    src_offset: int
    slot: int

    @staticmethod
    def fields(params):
        used = (
            _indexed_dst_width(params)
            + params.x_pos_width
            + params.y_pos_width
            + params.message_length_width
            + params.message_type_width
            + 1
            + params.ident_width
            + _jte_tail_width(params)
        )
        return [
            ('dst_index', _indexed_dst_width(params)),
            ('source_x', params.x_pos_width),
            ('source_y', params.y_pos_width),
            ('length', params.message_length_width),
            ('message_type', params.message_type_width),
            ('send_type', 1),
            ('ident', params.ident_width),
            *_jte_tail_fields(params),
            ('_padding', params.word_width - used),
        ]

    def encode(self, params) -> int:
        values = dataclasses.asdict(self)
        values['n_bytes_encoded'] = _encode_jte_n_bytes(self.n_bytes, params)
        return pack_fields_to_int(SimpleNamespace(**values), self.fields(params))

    @classmethod
    def decode(cls, value: int, params) -> 'JteIHeader':
        fields = unpack_int_to_fields(value, cls.fields(params))
        fields.pop('_padding', None)
        fields['n_bytes'] = _decode_jte_n_bytes(fields.pop('n_bytes_encoded'), params)
        _decode_header_enums(fields)
        return cls(**fields)


@dataclass
class AddressHeader(IdentHeader):
    address: int   # 16 bits

    def encode(self, params) -> int:
        return pack_fields_to_int(self, params.address_header_fields)

    @classmethod
    def decode(cls, value: int, params) -> 'AddressHeader':
        return cls(**unpack_int_to_fields(value, params.address_header_fields))


@dataclass
class CacheLineHeader(Header):
    slot: int

    @staticmethod
    def fields(params):
        used = params._base_header_width + params.cache_slot_width
        return params.abstract_base_header_fields + [
            ('slot', params.cache_slot_width),
            ('_padding', params.word_bytes * 8 - used),
        ]

    def encode(self, params) -> int:
        return pack_fields_to_int(self, self.fields(params))

    @classmethod
    def decode(cls, value: int, params) -> 'CacheLineHeader':
        fields = unpack_int_to_fields(value, cls.fields(params))
        fields.pop('_padding', None)
        fields['message_type'] = MessageType(fields['message_type'])
        fields['send_type'] = SendType(fields['send_type'])
        return cls(**fields)


@dataclass
class ValueHeader(IdentHeader):
    value: bytes   # 16 bits


@dataclass
class WriteSetIdentHeader(IdentHeader):
    writeset_ident: int # 5 bits (11 remaining)


@dataclass
class WriteMemWordHeader(TaggedHeader):
    dst_byte_in_word: int    # 3 bits - dst byte in word (0-7)
    n_bytes_or_bits: int     # 3 bits - number of bytes (1-8), or number of bits in bit_mode
    element_index: int = 0  # Element index for ordered operations
    ordered: bool = False   # Whether this is an ordered operation
    bit_mode: bool = False      # 1 bit - if True, n_bytes_or_bits is n_bits
    dst_bit_in_byte: int = 0   # 3 bits - bit offset within byte (0-7), only used in bit_mode
    no_response: bool = False  # 1 bit - if True, no WRITE_MEM_WORD_RESP is sent
    writeset_ident: int = 0    # bit packing concerns: see docs/TODO.md


@dataclass
class ReadMemWordHeader(TaggedHeader):
    # TODO: element_index can be derived from source coordinates - remove in future
    element_index: int = 0  # Element index for ordered operations
    ordered: bool = False   # Whether this is an ordered operation
    parent_ident: int = 0   # Parent instruction ident for ordering checks
    fault: bool = False     # Earlier element faulted, skip this read
    writeset_ident: int = 0  # bit packing concerns: see docs/TODO.md


@dataclass
class ElementIndexHeader(IdentHeader):
    element_index: int = 0
    masked: bool = False
    fault: bool = False  # TLB fault occurred for this element


def pack_vector_fault_info_words(params, fault_info: VectorFaultInfo) -> list[int]:
    """Encode vector fault metadata as two machine-width packet words.

    Word 0 is the faulting byte address. Word 1 packs element_index in the
    low bits and TLBFaultType in the next two bits.
    """
    word_bits = params.word_bytes * 8
    assert 0 <= fault_info.fault_addr < (1 << word_bits)
    assert 0 <= fault_info.element_index < (1 << params.element_index_width)
    assert 0 <= fault_info.fault_type.value < (1 << 2)
    meta = fault_info.element_index | (
        fault_info.fault_type.value << params.element_index_width)
    assert 0 <= meta < (1 << word_bits)
    return [fault_info.fault_addr, meta]


def unpack_vector_fault_info_words(params, words: list[int]) -> VectorFaultInfo:
    assert len(words) == 2
    word_bits = params.word_bytes * 8
    fault_addr, meta = words
    assert 0 <= fault_addr < (1 << word_bits)
    assert 0 <= meta < (1 << word_bits)
    element_mask = (1 << params.element_index_width) - 1
    element_index = meta & element_mask
    fault_type_value = (meta >> params.element_index_width) & 0b11
    return VectorFaultInfo(
        element_index=element_index,
        fault_type=TLBFaultType(fault_type_value),
        fault_addr=fault_addr,
    )


class Direction(Enum):
    N = 0
    S = 1
    E = 2
    W = 3
    H = 4


directions = (Direction.N, Direction.S, Direction.E, Direction.W, Direction.H)


# Request messages sent via jamlet.send_packet that expect responses
REQUEST_MESSAGE_TYPES = {
    MessageType.LOAD_J2J_WORDS_REQ,
    MessageType.STORE_J2J_WORDS_REQ,
    MessageType.LOAD_WORD_REQ,
    MessageType.STORE_WORD_REQ,
    MessageType.READ_MEM_WORD_REQ,
    MessageType.WRITE_MEM_WORD_REQ,
}

# Cache line messages are sent via kamlet/jamlet directly, not through send_packet.
# TODO: Add tracking for these separately.
CACHE_LINE_MESSAGE_TYPES = {
    MessageType.READ_LINE_ADDR,
    MessageType.WRITE_LINE_ADDR,
    MessageType.WRITE_LINE_READ_LINE_ADDR,
}

CACHE_LINE_HEADER_MESSAGE_TYPES = {
    MessageType.READ_LINE_RESP,
    MessageType.WRITE_LINE_READ_LINE_RESP,
    MessageType.WRITE_LINE_DATA,
}

JTE_HEADER_MESSAGE_TYPES = {
    MessageType.LOAD_WORD_REQ,
    MessageType.LOAD_WORD_RESP,
    MessageType.LOAD_WORD_DROP,
    MessageType.LOAD_WORD_RETRY,
    MessageType.STORE_WORD_REQ,
    MessageType.STORE_WORD_RESP,
    MessageType.STORE_WORD_DROP,
    MessageType.STORE_WORD_RETRY,
}


def is_request_message(msg_type: MessageType) -> bool:
    """Return True if this message type expects a response."""
    return msg_type in REQUEST_MESSAGE_TYPES


# Message types that use AddressHeader (have an address field)
ADDRESS_HEADER_MESSAGE_TYPES = {
    MessageType.WRITE_LINE_ADDR, MessageType.WRITE_LINE_RESP,
    MessageType.READ_LINE_ADDR,
    MessageType.WRITE_LINE_READ_LINE_ADDR,
}


def int_to_header(value: int, params) -> Header:
    """Decode an integer into the appropriate Header subclass."""
    fields = unpack_int_to_fields(value, params.base_header_fields)
    msg_type = MessageType(fields['message_type'])
    if msg_type in CACHE_LINE_HEADER_MESSAGE_TYPES:
        return CacheLineHeader.decode(value, params)
    if msg_type in JTE_HEADER_MESSAGE_TYPES:
        return JteHeader.decode(value, params)
    fields = unpack_int_to_fields(value, params.address_header_fields)
    if msg_type in ADDRESS_HEADER_MESSAGE_TYPES:
        return AddressHeader(**fields)
    ident_fields = unpack_int_to_fields(value, params.ident_header_fields)
    return IdentHeader(**ident_fields)


def header_to_int(header: Header, params) -> int:
    """Encode a Header to an integer."""
    if isinstance(header, CacheLineHeader):
        return header.encode(params)
    if isinstance(header, JteHeader):
        return header.encode(params)
    if isinstance(header, AddressHeader):
        return pack_fields_to_int(header, params.address_header_fields)
    return pack_fields_to_int(header, params.ident_header_fields)
