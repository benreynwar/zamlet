import logging
from dataclasses import dataclass
from enum import Enum
from collections import deque
import random
from typing import Coroutine, List, Any

from zamlet.runner import Clock, Future
from zamlet.params import LamletParams
from zamlet.utils import SettableBool
from zamlet.message import Header, IdentHeader
from zamlet.kamlet import kinstructions
from zamlet import addresses
from zamlet.addresses import KMAddr


logger = logging.getLogger(__name__)


class CacheRequestType(Enum):
    WRITE_LINE = "WRITE_LINE"
    READ_LINE = "READ_LINE"
    WRITE_LINE_READ_LINE = "WRITE_LINE_READ_LINE"


@dataclass
class CacheRequestState:
    # Whether we have received the response for each jamlet.
    ident: int
    slot: int
    addr: int
    sent: List[SettableBool]
    received: List[SettableBool]
    request_type: CacheRequestType

    def update(self):
        for x in self.received:
            x.update()
        for x in self.sent:
            x.update()


class StoreSrcState(Enum):
    NEED_TO_SEND = 'NEED_TO_SEND'
    WAITING_FOR_RESPONSE = 'WAITING_FOR_RESPONSE'
    COMPLETE = 'COMPLETE'


class StoreDstState(Enum):
    WAITING_FOR_REQUEST = 'WAITING_FOR_REQUEST'
    NEED_TO_ASK_FOR_RESEND = 'NEED_TO_ASK_FOR_RESEND'
    COMPLETE = 'COMPLETE'


@dataclass
class ProtocolState:
    pass

    def finished(self) -> bool:
        raise NotImplementedError()


@dataclass
class StoreProtocolState(ProtocolState):
    """
    Each store instruction requires that for each jamlet and each tag:
      - src: The src sends a request to store (with the data)
                message = LOAD_J2J_WORDS
              when it sends this it sets the src state is WAITING_FOR_RESPONSE
      - dst: If the dst can't process it, it response with
             message = LOAD_J2J_WORDS_DROP
             it doesn't have a state for this yet, that's way it dropped it so it
             can't update the state.
      - dst: If it has a state, but doesn't have the cache line ready then it goes
             to the NEED_TO_ASK_FOR_RESENT state, but it doesn't send a message yet.
             When the cache line is ready it sends a LOAD_J2J_WORDS_RETRY message
             and sets it's state to WAITING_FOR_REQUEST
      - dst: If the the cache line is ready when it gets a LOAD_J2J_WORDS message then
             it sets the state to COMPLETE and writes to the cache line.
             It sends a LOAD_J2J_WORD_RESP message
      - src: If the src receives a LOAD_J2J_WORDS_DROP message then it sets it's state 
             back to NEED_TO_SEND
      - src: If the src receives a LOAD_J2J_WORDS_RETRY message then it also sets the 
             state back to NEED_TO_SEND
      - src: If it receives a LOAD_J2J_WORDS_RESP message then it sets it's state to
             complete.

    Once the state is COMPLETE for src and dst for all tags then the store is complete.
    """
    src_state: StoreSrcState = StoreSrcState.NEED_TO_SEND
    dst_state: StoreDstState = StoreDstState.WAITING_FOR_REQUEST

    def finished(self) -> bool:
        return self.src_state == StoreSrcState.COMPLETE and self.dst_state == StoreDstState.COMPLETE


class LoadSrcState(Enum):
    NEED_TO_SEND = 'NEED_TO_SEND'
    WAITING_FOR_RESPONSE = 'WAITING_FOR_RESPONSE'
    COMPLETE = 'COMPLETE'


class LoadDstState(Enum):
    WAITING_FOR_REQUEST = 'WAITING_FOR_REQUEST'
    NEED_TO_ASK_FOR_RESEND = 'NEED_TO_ASK_FOR_RESEND'
    COMPLETE = 'COMPLETE'


@dataclass
class LoadProtocolState(ProtocolState):
    src_state: LoadSrcState = LoadSrcState.NEED_TO_SEND
    dst_state: LoadDstState = LoadDstState.WAITING_FOR_REQUEST

    def finished(self) -> bool:
        return self.src_state == LoadSrcState.COMPLETE and self.dst_state == LoadDstState.COMPLETE




class WaitingItem:

    cache_is_write = False
    cache_is_read = False

    def __init__(self, item: Any, instr_ident: int|None=None, rf_ident: int|None=None):
        self.item = item
        self.instr_ident = instr_ident
        self.rf_ident = rf_ident
        self.cache_slot: int|None = None

    def ready(self):
        raise NotImplementedError()


class WaitingItemRequiresCache(WaitingItem):

    def __init__(self, item: Any, instr_ident: int|None=None,
                 cache_slot: int|None=None, cache_is_avail: bool=False,
                 writeset_ident: int|None=None, rf_ident: int|None=None):
        super().__init__(item, instr_ident, rf_ident)
        self.cache_slot = cache_slot
        self.cache_is_avail = cache_is_avail
        self.writeset_ident = writeset_ident
        assert self.cache_is_write or self.cache_is_read
        assert not (self.cache_is_write and self.cache_is_read)

    def set_cache_slot(self, slot):
        assert not self.cache_is_avail
        assert self.cache_slot is None
        self.cache_slot = slot

    def ready(self):
        return self.cache_is_avail


