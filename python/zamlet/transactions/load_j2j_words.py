'''
Load J2J Words Transaction

Handles unaligned vector loads where data must be transferred between jamlets via
jamlet-to-jamlet (J2J) messaging. Used when the load is not aligned to the vline or
when element widths don't match between source and destination.

Messages:
    LOAD_J2J_WORDS_REQ  - SRC jamlet sends data to DST jamlet
    LOAD_J2J_WORDS_RESP - DST jamlet acknowledges receipt
    LOAD_J2J_WORDS_DROP - DST jamlet wasn't ready, SRC should retry
    LOAD_J2J_WORDS_RETRY - DST asks SRC to resend (after becoming ready)
'''
from typing import List, Any, TYPE_CHECKING
import logging

from zamlet import addresses
from zamlet.waiting_item import WaitingItemRequiresCache
from zamlet.message import TaggedHeader, MessageType, SendType
from zamlet.kamlet.cache_table import SendState, ReceiveState, LoadProtocolState
from zamlet.kamlet import kinstructions
from zamlet.params import LamletParams
from zamlet.transactions import register_handler
from zamlet.transactions.j2j_mapping import RegMemMapping, get_mapping_from_reg, get_mapping_from_mem

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet
    from zamlet.kamlet.kamlet import Kamlet


logger = logging.getLogger(__name__)


class WaitingLoadJ2JWords(WaitingItemRequiresCache):

    cache_is_read = True

    def __init__(self, params: LamletParams, instr: kinstructions.Load, rf_ident: int|None=None):
        super().__init__(
            item=instr, instr_ident=instr.instr_ident,
            writeset_ident=instr.writeset_ident, rf_ident=rf_ident)
        n_tags = params.word_bytes * params.j_in_k
        self.protocol_states: List[LoadProtocolState] = [
            LoadProtocolState() for _ in range(n_tags)]

    def ready(self) -> bool:
        return all(state.finished() for state in self.protocol_states) and self.cache_is_avail

    async def monitor_jamlet(self, jamlet: 'Jamlet') -> None:
        if not self.cache_is_avail:
            return
        instr = self.item
        assert isinstance(instr, kinstructions.Load)
        word_bytes = jamlet.params.word_bytes
        for tag in range(word_bytes):
            response_index = jamlet.j_in_k_index * word_bytes + tag
            protocol_state = self.protocol_states[response_index]
            if protocol_state.src_state == SendState.NEED_TO_SEND:
                await send_req(jamlet, self, tag)

    async def finalize(self, kamlet: 'Kamlet') -> None:
        instr = self.item
        for pstate in self.protocol_states:
            assert pstate.finished()
        dst_regs = kamlet.get_regs(
            start_index=instr.start_index, n_elements=instr.n_elements,
            ew=instr.dst_ordering.ew, base_reg=instr.dst)
        read_regs = [instr.mask_reg] if instr.mask_reg is not None else []
        assert self.rf_ident is not None
        kamlet.rf_info.finish(self.rf_ident, write_regs=dst_regs, read_regs=read_regs)


def init_dst_state(jamlet, witem: WaitingLoadJ2JWords, tag: int) -> None:
    '''Initialize the dst_state for a given tag.'''
    instr = witem.item
    assert isinstance(instr, kinstructions.Load)

    mappings = get_mapping_from_reg(
        params=jamlet.params, k_maddr=instr.k_maddr, reg_ordering=instr.dst_ordering,
        start_index=instr.start_index, n_elements=instr.n_elements,
        reg_wb=tag*8, reg_x=jamlet.x, reg_y=jamlet.y)

    response_tag = jamlet.j_in_k_index * jamlet.params.word_bytes + tag
    if len(mappings) == 0:
        witem.protocol_states[response_tag].dst_state = ReceiveState.COMPLETE


def init_src_state(jamlet, witem: WaitingLoadJ2JWords, tag: int) -> None:
    '''Initialize the src_state for a given tag.'''
    instr = witem.item
    assert isinstance(instr, kinstructions.Load)

    mappings = get_mapping_from_mem(
        params=jamlet.params, k_maddr=instr.k_maddr, reg_ordering=instr.dst_ordering,
        start_index=instr.start_index, n_elements=instr.n_elements,
        mem_wb=tag*8, mem_x=jamlet.x, mem_y=jamlet.y)

    response_tag = jamlet.j_in_k_index * jamlet.params.word_bytes + tag
    if len(mappings) == 0:
        witem.protocol_states[response_tag].src_state = SendState.COMPLETE


