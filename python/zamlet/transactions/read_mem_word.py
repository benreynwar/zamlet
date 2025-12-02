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

    def __init__(self, header: IdentHeader, cache_slot: int, j_saddr: addresses.JSAddr):
        super().__init__(item=header, instr_ident=header.ident, cache_slot=cache_slot)
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
    '''
    header = packet[0]
    assert isinstance(header, TaggedHeader)
    addr = packet[1]
    assert isinstance(addr, addresses.KMAddr)
    assert header.message_type == MessageType.READ_MEM_WORD_REQ

    if jamlet.cache_table.can_read(addr):
        j_saddr = addr.to_j_saddr(jamlet.cache_table)
        await send_resp(jamlet, header, j_saddr)
    else:
        if (jamlet.cache_table.can_get_free_witem_index() and
                jamlet.cache_table.can_get_slot(addr)):
            cache_slot = jamlet.cache_table.get_slot_if_exists(addr)
            assert cache_slot is not None
            j_saddr = addr.to_j_saddr(jamlet.cache_table)
            witem = WaitingReadMemWord(header, cache_slot, j_saddr)
            jamlet.cache_table.add_witem_immediately(witem)
        else:
            await send_drop(jamlet, header)


@register_handler(MessageType.READ_MEM_WORD_RESP)
async def handle_resp(jamlet: 'Jamlet', packet: List[Any]) -> None:
    '''
    Handle a READ_MEM_WORD_RESP packet. Find the waiting item by ident
    and process the response.
    '''
    header = packet[0]
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    witem.process_response(packet)


@register_handler(MessageType.READ_MEM_WORD_DROP)
async def handle_drop(jamlet: 'Jamlet', packet: List[Any]) -> None:
    '''
    Handle a READ_MEM_WORD_DROP packet. Find the waiting item and mark
    for retry.
    '''
    header = packet[0]
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    witem.process_drop(packet)


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
    await jamlet.send_packet([header, data])


async def send_drop(jamlet: 'Jamlet', rcvd_header: TaggedHeader) -> None:
    '''Send READ_MEM_WORD_DROP indicating request couldn't be handled.'''
    header = TaggedHeader(
        target_x=rcvd_header.source_x, target_y=rcvd_header.source_y,
        source_x=jamlet.x, source_y=jamlet.y,
        message_type=MessageType.READ_MEM_WORD_DROP,
        send_type=SendType.SINGLE,
        length=1,
        tag=rcvd_header.tag,
        ident=rcvd_header.ident)
    await jamlet.send_packet([header])
