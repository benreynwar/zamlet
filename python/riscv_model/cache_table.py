import logging
from dataclasses import dataclass
from enum import Enum
from collections import deque
import random
from typing import Coroutine, List

from runner import Clock, Future
from params import LamletParams


logger = logging.getLogger(__name__)


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
    UNALLOCATED = 6    # Not allocated to any address.
    OLD_MODIFIED = 10  # Has updated data compared to the memory (for old location)
    OLD_READING = 11   # In middle of reading data from the memory (for old location)
    OLD_WRITING = 12   # In middle of writing data to the memory (for old location)


class CacheTable:

    def __init__(self, clock: Clock, params: LamletParams, flush_method, read_method, name=''):
        self.clock = clock
        self.params = params
        self.n_slots = params.jamlet_sram_bytes * params.j_in_k // params.cache_line_bytes
        assert (params.jamlet_sram_bytes * params.j_in_k) % params.cache_line_bytes == 0
        assert self.n_slots >= 4
        self.cache_line_bytes = params.cache_line_bytes
        # For now assume that we're using all of the SRAM for global cache.
        self.slot_states = [CacheLineState() for index in range(self.n_slots)]
        self.free_slots = deque(list(range(self.n_slots)))
        self.used_slots = []
        self._check_slots()
        self.next_read_id = 0
        self.name = name

        # These two methods take the arguments 'slot' and 'address in kamlet memory'
        self.flush_method = flush_method
        self.read_method = read_method

        self.aquiring_slot = False

    def get_read_id(self):
        read_id = self.next_read_id
        self.next_read_id += 1
        return read_id

    async def request_read(self, k_maddr, coro):
        """
        The coroutine will be run once k_maddr is available to read in the cache.
        """
        logger.debug(f'{self.clock.cycle}: {self.name}: Requesting a read for {hex(k_maddr.addr)}')
        # We want to read an address.
        # We might be given a slot that is ready to go.
        # We might be given slot and told we need to evict the current contents.
        # We might be given a slot and told we need to read in the contents.
        slot = self.addr_to_slot(k_maddr)
        if slot is None:
            # There is not slot for this memory address. We need to get a slot.
            slot = await self._get_new_slot(k_maddr)
        else:
            # Mark the slot as recently used
            self.used_slots.remove(slot)
            self.used_slots.append(slot)
        slot_state = self.slot_states[slot]
        slot_state.add_read_request(coro)
        task = self.clock.create_task(self._request_read_resolve(slot, coro))
        return task

    async def _prepare_cache(self, slot):
        slot_state = self.slot_states[slot]
        if slot_state.state == CacheState.OLD_MODIFIED:
            # There may be some values in the batch queue already.
            # They are waiting for when we have the updated data.
            flush_task = self.flush_slot_old(slot)
            await flush_task
        assert slot_state.state in (CacheState.INVALID, CacheState.SHARED,
                                    CacheState.MODIFIED, CacheState.READING, CacheState.WRITING,
                                    CacheState.OLD_WRITING, # A previous access request caused a cache line to flush.
                                    )
        if slot_state.state == CacheState.INVALID:
            read_task = self.read_slot(slot)
            await read_task
        assert slot_state.state in (CacheState.SHARED, CacheState.MODIFIED, CacheState.READING, CacheState.WRITING, CacheState.OLD_WRITING)
        while slot_state.state in (CacheState.READING, CacheState.WRITING, CacheState.OLD_WRITING):
            await self.clock.next_cycle
        assert slot_state.state in (CacheState.SHARED, CacheState.MODIFIED)
        
    async def _request_read_resolve(self, slot, coro):
        await self._prepare_cache(slot)
        # Now we just need to wait for our turn in the batch queue to come up.
        slot_state = self.slot_states[slot]
        while True:
            this_batch = slot_state.batch_queue[0]
            if isinstance(this_batch, WriteBatch):
                if this_batch.coro == coro:
                    assert False
            elif isinstance(this_batch, ReadBatch):
                if coro in this_batch.coros:
                    task = self.clock.create_task(coro)
                    break
            else:
                assert False
            await self.clock.next_cycle
        await task
        assert this_batch == slot_state.batch_queue[0]
        this_batch.coros.remove(coro)
        if not this_batch.coros:
            slot_state.batch_queue.pop(0)
                
    async def request_write(self, k_maddr, coro):
        """
        The coroutine will be run once k_maddr is available to write in the cache.
        """
        logger.debug(f'{self.clock.cycle}: {self.name}: Requesting a write for {hex(k_maddr.addr)}')
        slot = self.addr_to_slot(k_maddr)
        if slot is None:
            # There is not slot for this memory address. We need to get a slot.
            slot = await self._get_new_slot(k_maddr)
            slot_state = self.slot_states[slot]
            assert not slot_state.batch_queue
        else:
            # Mark the slot as recently used
            self.used_slots.remove(slot)
            self.used_slots.append(slot)
        slot_state = self.slot_states[slot]
        slot_state.add_write_request(coro, address=k_maddr.addr)
        task = self.clock.create_task(self._request_write_resolve(slot, coro, k_maddr))
        return task

    async def _request_write_resolve(self, slot, coro, k_maddr):
        logger.debug(f'{self.clock.cycle}: {self.name}: started _request_write_resolve {hex(k_maddr.addr)}')
        await self._prepare_cache(slot)
        # Now we just need to wait for our turn in the batch queue to come up.
        slot_state = self.slot_states[slot]
        while True:
            this_batch = slot_state.batch_queue[0]
            if isinstance(this_batch, WriteBatch):
                if this_batch.coro == coro:
                    task = self.clock.create_task(coro)
                    break
            elif isinstance(this_batch, ReadBatch):
                if coro in this_batch.coros:
                    assert False
            else:
                assert False
            await self.clock.next_cycle
        await task
        assert slot_state.state in (CacheState.SHARED, CacheState.MODIFIED)
        slot_state.state = CacheState.MODIFIED
        assert this_batch == slot_state.batch_queue[0]
        slot_state.batch_queue.pop(0)

    def _check_slots(self):
        assert len(self.free_slots) + len(self.used_slots) == self.n_slots

    def get_state(self, k_maddr):
        slot = self.addr_to_slot(k_maddr)
        return self.slot_states[slot]

    def can_read(self, k_maddr):
        state = self.get_state(k_maddr)
        return state.state in (CacheState.SHARED, CacheState.MODIFIED)

    def can_write(self, k_maddr):
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

    def flush_slot(self, slot):
        """
        This flushes the cache line to memory.
        """
        state = self.slot_states[slot]
        assert state.state == CacheState.MODIFIED
        state.state = CacheState.WRITING
        task = self.clock.create_task(self._flush_slot_resolve(slot))
        return task

    async def _flush_slot_resolve(self, slot):
        state = self.slot_states[slot]
        assert state.state == CacheState.WRITING
        task = await self.flush_method(slot, state.memory_loc*self.params.cache_line_bytes)
        await task
        state.state = CacheState.SHARED

    def flush_slot_old(self, slot):
        state = self.slot_states[slot]
        assert state.state == CacheState.OLD_MODIFIED
        self.slot_states[slot].state = CacheState.OLD_WRITING
        task = self.clock.create_task(self._flush_slot_old_resolve(slot))
        return task

    async def _flush_slot_old_resolve(self, slot):
        state = self.slot_states[slot]
        assert state.state == CacheState.OLD_WRITING
        task = await self.flush_method(slot, state.old_memory_loc*self.params.cache_line_bytes)
        await task
        state = self.slot_states[slot]
        state.state = CacheState.INVALID

    def read_slot(self, slot):
        """
        This reads a cache line into the SRAM.
        It takes a future that should resolve when the data is written.
        It returns a future that resolves when the cache state has been updated.
        """
        assert self.slot_states[slot].state == CacheState.INVALID
        self.slot_states[slot].state = CacheState.READING
        task = self.clock.create_task(self._read_slot_resolve(slot))
        return task

    async def _read_slot_resolve(self, slot):
        state = self.slot_states[slot]
        task = await self.read_method(slot, state.memory_loc*self.params.cache_line_bytes)
        await task
        assert state.state == CacheState.READING
        state.state = CacheState.SHARED

    async def _get_new_slot(self, k_maddr):
        """
        This returns a free slot if it can, otherwise it returns a slot to be evicted.
        """
        assert self.addr_to_slot(k_maddr) is None
        self._check_slots()
        # Adding some assert statements to make sure we don't call one request_read
        # until the previous is finished.
        assert not self.aquiring_slot
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