class WaitingWriteImmBytes(WaitingItemRequiresCache):

    cache_is_write = True

    def __init__(self, instr: kinstructions.WriteImmBytes):
        super().__init__(item=instr)


class WaitingReadByte(WaitingItemRequiresCache):

    cache_is_read = True

    def __init__(self, instr: kinstructions.ReadByte):
        super().__init__(item=instr)


class WaitingStoreSimple(WaitingItemRequiresCache):

    cache_is_write = True

    def __init__(self, instr: kinstructions.Store, rf_ident: int|None=None):
        super().__init__(
                item=instr, writeset_ident=instr.writeset_ident, rf_ident=rf_ident)


class WaitingLoadSimple(WaitingItemRequiresCache):

    cache_is_read = True

    def __init__(self, instr: kinstructions.Load, rf_ident: int|None=None):
        super().__init__(
                item=instr, writeset_ident=instr.writeset_ident, rf_ident=rf_ident)


class WaitingLoadWordSrc(WaitingItemRequiresCache):

    cache_is_read = True

    def __init__(self, params: LamletParams, instr: kinstructions.LoadWord):
        super().__init__(
                item=instr, instr_ident=instr.instr_ident, writeset_ident=instr.writeset_ident, rf_ident=None)
        self.protocol_states = [LoadSrcState.COMPLETE for _ in range(params.j_in_k)]

    def ready(self):
        return all(state == LoadSrcState.COMPLETE for state in self.protocol_states) and self.cache_is_avail


class WaitingLoadWordDst(WaitingItem):

    def __init__(self, params: LamletParams, instr: kinstructions.LoadWord, rf_ident: int):
        super().__init__(item=instr, rf_ident=rf_ident)
        self.protocol_states = [LoadDstState.COMPLETE for _ in range(params.j_in_k)]
        self.instr_ident = instr.instr_ident + 1
        self.writeset_ident = instr.writeset_ident

    def ready(self):
        return all(state == LoadDstState.COMPLETE for state in self.protocol_states)


class WaitingStoreWordSrc(WaitingItem):

    def __init__(self, params: LamletParams, instr: kinstructions.StoreWord, rf_ident: int):
        super().__init__(item=instr, rf_ident=rf_ident)
        self.protocol_states = [StoreSrcState.COMPLETE for _ in range(params.j_in_k)]
        self.instr_ident = instr.instr_ident
        self.writeset_ident = instr.writeset_ident

    def ready(self):
        return all(state == StoreSrcState.COMPLETE for state in self.protocol_states)


class WaitingStoreWordDst(WaitingItemRequiresCache):

    cache_is_write = True

    def __init__(self, params: LamletParams, instr: kinstructions.StoreWord):
        super().__init__(
                item=instr, instr_ident=instr.instr_ident + 1,
                writeset_ident=instr.writeset_ident, rf_ident=None)
        self.protocol_states = [StoreDstState.COMPLETE for _ in range(params.j_in_k)]

    def ready(self):
        return all(state == StoreDstState.COMPLETE for state in self.protocol_states) and self.cache_is_avail


class WaitingFuture(WaitingItem):
    
    def __init__(self, future: Future):
        """
        This is used in the lamlet
        When a response is received with header.ident == item_index (in the list waiting_items list)
        then the future is fired.
        """
        super().__init__(item=future)


class WaitingStoreJ2JWords(WaitingItemRequiresCache):

    cache_is_write = True

    def __init__(self, params: LamletParams, instr: kinstructions.Store, rf_ident: int|None=None):
        super().__init__(item=instr, instr_ident=instr.instr_ident, writeset_ident=instr.writeset_ident, rf_ident=rf_ident)
        n_tags = instr.n_tags(params) * params.j_in_k
        self.protocol_states: List[StoreProtocolState] = [
                StoreProtocolState() for _ in range(n_tags)]

    def ready(self):
        return all(state.finished() for state in self.protocol_states) and self.cache_is_avail


class WaitingLoadJ2JWords(WaitingItemRequiresCache):

    cache_is_read = True

    def __init__(self, params: LamletParams, instr: kinstructions.Load, rf_ident: int|None=None):
        super().__init__(item=instr, instr_ident=instr.instr_ident, writeset_ident=instr.writeset_ident, rf_ident=rf_ident)
        n_tags = instr.n_tags(params) * params.j_in_k
        self.protocol_states: List[LoadProtocolState] = [
                LoadProtocolState() for _ in range(n_tags)]

    def ready(self):
        return all(state.finished() for state in self.protocol_states) and self.cache_is_avail

