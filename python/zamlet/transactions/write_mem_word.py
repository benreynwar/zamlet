'''
Write Memory Word Transaction

Handles writing a word to another jamlet's cache. This is used by transactions
that need to write data to a different jamlet's memory space (e.g., strided stores).

Messages:
    WRITE_MEM_WORD_REQ   - Request to write a word to another jamlet's cache
    WRITE_MEM_WORD_RESP  - Write completed successfully
    WRITE_MEM_WORD_DROP  - Request couldn't be handled, sender should retry
    WRITE_MEM_WORD_RETRY - Cache became ready, sender should resend data

Flow:
1. Requester sends WRITE_MEM_WORD_REQ with data to target jamlet
2. Target checks if cache line is available for writing
3. If yes, writes data to sram, sends WRITE_MEM_WORD_RESP
4. If no but can allocate waiting item, creates WaitingWriteMemWord
   - When cache ready, sends WRITE_MEM_WORD_RETRY (requester must resend)
5. If can't allocate, sends WRITE_MEM_WORD_DROP (requester retries later)
'''
from typing import List, Any, TYPE_CHECKING
import logging

from zamlet import addresses
from zamlet.addresses import JSAddr
from zamlet.message import WriteMemWordHeader, TaggedHeader, MessageType, SendType
from zamlet.waiting_item import WaitingItemRequiresCache
from zamlet.transactions import register_handler
from zamlet.kamlet.cache_table import CacheState, ReceiveState
from zamlet import utils

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


class WaitingWriteMemWord(WaitingItemRequiresCache):
    '''
    Waiting item for a WriteMemWord request where the cache line isn't ready yet.
    When cache becomes ready, sends RETRY so the requester can resend the data.
    The item stays in waiting_items to hold the cache slot until the write completes.
    '''

    cache_is_write = True
    use_source_to_match = True

    def __init__(self, header: WriteMemWordHeader, cache_slot: int, j_saddr: addresses.JSAddr,
                 writeset_ident: int | None = None):
        super().__init__(item=header, instr_ident=header.ident, cache_slot=cache_slot,
                         writeset_ident=writeset_ident,
                         source=(header.source_x, header.source_y))
        self.j_saddr = j_saddr
        self.state = ReceiveState.NEED_TO_ASK_FOR_RESEND

    def ready(self):
        return self.state == ReceiveState.COMPLETE

    async def monitor_kamlet(self, kamlet) -> None:
        '''Send RETRY when cache becomes ready, then wait for resent REQ.'''
        if self.state == ReceiveState.NEED_TO_ASK_FOR_RESEND and self.cache_is_avail:
            jamlet = kamlet.jamlets[self.j_saddr.j_in_k_index]
            await send_retry(jamlet, self.item)
            self.state = ReceiveState.WAITING_FOR_REQUEST

    async def finalize(self, kamlet) -> None:
        '''Called when write is complete.'''
        pass


