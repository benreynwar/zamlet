import logging
from dataclasses import dataclass
from enum import Enum
from collections import deque
import random
from typing import Coroutine, List, Any

from runner import Clock, Future
from params import LamletParams
from utils import SettableBool
from message import Header, IdentHeader


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


@dataclass
class ResponseInfo:
    # The response has been received.
    received: bool = False
    # The response let's us know the request was dropped.
    # Used to resent the request.
    drop_notification: bool = False


#@dataclass
#class LoadRequest:
#    addr: KMAddr
#    n_words: int
#    src_x: int
#    src_y: int


@dataclass
class WaitingItem:
    item: Any   # LoadRequest or KInstr
    response_infos: List[ResponseInfo]
    step: int = 0
    cache_is_write: bool = False
    cache_is_avail: bool = False
    cache_slot: int|None = None


@dataclass
class WriteBatch:
    coro: Coroutine
    address: int


@dataclass
class ReadBatch:
    coros: List[Coroutine]


class CacheLineState:

    def __init__(self):
        self.state = CacheState.UNALLOCATED
        # The memory address divided by the cache line size
        self.memory_loc = None
        # The memory address of something that we're in the process of evicting
        self.old_memory_loc = None
        self.batch_queue = []

    def add_read_request(self, coro):
        if not self.batch_queue or not isinstance(self.batch_queue[-1], ReadBatch):
            self.batch_queue.append(ReadBatch([]))
        self.batch_queue[-1].coros.append(coro)

    def add_write_request(self, coro, address=None):
        self.batch_queue.append(WriteBatch(coro, address))


