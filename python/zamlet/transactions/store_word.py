'''
Store Word Transaction

Handles partial word stores that cross cache line boundaries between kamlets.
Data flows from a SRC kamlet (which has the register) to a DST kamlet
(which has the cache line to write).

Messages:
    STORE_WORD_REQ   - SRC jamlet sends word data to DST jamlet
    STORE_WORD_RESP  - DST jamlet acknowledges receipt
    STORE_WORD_DROP  - DST jamlet wasn't ready, SRC should retry
    STORE_WORD_RETRY - DST asks SRC to resend (after becoming ready)
'''
from typing import List, Any, TYPE_CHECKING
import logging

from zamlet import addresses
from zamlet.waiting_item import WaitingItem, WaitingItemRequiresCache
from zamlet.message import TaggedHeader, MessageType, SendType
from zamlet.kamlet.cache_table import SendState, ReceiveState, CacheState
from zamlet.kamlet import kinstructions
from zamlet.params import LamletParams
from zamlet.transactions import register_handler

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet
    from zamlet.kamlet.kamlet import Kamlet

logger = logging.getLogger(__name__)


class WaitingStoreWordSrc(WaitingItem):

    def __init__(self, params: LamletParams, instr: kinstructions.StoreWord, rf_ident: int):
        super().__init__(item=instr, instr_ident=instr.instr_ident, rf_ident=rf_ident)
        self.protocol_states = [SendState.COMPLETE for _ in range(params.j_in_k)]
        self.writeset_ident = instr.writeset_ident

    def ready(self) -> bool:
        return all(state == SendState.COMPLETE for state in self.protocol_states)

    async def monitor_jamlet(self, jamlet: 'Jamlet') -> None:
        if self.protocol_states[jamlet.j_in_k_index] == SendState.NEED_TO_SEND:
            await send_req(jamlet, self)

    async def finalize(self, kamlet: 'Kamlet') -> None:
        assert all(state == SendState.COMPLETE for state in self.protocol_states)
        assert self.rf_ident is not None
        instr = self.item
        read_regs = [instr.src.reg] + ([instr.mask_reg] if instr.mask_reg is not None else [])
        kamlet.rf_info.finish(self.rf_ident, read_regs=read_regs)


class WaitingStoreWordDst(WaitingItemRequiresCache):

    cache_is_write = True

    def __init__(self, params: LamletParams, instr: kinstructions.StoreWord):
        super().__init__(
            item=instr, instr_ident=instr.instr_ident + 1,
            writeset_ident=instr.writeset_ident, rf_ident=None)
        self.protocol_states = [ReceiveState.COMPLETE for _ in range(params.j_in_k)]

    def ready(self) -> bool:
        return all(state == ReceiveState.COMPLETE for state in self.protocol_states) and self.cache_is_avail

    async def monitor_jamlet(self, jamlet: 'Jamlet') -> None:
        if self.protocol_states[jamlet.j_in_k_index] == ReceiveState.NEED_TO_ASK_FOR_RESEND:
            if self.cache_is_avail:
                await send_retry(jamlet, self)

    async def finalize(self, kamlet: 'Kamlet') -> None:
        assert all(state == ReceiveState.COMPLETE for state in self.protocol_states)


def init_src_state(jamlet: 'Jamlet', witem: WaitingStoreWordSrc) -> None:
    """Initialize protocol state for SRC jamlet."""
    instr = witem.item
    is_src = (instr.src.k_index == jamlet.k_index and
              instr.src.j_in_k_index == jamlet.j_in_k_index)
    if is_src:
        logger.debug(
            f'{jamlet.clock.cycle}: jamlet {(jamlet.x, jamlet.y)}: '
            f'setting j_in_k={jamlet.j_in_k_index} to NEED_TO_SEND')
        witem.protocol_states[jamlet.j_in_k_index] = SendState.NEED_TO_SEND


def init_dst_state(jamlet: 'Jamlet', witem: WaitingStoreWordDst) -> None:
    """Initialize protocol state for DST jamlet."""
    instr = witem.item
    is_dst = (instr.dst.k_index == jamlet.k_index and
              instr.dst.j_in_k_index == jamlet.j_in_k_index)
    if is_dst:
        logger.debug(
            f'{jamlet.clock.cycle}: jamlet {(jamlet.x, jamlet.y)}: '
            f'setting j_in_k={jamlet.j_in_k_index} to WAITING_FOR_REQUEST')
        witem.protocol_states[jamlet.j_in_k_index] = ReceiveState.WAITING_FOR_REQUEST