@register_handler(MessageType.WRITE_MEM_WORD_REQ)
async def handle_req(jamlet: 'Jamlet', packet: List[Any]) -> None:
    '''
    Handle a WRITE_MEM_WORD_REQ packet. Check if we can write to cache,
    and either write immediately or create a waiting item.

    Packet format: [header, addr, data]
    '''
    header = packet[0]
    assert isinstance(header, WriteMemWordHeader)
    addr = packet[1]
    assert isinstance(addr, addresses.KMAddr)
    data = packet[2]
    src_start = header.tag
    dst_start = header.dst_byte_in_word
    n_bytes = header.n_bytes
    assert header.message_type == MessageType.WRITE_MEM_WORD_REQ

    # Check if the parent instruction exists on this jamlet
    parent_ident = (header.ident - header.tag - 1) % jamlet.params.max_response_tags
    parent_witem = jamlet.cache_table.get_waiting_item_by_instr_ident(parent_ident)
    if parent_witem is None:
        logger.debug(f'{jamlet.clock.cycle}: WRITE_MEM_WORD_REQ: jamlet ({jamlet.x},{jamlet.y}) '
                     f'parent_ident={parent_ident} not found, sending DROP')
        await send_drop(jamlet, header)
        return

    can_write = jamlet.cache_table.can_write(addr, witem=parent_witem)
    slot = jamlet.cache_table.addr_to_slot(addr)
    slot_in_use = slot is not None and jamlet.cache_table.slot_in_use(
        slot, writeset_ident=parent_witem.writeset_ident)

    # Check if there's a WaitingWriteMemWord waiting for this resend
    existing_witem = jamlet.cache_table.get_waiting_item_by_instr_ident(
        header.ident, source=(header.source_x, header.source_y))
    if existing_witem is not None:
        # This is a resend after RETRY - complete the write
        assert isinstance(existing_witem, WaitingWriteMemWord), \
            f'Expected WaitingWriteMemWord, got {type(existing_witem).__name__} ' \
            f'header.ident={header.ident} existing_witem.instr_ident={existing_witem.instr_ident} ' \
            f'source=({header.source_x},{header.source_y})'
        assert existing_witem.state == ReceiveState.WAITING_FOR_REQUEST, \
            f'Expected WAITING_FOR_REQUEST, got {existing_witem.state}, ident={header.ident}'
        j_saddr = addr.to_j_saddr(jamlet.cache_table)
        logger.debug(f'{jamlet.clock.cycle}: WRITE_MEM_WORD_REQ: jamlet ({jamlet.x},{jamlet.y}) '
                     f'resend after RETRY addr=0x{addr.addr:x} slot={existing_witem.cache_slot}')
        await do_write_and_respond(jamlet, header, j_saddr, data, src_start, dst_start, n_bytes,
                                   existing_witem.cache_slot)
        existing_witem.state = ReceiveState.COMPLETE
    elif can_write:
        # Slot exists, state is ready, no clashing witem - write immediately
        j_saddr = addr.to_j_saddr(jamlet.cache_table)
        logger.debug(f'{jamlet.clock.cycle}: WRITE_MEM_WORD_REQ: jamlet ({jamlet.x},{jamlet.y}) '
                     f'can_write addr=0x{addr.addr:x} slot={slot}')
        await do_write_and_respond(jamlet, header, j_saddr, data, src_start, dst_start, n_bytes,
                                   slot)
    elif slot is not None and not slot_in_use:
        # Slot exists but state not ready, no clashing witem - create witem to wait
        can_get_witem = jamlet.cache_table.can_get_free_witem_index()
        if can_get_witem:
            slot_state = jamlet.cache_table.slot_states[slot]
            j_saddr = addr.to_j_saddr(jamlet.cache_table)
            witem = WaitingWriteMemWord(header, slot, j_saddr,
                                        writeset_ident=parent_witem.writeset_ident)
            jamlet.cache_table.add_witem_immediately(witem)
            logger.debug(f'{jamlet.clock.cycle}: WRITE_MEM_WORD_REQ: jamlet ({jamlet.x},{jamlet.y}) '
                         f'created WaitingWriteMemWord for slot={slot} '
                         f'state={slot_state.state} addr=0x{addr.addr:x}')
        else:
            logger.debug(f'{jamlet.clock.cycle}: WRITE_MEM_WORD_REQ: jamlet ({jamlet.x},{jamlet.y}) '
                         f'DROP addr=0x{addr.addr:x} reason=no_free_witem')
            await send_drop(jamlet, header)
    elif slot is None:
        # No slot exists - try to allocate one and create witem
        can_get_witem = jamlet.cache_table.can_get_free_witem_index()
        can_get_slot = jamlet.cache_table.can_get_slot(addr)
        if can_get_witem and can_get_slot:
            cache_slot = jamlet.cache_table.get_slot_if_exists(addr)
            assert cache_slot is not None
            slot_state = jamlet.cache_table.slot_states[cache_slot]
            j_saddr = addr.to_j_saddr(jamlet.cache_table)
            witem = WaitingWriteMemWord(header, cache_slot, j_saddr,
                                        writeset_ident=parent_witem.writeset_ident)
            jamlet.cache_table.add_witem_immediately(witem)
            logger.debug(f'{jamlet.clock.cycle}: WRITE_MEM_WORD_REQ: jamlet ({jamlet.x},{jamlet.y}) '
                         f'allocated slot={cache_slot} created WaitingWriteMemWord '
                         f'state={slot_state.state} addr=0x{addr.addr:x}')
        else:
            logger.debug(f'{jamlet.clock.cycle}: WRITE_MEM_WORD_REQ: jamlet ({jamlet.x},{jamlet.y}) '
                         f'DROP addr=0x{addr.addr:x} reason=no_slot_or_witem')
            await send_drop(jamlet, header)
    else:
        # Slot in use by clashing witem - DROP
        logger.debug(f'{jamlet.clock.cycle}: WRITE_MEM_WORD_REQ: jamlet ({jamlet.x},{jamlet.y}) '
                     f'DROP addr=0x{addr.addr:x} reason=slot_in_use')
        await send_drop(jamlet, header)