#@dataclass
#class WaitingItem:
#    """
#    Represents something that must be done in the future once some preconditions are
#    met.  This could be cache becoming available or responses being received.
#    If the hardware we'll have a small buffer to keep these in.
#
#    It's ok if there are multiple WaitingItem with 'cache_is_read' for the same
#    cache slot, but we can't have some with 'cache_is_read' and some with
#    'cache_is_write'. We can have one item with 'cache_is_write' or several with
#    'cache_is_read'.
#
#    When creating a waiting item the cache_slot must be allocated at the same time.
#    """
#    witem_type: WItemType
#    protocol_states: List[ProtocolState]
#    item: Any   # LoadRequest or KInstr
#    cache_is_read: bool = False
#    cache_is_write: bool = False
#    cache_is_avail: bool = False
#    cache_slot: int|None = None
#    # This is used when two kamlets are communicating with one another to know
#    # that this is the same instruction.
#    # TODO: We should be able to work out a way to use this as the item_index so
#    # we don't have to match on it.
#    instr_ident: int|None = None
#    # A debug index to check that the same object is requesting a RF write and then
#    # releasing it.
#    rf_ident: int|None = None
#    # We can have multiple cache writes to the same slot if they all have the same
#    # writeset_ident. These are guaranteed to access different parts of the cache line.
#    # TODO: Currently  this is not used.
#    writeset_ident: int|None = None


class CacheLineState:

    def __init__(self):
        '''
        Keeps track of the state of the cache lines and what location in
        memory they represent.
        '''
        self.state = CacheState.UNALLOCATED
        # The memory address divided by the cache line size
        self.memory_loc = None
        # The memory address of something that we're in the process of evicting
        self.old_memory_loc = None


class CacheState(Enum):
    INVALID = 0        # Unitialized data
    SHARED = 1         # Data matches the memory
    MODIFIED = 2       # Has updated data compared to the memory
    READING = 3        # In middle of reading data from the memory
    WRITING = 4        # In middle of writing data to the memory
    WRITING_READING = 5  # In middle of writing data to the memory and reading new data
    UNALLOCATED = 6    # Not allocated to any address.
    OLD_MODIFIED = 10  # Has updated data compared to the memory (for old location)


