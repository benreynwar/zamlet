'''
Store J2J Words Transaction

Handles unaligned vector stores where data must be transferred between jamlets via
jamlet-to-jamlet (J2J) messaging. Used when the store is not aligned to the vline or
when element widths don't match between source and destination.

Messages:
    STORE_J2J_WORDS_REQ   - SRC jamlet sends register data to DST jamlet
    STORE_J2J_WORDS_RESP  - DST jamlet acknowledges receipt (wrote to cache)
    STORE_J2J_WORDS_DROP  - DST jamlet wasn't ready, SRC should retry
    STORE_J2J_WORDS_RETRY - DST asks SRC to resend (after cache becomes available)
'''
from typing import List, Any, TYPE_CHECKING
import logging

from zamlet import addresses, utils
from zamlet.waiting_item import WaitingItemRequiresCache
from zamlet.message import TaggedHeader, MessageType, SendType
from zamlet.kamlet.cache_table import SendState, ReceiveState, StoreProtocolState, CacheState
from zamlet.kamlet import kinstructions
from zamlet.params import LamletParams
from zamlet.transactions import register_handler
from zamlet.transactions.j2j_mapping import RegMemMapping, get_mapping_from_reg, get_mapping_from_mem

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet
    from zamlet.kamlet.kamlet import Kamlet

logger = logging.getLogger(__name__)


class WaitingStoreJ2JWords(WaitingItemRequiresCache):

    cache_is_write = True

    def __init__(self, params: LamletParams, instr: kinstructions.Store, rf_ident: int | None = None):
        super().__init__(
            item=instr, instr_ident=instr.instr_ident,
            writeset_ident=instr.writeset_ident, rf_ident=rf_ident)
        n_tags = params.word_bytes * params.j_in_k
        self.protocol_states: List[StoreProtocolState] = [
            StoreProtocolState() for _ in range(n_tags)]
        self.params = params

    def state_summary(self) -> str:
        """Return a compact summary of protocol states for logging."""
        parts = []
        for i, state in enumerate(self.protocol_states):
            src = 'C' if state.src_state == SendState.COMPLETE else \
                  'N' if state.src_state == SendState.NEED_TO_SEND else 'W'
            dst = 'C' if state.dst_state == ReceiveState.COMPLETE else \
                  'W' if state.dst_state == ReceiveState.WAITING_FOR_REQUEST else 'R'
            parts.append(f"{i}:{src}{dst}")
        return ' '.join(parts)

    def ready(self) -> bool:
        all_finished = all(state.finished() for state in self.protocol_states)
        is_ready = all_finished and self.cache_is_avail
        if not is_ready:
            unfinished = [(i, s.src_state.name, s.dst_state.name)
                          for i, s in enumerate(self.protocol_states) if not s.finished()]
            logger.debug(
                f'WaitingStoreJ2JWords ident={self.instr_ident} NOT ready: '
                f'cache_avail={self.cache_is_avail} unfinished={unfinished[:4]}...')
        return is_ready

    async def monitor_jamlet(self, jamlet: 'Jamlet') -> None:
        if not self.cache_is_avail:
            return
        instr = self.item
        assert isinstance(instr, kinstructions.Store)
        word_bytes = jamlet.params.word_bytes
        for tag in range(word_bytes):
            response_index = jamlet.j_in_k_index * word_bytes + tag
            protocol_state = self.protocol_states[response_index]
            if protocol_state.src_state == SendState.NEED_TO_SEND:
                await send_req(jamlet, self, tag)
            if protocol_state.dst_state == ReceiveState.NEED_TO_ASK_FOR_RESEND:
                await send_retry(jamlet, self, tag)

    async def finalize(self, kamlet: 'Kamlet') -> None:
        instr = self.item
        for pstate in self.protocol_states:
            assert pstate.finished()
        src_regs = kamlet.get_regs(
            start_index=instr.start_index, n_elements=instr.n_elements,
            ew=instr.src_ordering.ew, base_reg=instr.src)
        read_regs = src_regs + ([instr.mask_reg] if instr.mask_reg is not None else [])
        assert self.rf_ident is not None
        kamlet.rf_info.finish(self.rf_ident, write_regs=[], read_regs=read_regs)