async def send_req(jamlet: 'Jamlet', witem: WaitingStoreWordSrc) -> None:
    """SRC jamlet sends request with data to DST jamlet."""
    instr = witem.item

    target_x, target_y = addresses.k_indices_to_j_coords(
        jamlet.params, instr.dst.k_index, instr.dst.j_in_k_index)

    witem.protocol_states[jamlet.j_in_k_index] = SendState.WAITING_FOR_RESPONSE

    wb = jamlet.params.word_bytes
    word_addr = (instr.src.reg * wb // wb) * wb
    word = jamlet.rf_slice[word_addr : word_addr + wb]

    logger.debug(
        f'{jamlet.clock.cycle}: STORE_WORD: jamlet ({jamlet.x}, {jamlet.y}): '
        f'send_store_word_req to ({target_x}, {target_y}) ident={instr.instr_ident} '
        f'reg={instr.src.reg} word={word.hex()}')

    header = TaggedHeader(
        target_x=target_x, target_y=target_y,
        source_x=jamlet.x, source_y=jamlet.y,
        message_type=MessageType.STORE_WORD_REQ,
        send_type=SendType.SINGLE,
        length=2,
        ident=instr.instr_ident, tag=0)

    await jamlet.send_packet([header, word])


@register_handler(MessageType.STORE_WORD_REQ)
async def handle_req(jamlet: 'Jamlet', packet: List[Any]) -> None:
    """DST jamlet receives request with data, writes to cache, sends response."""
    header = packet[0]
    word = packet[1]

    logger.debug(
        f'{jamlet.clock.cycle}: STORE_WORD: jamlet ({jamlet.x}, {jamlet.y}): '
        f'handle_store_word_req from ({header.source_x}, {header.source_y}) ident={header.ident}')

    dst_ident = header.ident + 1
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(dst_ident)
    if witem is None:
        witems_debug = [
            (i, w.instr_ident, type(w).__name__)
            for i, w in enumerate(jamlet.cache_table.waiting_items) if w is not None]
        logger.debug(
            f'{jamlet.clock.cycle}: STORE_WORD: jamlet ({jamlet.x}, {jamlet.y}): '
            f'DROP - no witem. Waiting items: {witems_debug}')
        await send_drop(jamlet, header)
        return

    assert isinstance(witem, WaitingStoreWordDst)
    if not witem.cache_is_avail:
        logger.debug(
            f'{jamlet.clock.cycle}: STORE_WORD: jamlet ({jamlet.x}, {jamlet.y}): '
            f'cache not ready, setting NEED_TO_ASK_FOR_RESEND')
        witem.protocol_states[jamlet.j_in_k_index] = ReceiveState.NEED_TO_ASK_FOR_RESEND
        return

    assert witem.protocol_states[jamlet.j_in_k_index] == ReceiveState.WAITING_FOR_REQUEST
    instr = witem.item
    word_as_int = int.from_bytes(word, byteorder='little')

    j_saddr = instr.dst.to_j_saddr(jamlet.cache_table)
    wb = jamlet.params.word_bytes
    sram_addr = (j_saddr.addr // wb) * wb

    old_word = jamlet.sram[sram_addr : sram_addr + wb]
    old_word_as_int = int.from_bytes(old_word, byteorder='little')

    src_word_offset = instr.src.offset_in_word
    dst_word_offset = instr.dst.addr % wb
    shift_bytes = src_word_offset - dst_word_offset
    shift_bits = shift_bytes * 8

    logger.debug(
        f'{jamlet.clock.cycle}: STORE_WORD: jamlet ({jamlet.x}, {jamlet.y}): '
        f'src.offset_in_word={src_word_offset}, dst.addr={instr.dst.addr}, '
        f'dst_word_offset={dst_word_offset}, shift_bytes={shift_bytes}')

    dst_expanded_mask = 0
    for byte_idx in range(wb):
        if instr.byte_mask & (1 << byte_idx):
            dst_expanded_mask |= (0xFF << (byte_idx * 8))

    if shift_bits < 0:
        shifted_word = word_as_int << (-shift_bits)
    else:
        shifted_word = word_as_int >> shift_bits

    masked_new = shifted_word & dst_expanded_mask
    masked_old = old_word_as_int & (~dst_expanded_mask)
    result = masked_old | masked_new

    result_bytes = result.to_bytes(wb, byteorder='little')
    old_bytes = old_word_as_int.to_bytes(wb, byteorder='little')
    jamlet.sram[sram_addr : sram_addr + wb] = result_bytes
    logger.debug(
        f'{jamlet.clock.cycle}: CACHE_WRITE STORE_WORD: jamlet ({jamlet.x},{jamlet.y}) '
        f'sram[{sram_addr}] old={old_bytes.hex()} new={result_bytes.hex()}')

    slot = witem.cache_slot
    assert slot is not None
    jamlet.cache_table.slot_states[slot].state = CacheState.MODIFIED

    witem.protocol_states[jamlet.j_in_k_index] = ReceiveState.COMPLETE

    logger.debug(
        f'{jamlet.clock.cycle}: STORE_WORD: jamlet ({jamlet.x}, {jamlet.y}): '
        f'wrote to sram_addr={sram_addr} result={result_bytes.hex()}')

    await send_resp(jamlet, header)


async def send_resp(jamlet: 'Jamlet', rcvd_header: TaggedHeader) -> None:
    """DST sends acknowledgment response to SRC."""
    header = TaggedHeader(
        target_x=rcvd_header.source_x, target_y=rcvd_header.source_y,
        source_x=jamlet.x, source_y=jamlet.y,
        message_type=MessageType.STORE_WORD_RESP,
        send_type=SendType.SINGLE,
        length=1,
        ident=rcvd_header.ident, tag=0)
    await jamlet.send_packet([header])


async def send_drop(jamlet: 'Jamlet', rcvd_header: TaggedHeader) -> None:
    """DST sends drop response to SRC."""
    header = TaggedHeader(
        target_x=rcvd_header.source_x, target_y=rcvd_header.source_y,
        source_x=jamlet.x, source_y=jamlet.y,
        message_type=MessageType.STORE_WORD_DROP,
        send_type=SendType.SINGLE,
        length=1,
        ident=rcvd_header.ident, tag=0)
    await jamlet.send_packet([header])


@register_handler(MessageType.STORE_WORD_RESP)
def handle_resp(jamlet: 'Jamlet', packet: List[Any]) -> None:
    """SRC jamlet receives acknowledgment response."""
    header = packet[0]
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    assert isinstance(witem, WaitingStoreWordSrc)

    logger.debug(
        f'{jamlet.clock.cycle}: STORE_WORD: jamlet ({jamlet.x}, {jamlet.y}): '
        f'handle_store_word_resp from ({header.source_x}, {header.source_y}) - COMPLETE')

    assert witem.protocol_states[jamlet.j_in_k_index] == SendState.WAITING_FOR_RESPONSE
    witem.protocol_states[jamlet.j_in_k_index] = SendState.COMPLETE


@register_handler(MessageType.STORE_WORD_DROP)
def handle_drop(jamlet: 'Jamlet', packet: List[Any]) -> None:
    """SRC jamlet receives drop, will retry request."""
    header = packet[0]
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    assert isinstance(witem, WaitingStoreWordSrc)

    logger.debug(
        f'{jamlet.clock.cycle}: STORE_WORD: jamlet ({jamlet.x}, {jamlet.y}): '
        f'handle_store_word_drop from ({header.source_x}, {header.source_y}) - will RETRY')

    witem.protocol_states[jamlet.j_in_k_index] = SendState.NEED_TO_SEND


async def send_retry(jamlet: 'Jamlet', witem: WaitingStoreWordDst) -> None:
    """DST jamlet sends retry to SRC when it becomes ready."""
    instr = witem.item

    target_x, target_y = addresses.k_indices_to_j_coords(
        jamlet.params, instr.src.k_index, instr.src.j_in_k_index)

    witem.protocol_states[jamlet.j_in_k_index] = ReceiveState.WAITING_FOR_REQUEST

    header = TaggedHeader(
        target_x=target_x, target_y=target_y,
        source_x=jamlet.x, source_y=jamlet.y,
        message_type=MessageType.STORE_WORD_RETRY,
        send_type=SendType.SINGLE,
        length=1,
        ident=instr.instr_ident, tag=0)

    await jamlet.send_packet([header])


@register_handler(MessageType.STORE_WORD_RETRY)
def handle_retry(jamlet: 'Jamlet', packet: List[Any]) -> None:
    """SRC jamlet receives retry, resend request."""
    header = packet[0]
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    assert isinstance(witem, WaitingStoreWordSrc)

    witem.protocol_states[jamlet.j_in_k_index] = SendState.NEED_TO_SEND