class CacheTable:

    def __init__(self, clock: Clock, params: LamletParams, name=''):
        self.clock = clock
        self.params = params
        self.n_slots = params.jamlet_sram_bytes * params.j_in_k // params.cache_line_bytes
        assert (params.jamlet_sram_bytes * params.j_in_k) % params.cache_line_bytes == 0
        assert self.n_slots >= 4
        self.cache_line_bytes = params.cache_line_bytes
        # For now assume that we're using all of the SRAM for global cache.
        self.slot_states = [CacheLineState() for index in range(self.n_slots)]
        self.free_slots = deque(list(range(self.n_slots)))
        self.used_slots: List[int] = []
        self._check_slots()
        self.next_read_id = 0
        self.name = name

        # These are actions that are waiting on a cache state to update, or for messages to be received.
        self.waiting_items: List[WaitingItem|None] = [None for _ in range(params.n_items)]

        # This is a list of outstanding cache read_line or write_line requests.
        self.cache_requests: List[CacheRequestState|None] = [None] * params.n_cache_requests

        self.acquiring_slot = False

    def receive_cache_response(self, header: IdentHeader) -> None:
        """
        Jamlet's pass us the headers of any WRITE_LINE_RESP or READ_LINE_RESP packets that they
        receive.
        """
        ident = header.ident
        tag = ((header.target_y % self.params.j_rows) * self.params.j_cols +
               (header.target_x % self.params.j_cols))
        state = self.cache_requests[ident]
        assert state is not None
        assert state.ident == ident
        assert not state.received[tag]
        state.received[tag].set(True)
        logger.debug(
            f'{self.clock.cycle}: {self.name}: receive_cache_response '
            f'req={ident} tag={tag} slot={state.slot} '
            f'received={sum(1 for r in state.received if r)}/{len(state.received)}'
        )

    def can_get_free_witem_index(self) -> bool:
        return self.get_free_witem_index_if_exists() is not None

    def get_free_witem_index_if_exists(self) -> int|None:
        valid_indices = [index for index, x in enumerate(self.waiting_items) if x is None]
        if valid_indices:
            return valid_indices[0]
        else:
            return None

    async def get_free_witem_index(self) -> int:
        while True:
            free_item = self.get_free_witem_index_if_exists()
            if free_item is not None:
                break
            await self.clock.next_cycle
        return free_item

    def can_get_free_cache_request(self) -> bool:
        valid_indices = [index for index, x in enumerate(self.cache_requests) if x is None]
        return len(valid_indices) > 0

    def get_cache_request_if_exists(self, slot):
        valid_indices = [index for index, x in enumerate(self.cache_requests) if x is not None and x.slot == slot]
        assert len(valid_indices) in (0, 1)
        if valid_indices:
            return valid_indices[0]
        else:
            return None

    async def get_free_cache_request(self):
        logger.debug('get_free_cache_request: start')
        while True:
            valid_indices = [index for index, x in enumerate(self.cache_requests) if x is None]
            if valid_indices:
                break
            await self.clock.next_cycle
        logger.debug('get_free_cache_request: end')
        return valid_indices[0]

    async def wait_for_slot_to_be_writeable(self, slot: int, k_maddr: KMAddr) -> None:
        while True:
            assert slot == self.addr_to_slot(k_maddr)
            if not self.slot_in_use(slot):
                break
            await self.clock.next_cycle
        state = self.get_state(k_maddr)
        assert state.state in (CacheState.SHARED, CacheState.MODIFIED)

    async def wait_for_slot_to_be_readable(self, slot: int, k_maddr: KMAddr) -> None:
        while True:
            assert slot == self.addr_to_slot(k_maddr)
            if not self.slot_has_write(slot):
                break
            await self.clock.next_cycle
        state = self.get_state(k_maddr)
        assert state.state in (CacheState.SHARED, CacheState.MODIFIED)

    async def add_witem(self, witem: WaitingItem, k_maddr: KMAddr|None=None):
        if isinstance(witem, WaitingItemRequiresCache):
            assert k_maddr is not None
            assert not (witem.cache_is_read and witem.cache_is_write)
            assert witem.cache_is_read or witem.cache_is_write
            slot = self.addr_to_slot(k_maddr)
            if slot is None:
                logger.debug(
                    f'{self.clock.cycle}: {self.name}: cache miss for '
                    f'addr={hex(k_maddr.addr)}, getting new slot'
                )
                slot = await self._get_new_slot(k_maddr)
                witem.set_cache_slot(slot)
                logger.debug(
                    f'{self.clock.cycle}: {self.name}: got new slot={slot} '
                    f'cache_is_avail={witem.cache_is_avail} state={self.slot_states[slot].state}'
                )
            else:
                logger.debug(
                    f'{self.clock.cycle}: {self.name}: cache hit for '
                    f'addr={hex(k_maddr.addr)}, slot={slot}'
                )
                witem.set_cache_slot(slot)
                if witem.cache_is_write:
                    if self.slot_in_use(slot):
                        # If there are other witems in the midst of a read or write we need
                        # to wait for them to complete
                        await self.wait_for_slot_to_be_writeable(slot, k_maddr)
                if witem.cache_is_read:
                    if self.slot_has_write(slot):
                        await self.wait_for_slot_to_be_readable(slot, k_maddr)
                witem.cache_is_avail = (
                        self.slot_states[slot].state in (CacheState.SHARED, CacheState.MODIFIED))
                logger.debug(
                    f'{self.clock.cycle}: {self.name}: slot state={self.slot_states[slot].state}, '
                    f'cache_is_avail={witem.cache_is_avail}'
                )
        witem_index = await self.get_free_witem_index()
        self.waiting_items[witem_index] = witem
        return witem_index

    async def update_cache(self, slot):
        slot_state = self.slot_states[slot]
        # We want to read an address.
        # We might be given a slot that is ready to go.
        # We might be given slot and told we need to evict the current contents.
        # We might be given a slot and told we need to read in the contents.

        cache_request_index = await self.get_free_cache_request()
        # There is not slot for this memory address. We need to get a slot.
        if slot_state.state == CacheState.INVALID:
            request_type=CacheRequestType.READ_LINE
            n_sent = 1
            request_addr = slot_state.memory_loc * self.params.cache_line_bytes
        elif slot_state.state == CacheState.OLD_MODIFIED:
            request_type=CacheRequestType.WRITE_LINE_READ_LINE
            n_sent = self.params.j_in_k
            # For WRITE_LINE_READ_LINE, addr is the OLD address to flush
            request_addr = slot_state.old_memory_loc * self.params.cache_line_bytes
        else:
            assert False
        assert self.cache_requests[cache_request_index] is None
        cache_request = CacheRequestState(
                ident=cache_request_index,
                addr=request_addr,
                slot=slot,
                sent=[SettableBool(False) for x in range(n_sent)],
                received=[SettableBool(False) for x in range(self.params.j_in_k)],
                request_type=request_type,
                )
        self.cache_requests[cache_request_index] = cache_request

        # Update the slot state immediately to prevent duplicate cache requests
        if request_type == CacheRequestType.READ_LINE:
            slot_state.state = CacheState.READING
        elif request_type == CacheRequestType.WRITE_LINE_READ_LINE:
            slot_state.state = CacheState.WRITING_READING

    #async def request_read(self, k_maddr, item, step):
    #    """
    #    The item with handled with the argument 'step' once the cache read is done.
    #    """
    #    logger.debug(f'{self.clock.cycle}: {self.name}: Requesting a read for {hex(k_maddr.addr)}')
    #    # We want to read an address.
    #    # We might be given a slot that is ready to go.
    #    # We might be given slot and told we need to evict the current contents.
    #    # We might be given a slot and told we need to read in the contents.
    #    slot = self.addr_to_slot(k_maddr)
    #    if slot is None:
    #        cache_request_index = await self.get_free_cache_request()
    #        # There is not slot for this memory address. We need to get a slot.
    #        slot = await self._get_new_slot(k_maddr)
    #        slot_state = self.slot_states[slot]
    #        if slot_state.state == CacheState.INVALID:
    #            request_type=CacheRequestType.READ_LINE
    #            n_sent = 1
    #        elif slot_state.state == CacheState.OLD_MODIFIED:
    #            request_type=CacheRequestType.WRITE_LINE_READ_LINE
    #            n_sent = self.params.j_in_k
    #        else:
    #            assert False
    #        assert self.cache_requests[cache_request_index] is None
    #        cache_request = CacheRequestState(
    #                ident=cache_request_index,
    #                addr=k_maddr.addr,
    #                slot=slot,
    #                sent=[SettableBool(False) for x in range(n_sent)],
    #                received=[SettableBool(False) for x in range(self.params.j_in_k)],
    #                request_type=request_type,
    #                )
    #        self.cache_requests[cache_request_index] = cache_request
    #    else:
    #        # We have a slot but it might be in the process of loading in.
    #        slot_state = self.slot_states[slot]
    #        assert slot_state.state in (CacheState.READING, CacheState.WRITING, CacheState.WRITING_READING)
    #        # If it was shared or modified we can use it immediately and this
    #        # function shouldn't have been called.
    #        cache_request_index = self.get_cache_request(slot)
    #        # Mark the slot as recently used
    #        self.used_slots.remove(slot)
    #        self.used_slots.append(slot)
    #    await self.add_item(item, [], cache_is_write=False, cache_slot=slot, step=step)

    #async def _prepare_cache(self, slot, cache_request_index):
    #    slot_state = self.slot_states[slot]
    #    if slot_state.state == CacheState.OLD_MODIFIED:
    #        cache_request = CacheRequest(
    #                ident=cache_request_index,
    #                slot=slot,
    #                sent=[SettableBool(false) for x in range(self.params.j_in_k)],
    #                received=[SettableBool(false) for x in range(self.params.j_in_k)],
    #                request_type=CacheRequestType.WRITE_LINE_READ_LINE,
    #                )
    #    elif slot_state.state == CacheState.INVALID:
    #        cache_request = CacheRequest(
    #                ident=cache_request_index,
    #                slot=slot,
    #                sent=[SettableBool(false) for x in range(self.params.j_in_k)],
    #                received=[SettableBool(false) for x in range(self.params.j_in_k)],
    #                request_type=CacheRequestType.READ_LINE,
    #                )

    #    assert slot_state.state in (CacheState.INVALID, CacheState.SHARED,
    #                                CacheState.MODIFIED, CacheState.READING, CacheState.WRITING,
    #                                CacheState.OLD_WRITING, # A previous access request caused a cache line to flush.
    #                                )
    #    if slot_state.state == CacheState.INVALID:
    #        read_task = self.read_slot(slot)
    #        await read_task
    #    assert slot_state.state in (CacheState.SHARED, CacheState.MODIFIED, CacheState.READING, CacheState.WRITING, CacheState.OLD_WRITING)
    #    while slot_state.state in (CacheState.READING, CacheState.WRITING, CacheState.OLD_WRITING):
    #        await self.clock.next_cycle
    #    assert slot_state.state in (CacheState.SHARED, CacheState.MODIFIED)
        
    #async def _request_read_resolve(self, slot, coro):
    #    await self._prepare_cache(slot)
    #    # Now we just need to wait for our turn in the batch queue to come up.
    #    slot_state = self.slot_states[slot]
    #    while True:
    #        this_batch = slot_state.batch_queue[0]
    #        if isinstance(this_batch, WriteBatch):
    #            if this_batch.coro == coro:
    #                assert False
    #        elif isinstance(this_batch, ReadBatch):
    #            if coro in this_batch.coros:
    #                task = self.clock.create_task(coro)
    #                break
    #        else:
    #            assert False
    #        await self.clock.next_cycle
    #    await task
    #    assert this_batch == slot_state.batch_queue[0]
    #    this_batch.coros.remove(coro)
    #    if not this_batch.coros:
    #        slot_state.batch_queue.pop(0)
                
    #async def request_write(self, k_maddr, item, step):
    #    """
    #    The coroutine will be run once k_maddr is available to write in the cache.
    #    """
    #    logger.debug(f'{self.clock.cycle}: {self.name}: Requesting a write for {hex(k_maddr.addr)}')

    #    logger.warning('adding item')
    #    logger.warning('added item')

    #    slot = self.addr_to_slot(k_maddr)
    #    if slot is None:
    #        cache_request_index = await self.get_free_cache_request()
    #        # There is not slot for this memory address. We need to get a slot.
    #        slot = await self._get_new_slot(k_maddr)
    #        await self.add_item(item, [], cache_is_write=True, cache_slot=slot, step=step)
    #        slot_state = self.slot_states[slot]
    #        if slot_state.state == CacheState.INVALID:
    #            request_type=CacheRequestType.READ_LINE
    #            n_send = 1
    #        elif slot_state.state == CacheState.OLD_MODIFIED:
    #            request_type=CacheRequestType.WRITE_LINE_READ_LINE
    #            n_send = self.params.j_in_k
    #        else:
    #            assert False
    #        assert self.cache_requests[cache_request_index] is None
    #        cache_request = CacheRequestState(
    #                ident=cache_request_index,
    #                slot=slot,
    #                addr=k_maddr.addr,
    #                sent=[SettableBool(False) for x in range(n_send)],
    #                received=[SettableBool(False) for x in range(self.params.j_in_k)],
    #                request_type=request_type,
    #                )
    #        self.cache_requests[cache_request_index] = cache_request
    #    else:
    #        await self.add_item(item, [], cache_is_write=True, cache_slot=slot, step=step)
    #        # We have a slot but it might be in the process of loading in.
    #        slot_state = self.slot_states[slot]
    #        assert slot_state.state in (CacheState.READING, CacheState.WRITING, CacheState.WRITING_READING)
    #        # If it was shared or modified we can use it immediately and this
    #        # function shouldn't have been called.
    #        cache_request_index = self.get_cache_request(slot)
    #        # Mark the slot as recently used
    #        self.used_slots.remove(slot)
    #        self.used_slots.append(slot)
    #    return cache_request_index

    #async def _request_write_resolve(self, slot, coro, k_maddr):
    #    logger.debug(f'{self.clock.cycle}: {self.name}: started _request_write_resolve {hex(k_maddr.addr)}')
    #    await self._prepare_cache(slot)
    #    # Now we just need to wait for our turn in the batch queue to come up.
    #    slot_state = self.slot_states[slot]
    #    while True:
    #        this_batch = slot_state.batch_queue[0]
    #        if isinstance(this_batch, WriteBatch):
    #            if this_batch.coro == coro:
    #                task = self.clock.create_task(coro)
    #                break
    #        elif isinstance(this_batch, ReadBatch):
    #            if coro in this_batch.coros:
    #                assert False
    #        else:
    #            assert False
    #        await self.clock.next_cycle
    #    await task
    #    assert slot_state.state in (CacheState.SHARED, CacheState.MODIFIED)
    #    slot_state.state = CacheState.MODIFIED
    #    assert this_batch == slot_state.batch_queue[0]
    #    slot_state.batch_queue.pop(0)

    def _check_slots(self):
        assert len(self.free_slots) + len(self.used_slots) == self.n_slots
        assert len(set(self.free_slots)) == len(self.free_slots)
        assert len(set(self.used_slots)) == len(self.used_slots)

    def get_state(self, k_maddr):
        slot = self.addr_to_slot(k_maddr)
        return self.slot_states[slot]

    def can_read(self, k_maddr):
        slot = self.addr_to_slot(k_maddr)
        if slot is None:
            return False
        else:
            state = self.get_state(k_maddr)
            good_state = state.state in (CacheState.SHARED, CacheState.MODIFIED)
            has_write = self.slot_has_write(slot)
            return good_state and not has_write

    def can_write(self, k_maddr, witem:WaitingItem|None=None):
        slot = self.addr_to_slot(k_maddr)
        if slot is None:
            return False
        else:
            state = self.get_state(k_maddr)
            good_state = state.state in (CacheState.SHARED, CacheState.MODIFIED)
            in_use = self.slot_in_use(slot, witem=witem)
            return good_state and not in_use

    #def get_free_slot(self):
    #    """
    #    This returns a slot that is unallocated and available to be used.
    #    """
    #    self._check_slots()
    #    if self.free_slots:
    #        slot = self.free_slots.pop(0)
    #        self.used_slots.append(slot)
    #        slot_state = self.slot_states[slot]
    #        assert slot_state.state == CacheState.UNALLOCATED
    #        assert slot_state.memory_loc is None
    #    else:
    #        slot = None
    #    self._check_slots()
    #    return slot

    #def flush_slot(self, slot):
    #    """
    #    This flushes the cache line to memory.
    #    """
    #    state = self.slot_states[slot]
    #    assert state.state == CacheState.MODIFIED
    #    state.state = CacheState.WRITING
    #    task = self.clock.create_task(self._flush_slot_resolve(slot))
    #    return task

    #async def _flush_slot_resolve(self, slot):
    #    state = self.slot_states[slot]
    #    assert state.state == CacheState.WRITING
    #    task = await self.flush_method(slot, state.memory_loc*self.params.cache_line_bytes)
    #    await task
    #    state.state = CacheState.SHARED

    #def flush_slot_old(self, slot):
    #    state = self.slot_states[slot]
    #    assert state.state == CacheState.OLD_MODIFIED
    #    self.slot_states[slot].state = CacheState.OLD_WRITING
    #    task = self.clock.create_task(self._flush_slot_old_resolve(slot))
    #    return task

    #async def _flush_slot_old_resolve(self, slot):
    #    state = self.slot_states[slot]
    #    assert state.state == CacheState.OLD_WRITING
    #    task = await self.flush_method(slot, state.old_memory_loc*self.params.cache_line_bytes)
    #    await task
    #    state = self.slot_states[slot]
    #    state.state = CacheState.INVALID

    #def read_slot(self, slot):
    #    """
    #    This reads a cache line into the SRAM.
    #    It takes a future that should resolve when the data is written.
    #    It returns a future that resolves when the cache state has been updated.
    #    """
    #    assert self.slot_states[slot].state == CacheState.INVALID
    #    self.slot_states[slot].state = CacheState.READING
    #    task = self.clock.create_task(self._read_slot_resolve(slot))
    #    return task

    #async def _read_slot_resolve(self, slot):
    #    state = self.slot_states[slot]
    #    task = await self.read_method(slot, state.memory_loc*self.params.cache_line_bytes)
    #    await task
    #    assert state.state == CacheState.READING
    #    state.state = CacheState.SHARED

    def slot_has_write(self, slot):
        # Check to see if there are any waiting items using this slot.
        slot_in_use = False
        for item in self.waiting_items:
            if item is None:
                continue
            using_cache = item.cache_is_write
            if item.cache_slot == slot and using_cache:
                slot_in_use = True
        if slot_in_use:
            assert slot in self.used_slots
        return slot_in_use

    def slot_in_use(self, slot, witem=None):
        # Check to see if there are any waiting items using this slot.
        slot_in_use = False
        for other_witem_index, other_witem in enumerate(self.waiting_items):
            if other_witem is None or other_witem == witem:
                continue
            using_cache = other_witem.cache_is_read or other_witem.cache_is_write
            if using_cache and other_witem.cache_slot == slot:
                slot_in_use = True
                logger.debug(f'slot {slot} in use by witem {other_witem_index}')
        if slot_in_use:
            assert slot in self.used_slots
        return slot_in_use

    def get_waiting_item_by_instr_ident(self, instr_ident: int) -> WaitingItem|None:
        valid_indices = [index for index, item in enumerate(self.waiting_items)
                       if item is not None and item.instr_ident == instr_ident]
        if not valid_indices:
            return None
        assert len(valid_indices) == 1
        index = valid_indices[0]
        item = self.waiting_items[index]
        return item

    def _can_get_new_slot(self, k_maddr: KMAddr) -> bool:
        if self.free_slots:
            return True
        else:
            for check_slot in self.used_slots:
                # Check to see if there are any waiting items using this slot.
                slot_in_use = self.slot_in_use(check_slot)
                if not slot_in_use:
                    return True
        return False

    def _get_new_slot_if_exists(self, k_maddr: KMAddr, check: bool=True) -> int|None:
        assert self.addr_to_slot(k_maddr) is None
        self._check_slots()
        if check:
            assert not self.acquiring_slot
        slot = None
        if self.free_slots:
            slot = self.free_slots.popleft()
        else:
            for check_slot in self.used_slots:
                # Check to see if there are any waiting items using this slot.
                slot_in_use = self.slot_in_use(check_slot)
                if not slot_in_use:
                    slot = check_slot
                    self.used_slots.remove(slot)
                    break
        if slot is not None:
            self.used_slots.append(slot)
        self._check_slots()
        return slot


    async def _get_new_slot(self, k_maddr):
        """
        This returns a free slot if it can, otherwise it returns a slot to be evicted.
        """
        logger.info(f'[CACHE_ALLOC] Trying to get new slot for k_maddr=0x{k_maddr.addr:x}')
        assert self.addr_to_slot(k_maddr) is None
        self._check_slots()
        # Adding some assert statements to make sure we don't call one request_read
        # until the previous is finished.
        assert not self.acquiring_slot
        self.acquiring_slot = True
        slot = None
        while True:
            slot = self._get_new_slot_if_exists(k_maddr, check=False)
            if slot is not None:
                break
            await self.clock.next_cycle
        self.acquiring_slot = False

        slot_state = self.slot_states[slot]
        slot_state.old_memory_loc = slot_state.memory_loc
        slot_state.memory_loc = k_maddr.addr//self.cache_line_bytes

        logger.debug(
            f'{self.clock.cycle}: CACHE_LINE_ALLOC: {self.name} slot={slot} '
            f'memory_loc=0x{slot_state.memory_loc:x}'
        )

        old_state = slot_state.state
        if slot_state.state == CacheState.SHARED:
            slot_state.state = CacheState.INVALID
        elif slot_state.state == CacheState.MODIFIED:
            slot_state.state = CacheState.OLD_MODIFIED
        elif slot_state.state == CacheState.UNALLOCATED:
            slot_state.state = CacheState.INVALID
        elif slot_state.state == CacheState.INVALID:
            pass
        else:
            raise ValueError('Bad cache state')
        logger.debug('got a new slot')
        self._check_slots()
        return slot

    #def evict_slot(self, slot):
    #    """
    #    This evicts a slot.
    #    """
    #    assert self.slot_states[slot] in (CacheState.INVALID, CacheState.SHARED)
    #    assert slot in self.used_slots
    #    self.used_slots.remove(slot)
    #    self.slot_states[slot] = CacheLineState()
    #    self.slot_states[slot].state = CacheState.UNALLOCATED
    #    self.free_slots.append(slot)
    #    self._check_slots()

    #def assign_slot(self, slot, k_maddr):
    #    """
    #    This assigns a slot to a memory location.
    #    """
    #    memory_loc = k_maddr.addr // self.params.cache_line_bytes
    #    assert self.slot_states[slot].state == CacheState.UNALLOCATED
    #    assert slot in self.free_slots
    #    self.free_slots.remove(slot)
    #    self.used_slots.append(slot)
    #    self.slot_states[slot] = CacheLineState()
    #    self.slot_states[slot].memory_loc = memory_loc
    #    self.slot_states[slot].state = CacheState.INVALID

    def addr_to_slot(self, k_maddr):
        memory_loc = k_maddr.addr // self.params.cache_line_bytes
        matching_slots = []
        for slot, slot_state in enumerate(self.slot_states):
            if slot_state.memory_loc == memory_loc:
                matching_slots.append(slot)
        assert len(matching_slots) <= 1
        if matching_slots:
            return matching_slots[0]
        else:
            return None

    def report_sent_request(self, request: CacheRequestState, j_in_k_index: int):
        assert self.cache_requests[request.ident] == request
        # State transitions now happen in update_cache(), so just verify they're correct
        if request.request_type == CacheRequestType.READ_LINE:
            request.sent[0].set(True)
            assert self.slot_states[request.slot].state == CacheState.READING
        elif request.request_type == CacheRequestType.WRITE_LINE_READ_LINE:
            request.sent[j_in_k_index].set(True)
            assert self.slot_states[request.slot].state == CacheState.WRITING_READING
        else:
            raise NotImplementedError()

    def resolve_read_line(self, request: CacheRequestState):
        assert self.cache_requests[request.ident] == request
        self.cache_requests[request.ident] = None
        state = self.slot_states[request.slot]
        assert state.state == CacheState.READING
        state.state = CacheState.SHARED
        for witem in self.waiting_items:
            if (witem is not None and isinstance(witem, WaitingItemRequiresCache) and
                    witem.cache_slot == request.slot):
                assert not witem.cache_is_avail
                witem.cache_is_avail = True

    def resolve_write_line_read_line(self, request: CacheRequestState):
        assert self.cache_requests[request.ident] == request
        self.cache_requests[request.ident] = None
        state = self.slot_states[request.slot]
        assert state.state == CacheState.WRITING_READING
        state.state = CacheState.SHARED
        for item in self.waiting_items:
            if item is not None and item.cache_slot == request.slot:
                item.cache_is_avail = True

    #async def _monitor_cache_requests(self):
    #    """
    #    Check to see if any of the open cache requests have received all of their responses.
    #    """
    #    while True:
    #        await self.clock.next_cycle
    #        for request_id, request in enumerate(self.cache_requests):
    #            if request is None:
    #                continue
    #            if all(request.received):
    #                state = self.slot_states[request.slot]
    #                if request.request_type == CacheRequestType.READ_LINE:
    #                    self.cache_requests[request_id] = None
    #                    assert state.state == CacheState.READING
    #                    state.state = CacheState.SHARED
    #                    for item in self.waiting_items:
    #                        if item is not None and item.cache_slot == request.slot:
    #                            item.cache_is_avail = True
    #                elif request.request_type == CacheRequestType.WRITE_LINE:
    #                    if state.state == CacheState.WRITING:
    #                        self.cache_requests[request_id] = None
    #                        state.state = CacheState.SHARED
    #                        for item in self.waiting_items:
    #                            if item is not None and item.cache_slot == request.slot:
    #                                item.cache_is_avail = True
    #                    elif state.state == CacheState.OLD_WRITING:
    #                        state.state = CacheState.INVALID
    #                        self.cache_requests[request_id] = ??
    #                else:
    #                    raise NotImplementedError()

    #async def _monitor_invalid_cache(self):
    #    """
    #    Detect cache lines that are invalid but should have data.
    #    Probably we've flushed but haven't read yet.  Submit the read.
    #    """

    async def _monitor_items(self) -> None:
        """
        Creates cache requests for items that have cache slots that need updating.
        """
        while True:
            await self.clock.next_cycle
            for witem in self.waiting_items:
                if witem is None:
                    continue
                if isinstance(witem, WaitingItemRequiresCache):
                    slot = witem.cache_slot
                    if slot is not None:
                        assert witem.cache_is_write or witem.cache_is_read
                        slot_state = self.slot_states[slot]
                        if slot_state.state in (CacheState.INVALID, CacheState.OLD_MODIFIED):
                            logger.debug(
                                f'{self.clock.cycle}: {self.name}: _monitor_items found '
                                f'slot={slot} in state={slot_state.state}, calling update_cache'
                            )
                            # The cache needs updating.
                            await self.update_cache(slot)

    async def _monitor_cache_responses(self):
        """
        Check to see if any of the open cache requests have received all of their responses.
        """
        while True:
            await self.clock.next_cycle
            for request_index, request in enumerate(self.cache_requests):
                if request is None:
                    continue
                assert request.ident == request_index
                if all(request.received):
                    logger.debug(
                        f'{self.clock.cycle}: {self.name}: _monitor_cache_responses '
                        f'req={request_index} type={request.request_type} complete, resolving'
                    )
                    if request.request_type == CacheRequestType.READ_LINE:
                        self.resolve_read_line(request)
                    #elif request.request_type == CacheRequestType.WRITE_LINE:
                    #    self.cache_table.resolve_write_line(request)
                    elif request.request_type == CacheRequestType.WRITE_LINE_READ_LINE:
                        self.resolve_write_line_read_line(request)
                    else:
                        raise NotImplementedError()

    async def run(self):
        self.clock.create_task(self._monitor_cache_responses())
        self.clock.create_task(self._monitor_items())

    def update(self):
        for index, state in enumerate(self.cache_requests):
            if state is None:
                continue
            assert state.ident == index
            state.update()
            #if all(state.received):
            #    slot_state = self.slot_states[state.slot]
            #    if state.request_type == CacheRequestType.READ_LINE:
            #        if slot_state.state == CacheState.READING:
            #            slot_state.state = CacheState.SHARED
            #            #self.update_cache_avail(state.slot)
            #        else:
            #            assert False
            #    elif state.request_type in CacheRequestType.WRITE_LINE:
            #        if slot_state.state == CacheState.WRITING:
            #            slot_state.state = CacheState.SHARED
            #            #self.update_cache_avail(state.slot)
            #        #elif slot_state.state == CacheState.OLD_WRITING:
            #        #    slot_state.state = CacheState.INVALID
            #        #    # We just finished flushing.
            #        #    # Now we need to read in the new data.
            #    else:
            #        assert False