def init_dst_state(jamlet, witem: WaitingStoreJ2JWords, tag: int) -> None:
    '''Initialize the dst_state for a given tag.'''
    instr = witem.item
    assert isinstance(instr, kinstructions.Store)

    mem_wb = tag * 8
    mappings = get_mapping_from_mem(
        params=jamlet.params, k_maddr=instr.k_maddr, reg_ordering=instr.src_ordering,
        start_index=instr.start_index, n_elements=instr.n_elements,
        mem_wb=mem_wb, mem_x=jamlet.x, mem_y=jamlet.y)

    word_bytes = jamlet.params.word_bytes
    response_tag = jamlet.j_in_k_index * word_bytes + tag
    if len(mappings) == 0:
        logger.debug(
            f'INIT_DST k={jamlet.k_index} j={jamlet.j_in_k_index} ident={instr.instr_ident} '
            f'tag={tag} resp_tag={response_tag}: no mappings -> COMPLETE')
        witem.protocol_states[response_tag].dst_state = ReceiveState.COMPLETE
    else:
        logger.debug(
            f'INIT_DST k={jamlet.k_index} j={jamlet.j_in_k_index} ident={instr.instr_ident} '
            f'tag={tag} resp_tag={response_tag}: {len(mappings)} mappings -> WAITING')


def init_src_state(jamlet, witem: WaitingStoreJ2JWords, tag: int) -> None:
    '''Initialize the src_state for a given tag.'''
    instr = witem.item
    assert isinstance(instr, kinstructions.Store)

    reg_wb = tag * 8
    mappings = get_mapping_from_reg(
        params=jamlet.params, k_maddr=instr.k_maddr, reg_ordering=instr.src_ordering,
        start_index=instr.start_index, n_elements=instr.n_elements,
        reg_wb=reg_wb, reg_x=jamlet.x, reg_y=jamlet.y)

    word_bytes = jamlet.params.word_bytes
    response_tag = jamlet.j_in_k_index * word_bytes + tag
    if len(mappings) == 0:
        logger.debug(
            f'INIT_SRC k={jamlet.k_index} j={jamlet.j_in_k_index} ident={instr.instr_ident} '
            f'tag={tag} resp_tag={response_tag}: no mappings -> COMPLETE')
        witem.protocol_states[response_tag].src_state = SendState.COMPLETE
    else:
        logger.debug(
            f'INIT_SRC k={jamlet.k_index} j={jamlet.j_in_k_index} ident={instr.instr_ident} '
            f'tag={tag} resp_tag={response_tag}: {len(mappings)} mappings -> NEED_TO_SEND')