class CacheState(Enum):
    INVALID = 0        # Unitialized data
    SHARED = 1         # Data matches the memory
    MODIFIED = 2       # Has updated data compared to the memory
    READING = 3        # In middle of reading data from the memory
    WRITING = 4        # In middle of writing data to the memory
    WRITING_READING = 5  # In middle of writing data to the memory and reading new data
    UNALLOCATED = 6    # Not allocated to any address.
    OLD_MODIFIED = 10  # Has updated data compared to the memory (for old location)
    #OLD_READING = 11   # In middle of reading data from the memory (for old location)
    #OLD_WRITING = 12   # In middle of writing data to the memory (for old location)


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

    def receive_cache_response(self, header: IdentHeader):
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

    async def get_free_item_index(self):
        while True:
            valid_indices = [index for index, x in enumerate(self.waiting_items) if x is None]
            if valid_indices:
                break
            await self.clock.next_cycle
        return valid_indices[0]

    def get_cache_request(self, slot):
        valid_indices = [index for index, x in enumerate(self.cache_requests) if x is not None and x.slot == slot]
        assert len(valid_indices) == 1
        return valid_indices[0]

    async def get_free_cache_request(self):
        logger.debug('get_free_cache_request: start')
        while True:
            valid_indices = [index for index, x in enumerate(self.cache_requests) if x is None]
            if valid_indices:
                break
            await self.clock.next_cycle
        logger.debug('get_free_cache_request: end')
        return valid_indices[0]

    async def add_item(self, new_item, response_tags, cache_is_write, cache_slot, step):
        response_infos = [ResponseInfo(received=False, drop_notification=False) for req in response_tags]
        cache_is_avail = self.slot_states[cache_slot].state in (CacheState.SHARED, CacheState.MODIFIED)
        item = WaitingItem(
            item=new_item,
            response_infos=response_infos,
            cache_is_write=cache_is_write,
            cache_is_avail=cache_is_avail,
            cache_slot=cache_slot,
            step=step,
            )
        new_item_index = await self.get_free_item_index()
        self.waiting_items[new_item_index] = item
        return new_item_index

    def get_read_id(self):
        read_id = self.next_read_id
        self.next_read_id += 1
        return read_id

    async def request_read(self, k_maddr, item, step):
        """
        The item with handled with the argument 'step' once the cache read is done.
        """
        logger.debug(f'{self.clock.cycle}: {self.name}: Requesting a read for {hex(k_maddr.addr)}')
        # We want to read an address.
        # We might be given a slot that is ready to go.
        # We might be given slot and told we need to evict the current contents.
        # We might be given a slot and told we need to read in the contents.
        slot = self.addr_to_slot(k_maddr)
        if slot is None:
            cache_request_index = await self.get_free_cache_request()
            # There is not slot for this memory address. We need to get a slot.
            slot = await self._get_new_slot(k_maddr)
            slot_state = self.slot_states[slot]
            if slot_state.state == CacheState.INVALID:
                request_type=CacheRequestType.READ_LINE
                n_sent = 1
            elif slot_state.state == CacheState.OLD_MODIFIED:
                request_type=CacheRequestType.WRITE_LINE_READ_LINE
                n_sent = self.params.j_in_k
            else:
                assert False
            assert self.cache_requests[cache_request_index] is None
            cache_request = CacheRequestState(
                    ident=cache_request_index,
                    addr=k_maddr.addr,
                    slot=slot,
                    sent=[SettableBool(False) for x in range(n_sent)],
                    received=[SettableBool(False) for x in range(self.params.j_in_k)],
                    request_type=request_type,
                    )
            self.cache_requests[cache_request_index] = cache_request
        else:
            # We have a slot but it might be in the process of loading in.
            slot_state = self.slot_states[slot]
            assert slot_state.state in (CacheState.READING, CacheState.WRITING, CacheState.WRITING_READING)
            # If it was shared or modified we can use it immediately and this
            # function shouldn't have been called.
            cache_request_index = self.get_cache_request(slot)
            # Mark the slot as recently used
            self.used_slots.remove(slot)
            self.used_slots.append(slot)
        await self.add_item(item, [], cache_is_write=False, cache_slot=slot, step=step)

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
                
    async def request_write(self, k_maddr, item, step):
        """
        The coroutine will be run once k_maddr is available to write in the cache.
        """
        logger.debug(f'{self.clock.cycle}: {self.name}: Requesting a write for {hex(k_maddr.addr)}')

        logger.warning('adding item')
        logger.warning('added item')

        slot = self.addr_to_slot(k_maddr)
        if slot is None:
            cache_request_index = await self.get_free_cache_request()
            # There is not slot for this memory address. We need to get a slot.
            slot = await self._get_new_slot(k_maddr)
            await self.add_item(item, [], cache_is_write=True, cache_slot=slot, step=step)
            slot_state = self.slot_states[slot]
            if slot_state.state == CacheState.INVALID:
                request_type=CacheRequestType.READ_LINE
                n_send = 1
            elif slot_state.state == CacheState.OLD_MODIFIED:
                request_type=CacheRequestType.WRITE_LINE_READ_LINE
                n_send = self.params.j_in_k
            else:
                assert False
            assert self.cache_requests[cache_request_index] is None
            cache_request = CacheRequestState(
                    ident=cache_request_index,
                    slot=slot,
                    addr=k_maddr.addr,
                    sent=[SettableBool(False) for x in range(n_send)],
                    received=[SettableBool(False) for x in range(self.params.j_in_k)],
                    request_type=request_type,
                    )
            self.cache_requests[cache_request_index] = cache_request
        else:
            await self.add_item(item, [], cache_is_write=True, cache_slot=slot, step=step)
            # We have a slot but it might be in the process of loading in.
            slot_state = self.slot_states[slot]
            assert slot_state.state in (CacheState.READING, CacheState.WRITING, CacheState.WRITING_READING)
            # If it was shared or modified we can use it immediately and this
            # function shouldn't have been called.
            cache_request_index = self.get_cache_request(slot)
            # Mark the slot as recently used
            self.used_slots.remove(slot)
            self.used_slots.append(slot)
        return cache_request_index

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

    def get_state(self, k_maddr):
        slot = self.addr_to_slot(k_maddr)
        return self.slot_states[slot]

    def can_read(self, k_maddr):
        slot = self.addr_to_slot(k_maddr)
        if slot is None:
            return False
        else:
            state = self.get_state(k_maddr)
            return state.state in (CacheState.SHARED, CacheState.MODIFIED)

    def can_write(self, k_maddr):
        slot = self.addr_to_slot(k_maddr)
        if slot is None:
            return False
        else:
            state = self.get_state(k_maddr)
            return state.state in (CacheState.SHARED, CacheState.MODIFIED)

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

    async def _get_new_slot(self, k_maddr):
        """
        This returns a free slot if it can, otherwise it returns a slot to be evicted.
        """
        logger.debug('Trying to get a new slot')
        assert self.addr_to_slot(k_maddr) is None
        self._check_slots()
        # Adding some assert statements to make sure we don't call one request_read
        # until the previous is finished.
        assert not self.acquiring_slot
        self.aquiring_slot = True
        slot = None
        while True:
            if self.free_slots:
                slot = self.free_slots.popleft()
            else:
                for check_slot in self.used_slots:
                    state = self.slot_states[check_slot]
                    #assert len(state.batch_queue) < 4
                    if not state.batch_queue:
                        slot = check_slot
                        self.used_slots.remove(slot)
                        break
            if slot is not None:
                break
            await self.clock.next_cycle
        self.aquiring_slot = False
        self.used_slots.append(slot)

        slot_state = self.slot_states[slot]
        assert slot_state.batch_queue == []
        slot_state.old_memory_loc = slot_state.memory_loc
        slot_state.memory_loc = k_maddr.addr//self.cache_line_bytes
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

    def report_sent_request(self, request: CacheRequestState):
        assert self.cache_requests[request.ident] == request
        assert len(request.sent) == 1
        request.sent[0].set(True)
        if request.request_type == CacheRequestType.READ_LINE:
            assert self.slot_states[request.slot].state == CacheState.INVALID
            self.slot_states[request.slot].state = CacheState.READING
        elif request.request_type == CacheRequestType.WRITE_LINE_READ_LINE:
            assert self.slot_states[request.slot].state == CacheState.OLD_MODIFIED
            self.slot_states[request.slot].state = CacheState.WRITING_READING
        else:
            raise NotImplementedError()

    def resolve_read_line(self, request: CacheRequestState):
        logger.warning('resolving read line')
        assert self.cache_requests[request.ident] == request
        self.cache_requests[request.ident] = None
        state = self.slot_states[request.slot]
        assert state.state == CacheState.READING
        state.state = CacheState.SHARED
        for item in self.waiting_items:
            if item is not None and item.cache_slot == request.slot:
                logger.warning(f'item {item} has available cache')
                item.cache_is_avail = True

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
                    if request.request_type == CacheRequestType.READ_LINE:
                        logger.warning('Read line resolved')
                        self.resolve_read_line(request)
                    #elif request.request_type == CacheRequestType.WRITE_LINE:
                    #    self.cache_table.resolve_write_line(request)
                    elif request.request_type == CacheRequestType.WRITE_LINE_READ_LINE:
                        self.resolve_write_line_read_line(request)
                    else:
                        raise NotImplementedError()

    async def run(self):
        self.clock.create_task(self._monitor_cache_responses())

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