async def send_req(jamlet, witem: WaitingLoadJ2JWords, tag: int) -> None:
    '''SRC jamlet reads cache and sends data to DST jamlet.'''
    instr = witem.item
    assert isinstance(instr, kinstructions.Load)
    assert witem.cache_slot is not None
    params = jamlet.params

    mem_wb = tag * 8

    mappings = get_mapping_from_mem(
        params, k_maddr=instr.k_maddr, reg_ordering=instr.dst_ordering,
        start_index=instr.start_index, n_elements=instr.n_elements,
        mem_wb=mem_wb, mem_x=jamlet.x, mem_y=jamlet.y)

    word_bytes = jamlet.params.word_bytes
    kamlet_vline_bytes = jamlet.params.vline_bytes // jamlet.params.k_in_l
    base_vline_in_cache = (instr.k_maddr.addr % jamlet.params.cache_line_bytes) // kamlet_vline_bytes
    response_tag = jamlet.j_in_k_index * word_bytes + mem_wb//8

    if len(mappings) == 0:
        witem.protocol_states[response_tag].src_state = SendState.COMPLETE
        return

    words = []
    reg_vw = None
    for mapping in mappings:
        cache_base_addr = witem.cache_slot * jamlet.params.vlines_in_cache_line * word_bytes
        vline_offset_in_cache = mapping.mem_v % jamlet.params.vlines_in_cache_line
        cache_addr = cache_base_addr + vline_offset_in_cache * word_bytes
        word = jamlet.sram[cache_addr: cache_addr + word_bytes]
        logger.debug(
            f'jamlet ({jamlet.x}, {jamlet.y}): send_load_j2j_words_req tag={mem_wb} '
            f'mapping={mapping} cache_slot={witem.cache_slot} '
            f'base_vline_in_cache={base_vline_in_cache} '
            f'vline_addr_offset={vline_offset_in_cache} cache_addr={cache_addr} '
            f'word={word.hex()}')
        assert len(word) == word_bytes
        words.append(word)
        # Check that all the mappings point to the same word in the reg vector line
        if reg_vw is None:
            reg_vw = mapping.reg_vw
        assert  reg_vw == mapping.reg_vw
    assert reg_vw is not None

    target_x, target_y = addresses.vw_index_to_j_coords(
        jamlet.params, instr.dst_ordering.word_order, reg_vw)
    witem.protocol_states[response_tag].src_state = SendState.WAITING_FOR_RESPONSE

    header = TaggedHeader(
        target_x=target_x,
        target_y=target_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        length=1 + len(words),
        message_type=MessageType.LOAD_J2J_WORDS_REQ,
        send_type=SendType.SINGLE,
        ident=instr.instr_ident,
        tag=mem_wb//8,
    )
    packet = [header] + words

    # Create transaction for this src/dst pair, parent is the SRC witem
    kamlet_min_x = (jamlet.x // jamlet.params.j_cols) * jamlet.params.j_cols
    kamlet_min_y = (jamlet.y // jamlet.params.j_rows) * jamlet.params.j_rows
    witem_span_id = jamlet.monitor.get_witem_span_id(instr.instr_ident, kamlet_min_x, kamlet_min_y)
    transaction_span_id = jamlet.monitor.create_transaction(
        'LoadJ2JWords', instr.instr_ident, jamlet.x, jamlet.y, target_x, target_y,
        parent_span_id=witem_span_id, tag=mem_wb//8)

    await jamlet.send_packet(packet, parent_span_id=transaction_span_id)


@register_handler(MessageType.LOAD_J2J_WORDS_REQ)
async def handle_req(jamlet, packet: List[Any]) -> None:
    '''DST jamlet receives data and writes to register file.'''
    header = packet[0]
    assert isinstance(header, TaggedHeader)
    assert header.message_type == MessageType.LOAD_J2J_WORDS_REQ

    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    if witem is None:
        await send_drop(jamlet, header)
        return
    instr = witem.item
    assert isinstance(instr, kinstructions.Load)

    word_bytes = jamlet.params.word_bytes
    mem_wb = header.tag * 8
    mappings = get_mapping_from_mem(
        jamlet.params, k_maddr=instr.k_maddr, reg_ordering=instr.dst_ordering,
        start_index=instr.start_index, n_elements=instr.n_elements,
        mem_wb=mem_wb, mem_x=header.source_x, mem_y=header.source_y)

    assert len(packet) >= 2
    words = packet[1:]
    assert len(mappings) == len(words)
    reg_wb = None
    for word, mapping in zip(words, mappings):
        shift = mapping.mem_wb - mapping.reg_wb
        mask = ((1 << mapping.n_bits) - 1) << mapping.reg_wb

        assert isinstance(word, (bytes, bytearray))
        assert len(word) == jamlet.params.word_bytes
        word_as_int = int.from_bytes(word, byteorder='little')
        if shift < 0:
            shifted = word_as_int << (-shift)
        else:
            shifted = word_as_int >> shift

        dst_reg = instr.dst + mapping.reg_v

        old_word = jamlet.rf_slice[dst_reg * word_bytes: (dst_reg+1) * word_bytes]
        old_word_as_int = int.from_bytes(old_word, byteorder='little')
        masked_old_word = old_word_as_int & (~mask)
        masked_shifted = shifted & mask
        updated_word = masked_old_word | masked_shifted
        updated_word_bytes = updated_word.to_bytes(word_bytes, byteorder='little')
        logger.debug(
            f'{jamlet.clock.cycle}: RF_WRITE LOAD_J2J: jamlet ({jamlet.x},{jamlet.y}) '
            f'rf[{dst_reg}] old={old_word.hex()} new={updated_word_bytes.hex()} '
            f'mapping={mapping} shift={shift} mask=0x{mask:x} word=0x{word_as_int:x}')
        jamlet.rf_slice[dst_reg * word_bytes: (dst_reg+1) * word_bytes] = updated_word_bytes
        if reg_wb is None:
            reg_wb = mapping.reg_wb
        assert reg_wb == mapping.reg_wb
    assert reg_wb is not None

    response_index = jamlet.j_in_k_index * word_bytes + reg_wb//8

    assert witem.protocol_states[response_index].dst_state == ReceiveState.WAITING_FOR_REQUEST
    witem.protocol_states[response_index].dst_state = ReceiveState.COMPLETE
    await send_resp(jamlet, header)


@register_handler(MessageType.LOAD_J2J_WORDS_RESP)
def handle_resp(jamlet, packet: List[Any]) -> None:
    '''SRC jamlet receives acknowledgment from DST.'''
    header = packet[0]
    assert isinstance(header, TaggedHeader)
    assert header.message_type == MessageType.LOAD_J2J_WORDS_RESP
    assert len(packet) == 1

    item = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    assert isinstance(item, WaitingLoadJ2JWords)
    response_tag = jamlet.j_in_k_index * jamlet.params.word_bytes + header.tag
    assert item.protocol_states[response_tag].src_state == SendState.WAITING_FOR_RESPONSE
    item.protocol_states[response_tag].src_state = SendState.COMPLETE


@register_handler(MessageType.LOAD_J2J_WORDS_DROP)
def handle_drop(jamlet, packet: List[Any]) -> None:
    '''SRC jamlet receives drop, will retry.'''
    header = packet[0]
    assert isinstance(header, TaggedHeader)
    assert header.message_type == MessageType.LOAD_J2J_WORDS_DROP
    assert len(packet) == 1

    item = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    assert isinstance(item, WaitingLoadJ2JWords)
    response_tag = jamlet.j_in_k_index * jamlet.params.word_bytes + header.tag
    item.protocol_states[response_tag].src_state = SendState.NEED_TO_SEND


async def send_drop(jamlet, rcvd_header: TaggedHeader) -> None:
    header = TaggedHeader(
        target_x=rcvd_header.source_x,
        target_y=rcvd_header.source_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        send_type=SendType.SINGLE,
        message_type=MessageType.LOAD_J2J_WORDS_DROP,
        length=1,
        ident=rcvd_header.ident,
        tag=rcvd_header.tag,
    )
    packet = [header]

    # Look up transaction (SRC sent REQ, we are DST sending DROP back)
    transaction_span_id = jamlet.monitor.get_transaction_span_id(
        rcvd_header.ident, rcvd_header.tag,
        rcvd_header.source_x, rcvd_header.source_y, jamlet.x, jamlet.y)

    await jamlet.send_packet(packet, parent_span_id=transaction_span_id)


async def send_resp(jamlet, rcvd_header: TaggedHeader) -> None:
    assert jamlet.x == rcvd_header.target_x
    assert jamlet.y == rcvd_header.target_y
    header = TaggedHeader(
        target_x=rcvd_header.source_x,
        target_y=rcvd_header.source_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        send_type=SendType.SINGLE,
        message_type=MessageType.LOAD_J2J_WORDS_RESP,
        length=1,
        ident=rcvd_header.ident,
        tag=rcvd_header.tag,
    )
    packet = [header]

    # Look up transaction (SRC sent REQ, we are DST sending RESP back)
    transaction_span_id = jamlet.monitor.get_transaction_span_id(
        rcvd_header.ident, rcvd_header.tag,
        rcvd_header.source_x, rcvd_header.source_y, jamlet.x, jamlet.y)

    await jamlet.send_packet(packet, parent_span_id=transaction_span_id)