async def send_req(jamlet, witem: WaitingStoreJ2JWords, tag: int) -> None:
    '''SRC jamlet reads register file and sends data to DST jamlet for cache write.'''
    instr = witem.item
    assert isinstance(instr, kinstructions.Store)
    params = jamlet.params

    reg_wb = tag * 8
    mappings = get_mapping_from_reg(
        params, k_maddr=instr.k_maddr, reg_ordering=instr.src_ordering,
        start_index=instr.start_index, n_elements=instr.n_elements,
        reg_wb=reg_wb, reg_x=jamlet.x, reg_y=jamlet.y)

    word_bytes = params.word_bytes
    response_tag = jamlet.j_in_k_index * word_bytes + tag

    if len(mappings) == 0:
        witem.protocol_states[response_tag].src_state = SendState.COMPLETE
        return

    words = []
    mem_vw = None
    reg_ew = instr.src_ordering.ew
    for mapping in mappings:
        src_reg = instr.src + mapping.reg_v
        word = jamlet.rf_slice[src_reg * word_bytes: (src_reg + 1) * word_bytes]
        logger.debug(
            f'jamlet ({jamlet.x}, {jamlet.y}): send_store_j2j_words_req tag={tag} '
            f'mapping={mapping} src_reg={src_reg} word={word.hex()}')
        words.append(word)
        if mem_vw is None:
            mem_vw = mapping.mem_vw
        assert mem_vw == mapping.mem_vw
    assert mem_vw is not None

    target_x, target_y = addresses.vw_index_to_j_coords(
        params, instr.k_maddr.ordering.word_order, mem_vw)
    witem.protocol_states[response_tag].src_state = SendState.WAITING_FOR_RESPONSE

    if instr.mask_reg is not None:
        mask_word = jamlet.rf_slice[instr.mask_reg * word_bytes: (instr.mask_reg + 1) * word_bytes]
        mask_word_int = int.from_bytes(mask_word, byteorder='little')
        mask_bits = []
        reg_elements_in_vline = params.vline_bytes * 8 // reg_ew
        reg_vw = addresses.j_coords_to_vw_index(params, instr.src_ordering.word_order, jamlet.x, jamlet.y)
        reg_ve = reg_wb // reg_ew * params.j_in_l + reg_vw
        for mapping in mappings:
            element_index = reg_ve + mapping.reg_v * reg_elements_in_vline
            word_element = element_index // params.j_in_l
            mask_bits.append((mask_word_int >> word_element) & 1)
    else:
        mask_bits = [1] * len(words)

    mask_bits_as_int = utils.list_of_uints_to_uint(mask_bits, width=1)

    header = TaggedHeader(
        target_x=target_x,
        target_y=target_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        length=1 + len(words),
        message_type=MessageType.STORE_J2J_WORDS_REQ,
        send_type=SendType.SINGLE,
        ident=instr.instr_ident,
        tag=tag,
        mask=mask_bits_as_int,
    )

    packet = [header] + words
    logger.debug(
        f'cycle {jamlet.clock.cycle}: jamlet {(jamlet.x, jamlet.y)}: '
        f'send_store_j2j_words_req to {(target_x, target_y)} ident={instr.instr_ident}')

    await jamlet.send_packet(packet)


@register_handler(MessageType.STORE_J2J_WORDS_REQ)
async def handle_req(jamlet, packet: List[Any]) -> None:
    '''DST jamlet receives data and writes to cache.'''
    header = packet[0]
    assert isinstance(header, TaggedHeader)
    assert header.message_type == MessageType.STORE_J2J_WORDS_REQ

    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    if witem is None:
        logger.debug(
            f'cycle {jamlet.clock.cycle}: jamlet {(jamlet.x, jamlet.y)}: '
            f'handle_store_j2j_words_req - dropping')
        await send_drop(jamlet, header)
        return
    assert isinstance(witem, WaitingStoreJ2JWords)
    slot = witem.cache_slot
    assert slot is not None
    instr = witem.item
    assert isinstance(instr, kinstructions.Store)
    params = jamlet.params

    reg_wb = header.tag * 8
    mappings = get_mapping_from_reg(
        params, k_maddr=instr.k_maddr, reg_ordering=instr.src_ordering,
        start_index=instr.start_index, n_elements=instr.n_elements,
        reg_wb=reg_wb, reg_x=header.source_x, reg_y=header.source_y)

    assert len(packet) >= 2
    words = packet[1:]
    assert len(mappings) == len(words)

    word_bytes = params.word_bytes
    mem_wb = None
    for word, mapping in zip(words, mappings):
        shift = mapping.reg_wb - mapping.mem_wb
        mask = ((1 << mapping.n_bits) - 1) << mapping.mem_wb

        assert isinstance(word, (bytes, bytearray))
        assert len(word) == word_bytes
        word_as_int = int.from_bytes(word, byteorder='little')
        word_mask = (1 << (word_bytes * 8)) - 1
        if shift < 0:
            shifted = word_as_int << (-shift)
        else:
            shifted = (word_as_int >> shift) & word_mask

        if mem_wb is None:
            mem_wb = mapping.mem_wb
        assert mem_wb == mapping.mem_wb

    assert mem_wb is not None
    response_tag = jamlet.j_in_k_index * word_bytes + mem_wb // 8

    if jamlet.cache_table.can_write(instr.k_maddr, witem=witem):
        assert witem.cache_is_avail

        cache_base_addr = slot * params.vlines_in_cache_line * word_bytes

        for word_index, (word, mapping) in enumerate(zip(words, mappings)):
            mask_bit = (header.mask >> word_index) & 1
            if not mask_bit:
                continue

            shift = mapping.reg_wb - mapping.mem_wb
            segment_mask = ((1 << mapping.n_bits) - 1) << mapping.mem_wb

            word_as_int = int.from_bytes(word, byteorder='little')
            word_mask = (1 << (word_bytes * 8)) - 1
            if shift < 0:
                shifted = (word_as_int << (-shift)) & word_mask
            else:
                shifted = word_as_int >> shift
            shifted_bytes = shifted.to_bytes(word_bytes, byteorder='little')

            vline_offset_in_cache = mapping.mem_v % params.vlines_in_cache_line
            cache_addr = cache_base_addr + vline_offset_in_cache * word_bytes
            old_word = jamlet.sram[cache_addr: cache_addr + word_bytes]
            updated_word = utils.update_bytes_word(
                old_word=old_word, new_word=shifted_bytes, mask=segment_mask)
            jamlet.sram[cache_addr: cache_addr + word_bytes] = updated_word
            logger.debug(
                f'{jamlet.clock.cycle}: CACHE_WRITE STORE_J2J: jamlet ({jamlet.x},{jamlet.y}) '
                f'sram[{cache_addr}] old={old_word.hex()} new={updated_word.hex()} '
                f'mapping={mapping} shift={shift} mask=0x{segment_mask:x}')

        assert witem.protocol_states[response_tag].dst_state == ReceiveState.WAITING_FOR_REQUEST
        witem.protocol_states[response_tag].dst_state = ReceiveState.COMPLETE
        cache_state = jamlet.cache_table.slot_states[slot]
        assert cache_state.state in (CacheState.SHARED, CacheState.MODIFIED)
        cache_state.state = CacheState.MODIFIED
        logger.info(
            f'jamlet ({jamlet.x}, {jamlet.y}): handle_store_j2j_words_req - '
            f'wrote to cache, sending resp')
        await send_resp(jamlet, header)
    else:
        witem.protocol_states[response_tag].dst_state = ReceiveState.NEED_TO_ASK_FOR_RESEND
        assert not witem.cache_is_avail
        logger.debug(
            f'jamlet ({jamlet.x}, {jamlet.y}): handle_store_j2j_words_req - '
            f"can't write, waiting for cache")


