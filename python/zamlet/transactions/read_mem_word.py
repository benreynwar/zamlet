'''
Read Memory Word Transaction

Handles reading a word from another jamlet's cache. This is used by transactions
that need to read data from a different jamlet's memory space.

Messages:
    READ_MEM_WORD_REQ  - Request a word from another jamlet
    READ_MEM_WORD_RESP - Response with the word data
    READ_MEM_WORD_DROP - Request couldn't be handled, need to resend

Flow:
1. Requester sends READ_MEM_WORD_REQ to target jamlet
2. Target checks if cache line is available
3. If yes, sends READ_MEM_WORD_RESP with data
4. If no, either creates WaitingReadMemWord or sends DROP
5. Requester handles response or retries on DROP
'''
from typing import List, Any, TYPE_CHECKING
import logging

from zamlet import addresses
from zamlet.addresses import JSAddr
from zamlet.message import TaggedHeader, MessageType, SendType, IdentHeader
from zamlet.waiting_item import WaitingItemRequiresCache
from zamlet.transactions import register_handler

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


class WaitingReadMemWord(WaitingItemRequiresCache):
    '''
    Waiting item for a ReadMemWord request where the cache line isn't ready yet.
    '''

    cache_is_read = True
    use_source_to_match = True

    def __init__(self, header: IdentHeader, cache_slot: int, j_saddr: addresses.JSAddr):
        super().__init__(item=header, instr_ident=header.ident, cache_slot=cache_slot,
                         source=(header.source_x, header.source_y))
        self.j_saddr = j_saddr

    def ready(self):
        return self.cache_is_avail

    async def finalize(self, kamlet) -> None:
        '''Called when cache is ready - send the response.'''
        jamlet = kamlet.jamlets[self.j_saddr.j_in_k_index]
        await send_resp(jamlet, self.item, self.j_saddr)


@register_handler(MessageType.READ_MEM_WORD_REQ)
async def handle_req(jamlet: 'Jamlet', packet: List[Any]) -> None:
    '''
    Handle a READ_MEM_WORD_REQ packet. Check if we can read from cache,
    and either send response immediately or create a waiting item.

    We must also check that the parent instruction has been processed on this
    jamlet before responding, otherwise we might read stale data from the cache
    before writes have completed.
    '''
    header = packet[0]
    assert isinstance(header, TaggedHeader)
    addr = packet[1]
    assert isinstance(addr, addresses.KMAddr)
    assert header.message_type == MessageType.READ_MEM_WORD_REQ

    # Check if the parent instruction exists on this jamlet - if not, the data
    # may not have been written yet, so we need to drop and retry later
    # The ident encodes: instr_ident + tag + 1, so subtract to get parent ident
    parent_ident = (header.ident - header.tag - 1) % jamlet.params.max_response_tags
    parent_witem = jamlet.cache_table.get_waiting_item_by_instr_ident(parent_ident)
    if parent_witem is None:
        await send_drop(jamlet, header, 'parent_not_ready')
        return

    can_read = jamlet.cache_table.can_read(addr)
    if can_read:
        j_saddr = addr.to_j_saddr(jamlet.cache_table)
        await send_resp(jamlet, header, j_saddr)
        return

    if not jamlet.cache_table.has_free_witem_slot(use_reserved=True):
        await send_drop(jamlet, header, 'witem_table_full')
        return

    if not jamlet.cache_table.can_get_slot(addr):
        await send_drop(jamlet, header, 'cache_slot_unavailable')
        return

    cache_slot = jamlet.cache_table.get_slot_if_exists(addr)
    assert cache_slot is not None
    j_saddr = addr.to_j_saddr(jamlet.cache_table)
    witem = WaitingReadMemWord(header, cache_slot, j_saddr)
    jamlet.cache_table.add_witem_immediately(witem, use_reserved=True)
    # Track witem span - parent is the transaction
    transaction_span_id = jamlet.monitor.get_transaction_span_id(
        header.ident, header.tag, header.source_x, header.source_y, jamlet.x, jamlet.y)
    jamlet.monitor.record_witem_created(
        instr_ident=header.ident,
        kamlet_x=jamlet.cache_table.kamlet_x,
        kamlet_y=jamlet.cache_table.kamlet_y,
        witem_type='WaitingReadMemWord',
        finalize=False,
        parent_span_id=transaction_span_id,
        source_x=header.source_x,
        source_y=header.source_y,
    )