@register_handler(MessageType.WRITE_MEM_WORD_RESP)
def handle_resp(jamlet: 'Jamlet', packet: List[Any]) -> None:
    '''
    Handle a WRITE_MEM_WORD_RESP packet. Find the waiting item by ident
    and mark the tag as complete.
    '''
    header = packet[0]
    parent_ident = (header.ident - header.tag - 1) % jamlet.params.max_response_tags
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(parent_ident)
    witem.process_response(jamlet, packet)


@register_handler(MessageType.WRITE_MEM_WORD_DROP)
def handle_drop(jamlet: 'Jamlet', packet: List[Any]) -> None:
    '''
    Handle a WRITE_MEM_WORD_DROP packet. Find the waiting item and mark
    for retry.
    '''
    header = packet[0]
    parent_ident = (header.ident - header.tag - 1) % jamlet.params.max_response_tags
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(parent_ident)
    witem.process_drop(jamlet, packet)


@register_handler(MessageType.WRITE_MEM_WORD_RETRY)
def handle_retry(jamlet: 'Jamlet', packet: List[Any]) -> None:
    '''
    Handle a WRITE_MEM_WORD_RETRY packet. The target's cache is now ready,
    so mark for resend.
    '''
    header = packet[0]
    parent_ident = (header.ident - header.tag - 1) % jamlet.params.max_response_tags
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(parent_ident)
    witem.process_drop(jamlet, packet)  # Same handling as DROP - mark for resend


async def do_write_and_respond(jamlet: 'Jamlet', rcvd_header: WriteMemWordHeader,
                                j_saddr: JSAddr, data: bytes,
                                src_start: int, dst_start: int, n_bytes: int,
                                slot: int) -> None:
    '''Write data to cache and send WRITE_MEM_WORD_RESP.'''
    assert j_saddr.k_index == jamlet.k_index
    assert j_saddr.j_in_k_index == jamlet.j_in_k_index
    j_cache_line_bits = jamlet.params.cache_line_bytes * 8 // jamlet.params.j_in_k
    expected_slot = j_saddr.bit_addr // j_cache_line_bits
    assert expected_slot == slot, f'j_saddr slot {expected_slot} does not match slot {slot}'
    slot_state = jamlet.cache_table.slot_states[slot]
    assert slot_state.state in (CacheState.SHARED, CacheState.MODIFIED), \
        f'Expected SHARED or MODIFIED, got {slot_state.state}'

    wb = jamlet.params.word_bytes
    sram_addr = j_saddr.addr // wb * wb

    old_word = jamlet.sram[sram_addr: sram_addr + wb]
    new_word = utils.shift_and_update_word(
        old_word=old_word,
        src_word=data,
        src_start=src_start,
        dst_start=dst_start,
        n_bytes=n_bytes,
    )
    jamlet.sram[sram_addr: sram_addr + wb] = new_word
    logger.debug(f'{jamlet.clock.cycle}: CACHE_WRITE WRITE_MEM_WORD: jamlet ({jamlet.x},{jamlet.y}) '
                 f'ident={rcvd_header.ident} tag={rcvd_header.tag} '
                 f'sram[{sram_addr}] old={old_word.hex()} new={new_word.hex()}')

    slot_state.state = CacheState.MODIFIED

    header = TaggedHeader(
        target_x=rcvd_header.source_x, target_y=rcvd_header.source_y,
        source_x=jamlet.x, source_y=jamlet.y,
        message_type=MessageType.WRITE_MEM_WORD_RESP,
        send_type=SendType.SINGLE,
        length=1,
        tag=rcvd_header.tag,
        ident=rcvd_header.ident)
    await jamlet.send_packet([header])


async def send_drop(jamlet: 'Jamlet', rcvd_header: WriteMemWordHeader) -> None:
    '''Send WRITE_MEM_WORD_DROP indicating request couldn't be handled.'''
    header = TaggedHeader(
        target_x=rcvd_header.source_x, target_y=rcvd_header.source_y,
        source_x=jamlet.x, source_y=jamlet.y,
        message_type=MessageType.WRITE_MEM_WORD_DROP,
        send_type=SendType.SINGLE,
        length=1,
        tag=rcvd_header.tag,
        ident=rcvd_header.ident)
    await jamlet.send_packet([header])


async def send_retry(jamlet: 'Jamlet', rcvd_header: WriteMemWordHeader) -> None:
    '''Send WRITE_MEM_WORD_RETRY indicating cache is now ready.'''
    header = TaggedHeader(
        target_x=rcvd_header.source_x, target_y=rcvd_header.source_y,
        source_x=jamlet.x, source_y=jamlet.y,
        message_type=MessageType.WRITE_MEM_WORD_RETRY,
        send_type=SendType.SINGLE,
        length=1,
        tag=rcvd_header.tag,
        ident=rcvd_header.ident)
    await jamlet.send_packet([header])