@register_handler(MessageType.STORE_J2J_WORDS_RESP)
def handle_resp(jamlet, packet: List[Any]) -> None:
    '''SRC jamlet receives acknowledgment from DST.'''
    header = packet[0]
    assert isinstance(header, TaggedHeader)
    assert header.message_type == MessageType.STORE_J2J_WORDS_RESP
    assert len(packet) == 1

    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    assert isinstance(witem, WaitingStoreJ2JWords)
    word_bytes = jamlet.params.word_bytes
    response_tag = jamlet.j_in_k_index * word_bytes + header.tag
    logger.info(
        f'jamlet ({jamlet.x}, {jamlet.y}): handle_store_j2j_words_resp from '
        f'({header.source_x}, {header.source_y}) tag={header.tag} ident={header.ident}')
    logger.info(
        f'{jamlet.clock.cycle}: jamlet ({jamlet.x}, {jamlet.y}): response_tag={response_tag}, '
        f'j_in_k={jamlet.j_in_k_index}, header.tag={header.tag}, '
        f'actual_state={witem.protocol_states[response_tag].src_state}')
    assert witem.protocol_states[response_tag].src_state == SendState.WAITING_FOR_RESPONSE
    witem.protocol_states[response_tag].src_state = SendState.COMPLETE


@register_handler(MessageType.STORE_J2J_WORDS_DROP)
def handle_drop(jamlet, packet: List[Any]) -> None:
    '''SRC jamlet receives drop, will retry.'''
    header = packet[0]
    assert isinstance(header, TaggedHeader)
    assert header.message_type == MessageType.STORE_J2J_WORDS_DROP
    assert len(packet) == 1

    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    assert isinstance(witem, WaitingStoreJ2JWords)
    word_bytes = jamlet.params.word_bytes
    response_tag = jamlet.j_in_k_index * word_bytes + header.tag
    assert witem.protocol_states[response_tag].src_state == SendState.WAITING_FOR_RESPONSE
    witem.protocol_states[response_tag].src_state = SendState.NEED_TO_SEND