@register_handler(MessageType.READ_MEM_WORD_RESP)
def handle_resp(jamlet: 'Jamlet', packet: List[Any]) -> None:
    '''
    Handle a READ_MEM_WORD_RESP packet. Find the waiting item by ident
    and process the response.
    '''
    header = packet[0]
    if header.ident_is_direct:
        instr_ident = header.ident
    else:
        # Decode parent ident from encoded ident
        instr_ident = (header.ident - header.tag - 1) % jamlet.params.max_response_tags
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(instr_ident)
    witem.process_response(jamlet, packet)


@register_handler(MessageType.READ_MEM_WORD_DROP)
def handle_drop(jamlet: 'Jamlet', packet: List[Any]) -> None:
    '''
    Handle a READ_MEM_WORD_DROP packet. Find the waiting item and mark
    for retry.
    '''
    header = packet[0]
    parent_ident = (header.ident - header.tag - 1) % jamlet.params.max_response_tags
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(parent_ident)
    witem.process_drop(jamlet, packet)


async def send_resp(jamlet: 'Jamlet', rcvd_header: TaggedHeader, j_saddr: JSAddr) -> None:
    '''Send READ_MEM_WORD_RESP with word data from cache.'''
    assert j_saddr.k_index == jamlet.k_index
    assert j_saddr.j_in_k_index == jamlet.j_in_k_index
    sram_addr = j_saddr.addr // jamlet.params.word_bytes * jamlet.params.word_bytes
    data = jamlet.sram[sram_addr: sram_addr + jamlet.params.word_bytes]
    header = TaggedHeader(
        target_x=rcvd_header.source_x, target_y=rcvd_header.source_y,
        source_x=jamlet.x, source_y=jamlet.y,
        message_type=MessageType.READ_MEM_WORD_RESP,
        send_type=SendType.SINGLE,
        length=2,
        tag=rcvd_header.tag,
        ident=rcvd_header.ident)
    assert len(data) == jamlet.params.word_bytes
    # Look up transaction (requester is source, we are dest)
    transaction_span_id = jamlet.monitor.get_transaction_span_id(
        rcvd_header.ident, rcvd_header.tag,
        rcvd_header.source_x, rcvd_header.source_y, jamlet.x, jamlet.y)
    assert transaction_span_id is not None
    # Record the data being read from SRAM
    jamlet.monitor.add_event(
        transaction_span_id,
        f'sram_read sram_addr={sram_addr}, data={data.hex()}')
    await jamlet.send_packet([header, data], parent_span_id=transaction_span_id)


async def send_drop(jamlet: 'Jamlet', rcvd_header: TaggedHeader,
                    reason: str) -> None:
    '''Send READ_MEM_WORD_DROP indicating request couldn't be handled.'''
    header = TaggedHeader(
        target_x=rcvd_header.source_x, target_y=rcvd_header.source_y,
        source_x=jamlet.x, source_y=jamlet.y,
        message_type=MessageType.READ_MEM_WORD_DROP,
        send_type=SendType.SINGLE,
        length=1,
        tag=rcvd_header.tag,
        ident=rcvd_header.ident)
    # Look up transaction (requester is source, we are dest)
    transaction_span_id = jamlet.monitor.get_transaction_span_id(
        rcvd_header.ident, rcvd_header.tag,
        rcvd_header.source_x, rcvd_header.source_y, jamlet.x, jamlet.y)
    assert transaction_span_id is not None
    await jamlet.send_packet([header], parent_span_id=transaction_span_id,
                             drop_reason=reason)