@register_handler(MessageType.STORE_J2J_WORDS_RETRY)
def handle_retry(jamlet, packet: List[Any]) -> None:
    '''SRC jamlet receives retry request from DST.'''
    header = packet[0]
    assert isinstance(header, TaggedHeader)
    assert header.message_type == MessageType.STORE_J2J_WORDS_RETRY
    assert len(packet) == 1

    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    assert isinstance(witem, WaitingStoreJ2JWords)
    word_bytes = jamlet.params.word_bytes
    response_tag = jamlet.j_in_k_index * word_bytes + header.tag
    logger.debug(
        f'{jamlet.clock.cycle} jamlet {(jamlet.x, jamlet.y)}: handle_store_j2j_words_retry '
        f'src_state={witem.protocol_states[response_tag].src_state} '
        f'instr_ident={witem.instr_ident} response_tag={response_tag}')
    assert witem.protocol_states[response_tag].src_state == SendState.WAITING_FOR_RESPONSE
    witem.protocol_states[response_tag].src_state = SendState.NEED_TO_SEND


async def send_drop(jamlet, rcvd_header: TaggedHeader) -> None:
    header = TaggedHeader(
        target_x=rcvd_header.source_x,
        target_y=rcvd_header.source_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        send_type=SendType.SINGLE,
        message_type=MessageType.STORE_J2J_WORDS_DROP,
        length=1,
        ident=rcvd_header.ident,
        tag=rcvd_header.tag,
    )
    packet = [header]
    await jamlet.send_packet(packet)


async def send_resp(jamlet, rcvd_header: TaggedHeader) -> None:
    header = TaggedHeader(
        target_x=rcvd_header.source_x,
        target_y=rcvd_header.source_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        send_type=SendType.SINGLE,
        message_type=MessageType.STORE_J2J_WORDS_RESP,
        length=1,
        ident=rcvd_header.ident,
        tag=rcvd_header.tag,
    )
    packet = [header]
    await jamlet.send_packet(packet)


async def send_retry(jamlet, witem: WaitingStoreJ2JWords, tag: int) -> None:
    '''DST jamlet asks SRC to resend data (cache is now available).'''
    assert witem.instr_ident is not None
    instr = witem.item
    assert isinstance(instr, kinstructions.Store)
    params = jamlet.params

    mem_wb = tag * 8
    mappings = get_mapping_from_mem(
        params, k_maddr=instr.k_maddr, reg_ordering=instr.src_ordering,
        start_index=instr.start_index, n_elements=instr.n_elements,
        mem_wb=mem_wb, mem_x=jamlet.x, mem_y=jamlet.y)

    assert len(mappings) > 0

    reg_vw = None
    reg_wb = None
    for mapping in mappings:
        if reg_vw is None:
            reg_vw = mapping.reg_vw
        if reg_wb is None:
            reg_wb = mapping.reg_wb
        assert reg_vw == mapping.reg_vw
        assert reg_wb == mapping.reg_wb
    assert reg_vw is not None
    assert reg_wb is not None

    target_x, target_y = addresses.vw_index_to_j_coords(
        params, instr.src_ordering.word_order, reg_vw)

    src_tag = reg_wb // 8
    logger.debug(
        f'{jamlet.clock.cycle}: jamlet {(jamlet.x, jamlet.y)}: send_store_j2j_words_retry '
        f'ident={witem.instr_ident} mem_tag={tag} src_tag={src_tag} to {(target_x, target_y)}')
    header = TaggedHeader(
        target_x=target_x,
        target_y=target_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        send_type=SendType.SINGLE,
        message_type=MessageType.STORE_J2J_WORDS_RETRY,
        length=1,
        ident=witem.instr_ident,
        tag=src_tag,
    )
    packet = [header]
    word_bytes = params.word_bytes
    ptag = jamlet.j_in_k_index * word_bytes + tag
    assert witem.protocol_states[ptag].dst_state == ReceiveState.NEED_TO_ASK_FOR_RESEND
    witem.protocol_states[ptag].dst_state = ReceiveState.WAITING_FOR_REQUEST
    await jamlet.send_packet(packet)
