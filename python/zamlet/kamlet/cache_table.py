import logging
from dataclasses import dataclass
from enum import Enum
from collections import deque
import random
from typing import Coroutine, List, Any

from zamlet.runner import Clock, Future
from zamlet.params import LamletParams
from zamlet.utils import SettableBool
from zamlet.message import Header, IdentHeader, TaggedHeader, WriteSetIdentHeader
from zamlet.kamlet import kinstructions
from zamlet import addresses
from zamlet.addresses import KMAddr
from zamlet.waiting_item import WaitingItem, WaitingItemRequiresCache
from zamlet.monitor import Monitor, ResourceType


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


class SendState(Enum):
    NEED_TO_SEND = 'NEED_TO_SEND'
    WAITING_FOR_RESPONSE = 'WAITING_FOR_RESPONSE'
    COMPLETE = 'COMPLETE'


class ReceiveState(Enum):
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
    src_state: SendState = SendState.NEED_TO_SEND
    dst_state: ReceiveState = ReceiveState.WAITING_FOR_REQUEST

    def finished(self) -> bool:
        return self.src_state == SendState.COMPLETE and self.dst_state == ReceiveState.COMPLETE


@dataclass
class LoadProtocolState(ProtocolState):
    src_state: SendState = SendState.NEED_TO_SEND
    dst_state: ReceiveState = ReceiveState.WAITING_FOR_REQUEST

    def finished(self) -> bool:
        return self.src_state == SendState.COMPLETE and self.dst_state == ReceiveState.COMPLETE


class WaitingFuture(WaitingItem):

    def __init__(self, future: Future, instr_ident: int):
        """
        This is used in the lamlet.
        When a response is received with header.ident matching instr_ident,
        the future is fired.
        """
        super().__init__(item=future, instr_ident=instr_ident)
        self.future = future


class WaitingStoreJ2JWords(WaitingItemRequiresCache):

    cache_is_write = True

    def __init__(self, params: LamletParams, instr: kinstructions.Store, rf_ident: int|None=None):
        super().__init__(item=instr, instr_ident=instr.instr_ident, writeset_ident=instr.writeset_ident, rf_ident=rf_ident)
        n_tags = instr.n_tags(params) * params.j_in_k
        self.protocol_states: List[StoreProtocolState] = [
                StoreProtocolState() for _ in range(n_tags)]

    def ready(self):
        return all(state.finished() for state in self.protocol_states) and self.cache_is_avail





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

    def __init__(self, clock: Clock, params: LamletParams, name: str, monitor: Monitor,
                 kamlet_x: int = 0, kamlet_y: int = 0):
        self.clock = clock
        self.params = params
        self.monitor = monitor
        self.kamlet_x = kamlet_x
        self.kamlet_y = kamlet_y
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
        # FIFO ordering - oldest items first for priority processing.
        self.waiting_items: deque[WaitingItem] = deque()

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
        n_received = sum(1 for r in state.received if r.peek())
        logger.debug(
            f'{self.clock.cycle}: {self.name}: receive_cache_response '
            f'req={ident} tag={tag} slot={state.slot} '
            f'received={n_received}/{len(state.received)}'
        )

    def has_free_witem_slot(self, use_reserved: bool = False) -> bool:
        """Check if a witem slot is available.

        Args:
            use_reserved: If True, can use reserved slots (for message handlers).
                         If False, must leave n_items_reserved slots free (for kinstructions).
        """
        used = len(self.waiting_items)
        if use_reserved:
            return used < self.params.n_items
        else:
            return used < self.params.n_items - self.params.n_items_reserved

    async def wait_for_free_witem_slot(self, witem: WaitingItem | None = None,
                                        use_reserved: bool = False) -> None:
        """Wait until a witem slot is available.

        Args:
            witem: The witem requesting the slot (for monitoring).
            use_reserved: If True, can use reserved slots (for message handlers).
                         If False, must leave n_items_reserved slots free (for kinstructions).
        """
        if self.has_free_witem_slot(use_reserved):
            return
        # Table is full - record resource exhaustion
        self.monitor.record_resource_exhausted(
            ResourceType.WITEM_TABLE, self.kamlet_x, self.kamlet_y)
        if witem is not None:
            self.monitor.record_witem_blocked_by_resource(
                witem.instr_ident, self.kamlet_x, self.kamlet_y, ResourceType.WITEM_TABLE)
        while True:
            if self.has_free_witem_slot(use_reserved):
                break
            await self.clock.next_cycle
        # Slot freed - record resource available
        self.monitor.record_resource_available(
            ResourceType.WITEM_TABLE, self.kamlet_x, self.kamlet_y)

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

    async def get_free_cache_request(self, witem: WaitingItem | None = None):
        valid_indices = [index for index, x in enumerate(self.cache_requests) if x is None]
        if valid_indices:
            return valid_indices[0]
        # Table is full - record resource exhaustion
        self.monitor.record_resource_exhausted(
            ResourceType.CACHE_REQUEST_TABLE, self.kamlet_x, self.kamlet_y)
        if witem is not None:
            self.monitor.record_witem_blocked_by_resource(
                witem.instr_ident, self.kamlet_x, self.kamlet_y, ResourceType.CACHE_REQUEST_TABLE)
        while True:
            valid_indices = [index for index, x in enumerate(self.cache_requests) if x is None]
            if valid_indices:
                break
            await self.clock.next_cycle
        # Slot freed - record resource available
        self.monitor.record_resource_available(
            ResourceType.CACHE_REQUEST_TABLE, self.kamlet_x, self.kamlet_y)
        return valid_indices[0]

    def _any_reads_all_memory(self) -> bool:
        """Check if any waiting item reads from all memory."""
        for item in self.waiting_items:
            if item.reads_all_memory:
                return True
        return False

    def _any_writes_all_memory(self, writeset_ident: int | None = None) -> bool:
        """Check if any waiting item writes to all memory.

        If writeset_ident is provided, items with matching writeset_ident are excluded.
        """
        for item in self.waiting_items:
            if item.writes_all_memory:
                if writeset_ident is not None and hasattr(item, 'writeset_ident'):
                    if item.writeset_ident == writeset_ident:
                        continue
                return True
        return False

    def _record_blocked_by_witems(self, blocked_witem: WaitingItem, predicate, reason: str):
        """Record monitor dependencies from blocked_witem to all witems matching predicate.

        This is for critical path analysis - records that blocked_witem is waiting on
        other witems that match the predicate.

        predicate: function(witem) -> bool
        """
        blocked_span_id = self.monitor.get_witem_span_id(
            blocked_witem.instr_ident, self.kamlet_x, self.kamlet_y)
        if blocked_span_id is None:
            return
        for item in self.waiting_items:
            if predicate(item):
                blocking_span_id = self.monitor.get_witem_span_id(
                    item.instr_ident, self.kamlet_x, self.kamlet_y)
                if blocking_span_id is not None:
                    self.monitor.add_dependency(blocked_span_id, blocking_span_id, reason)

    async def wait_for_slot_to_be_writeable(self, slot: int, k_maddr: KMAddr) -> None:
        while True:
            assert slot == self.addr_to_slot(k_maddr)
            if not self.slot_in_use(slot) and not self._any_reads_all_memory():
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

    def add_witem_immediately(self, witem: WaitingItem, use_reserved: bool = False):
        assert self.has_free_witem_slot(use_reserved=use_reserved)
        self.waiting_items.append(witem)

    async def add_witem(self, witem: WaitingItem, k_maddr: KMAddr|None=None,
                        use_reserved: bool = False):
        if witem.cache_is_read or witem.cache_is_write:
            assert k_maddr is not None
            assert not (witem.cache_is_read and witem.cache_is_write)
            # Wait for writes_all_memory/reads_all_memory to complete first, then check slot
            if self._any_writes_all_memory(witem.writeset_ident):
                self._record_blocked_by_witems(
                    witem,
                    lambda item: (item.writes_all_memory and
                                  (witem.writeset_ident is None or
                                   getattr(item, 'writeset_ident', None) != witem.writeset_ident)),
                    "blocked_by_writes_all_memory")
                await self._wait_for_writes_all_memory_complete(witem.writeset_ident)
            if witem.cache_is_write and self._any_reads_all_memory():
                self._record_blocked_by_witems(
                    witem, lambda item: item.reads_all_memory, "blocked_by_reads_all_memory")
                await self._wait_for_reads_all_memory_complete()
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
                    if self.slot_in_use(slot) or self._any_reads_all_memory():
                        # If there are other witems in the midst of a read or write we need
                        # to wait for them to complete
                        self._record_blocked_by_witems(
                            witem,
                            lambda item: (item.cache_slot == slot or item.reads_all_memory),
                            "blocked_by_slot_in_use")
                        await self.wait_for_slot_to_be_writeable(slot, k_maddr)
                if witem.cache_is_read:
                    if self.slot_has_write(slot):
                        self._record_blocked_by_witems(
                            witem,
                            lambda item: item.cache_is_write and item.cache_slot == slot,
                            "blocked_by_slot_write")
                        await self.wait_for_slot_to_be_readable(slot, k_maddr)
                witem.cache_is_avail = (
                        self.slot_states[slot].state in (CacheState.SHARED, CacheState.MODIFIED))
                logger.debug(
                    f'{self.clock.cycle}: {self.name}: slot state={self.slot_states[slot].state}, '
                    f'cache_is_avail={witem.cache_is_avail}'
                )
        # If this witem reads all memory, wait for all pending writes to complete first
        if witem.reads_all_memory:
            self._record_blocked_by_witems(
                witem, lambda item: item.cache_is_write, "reads_all_blocked_by_writes")
            await self._wait_for_all_writes_complete()
        # If this witem writes all memory, wait for all pending reads and other
        # writes_all_memory witems to complete first
        if witem.writes_all_memory:
            self._record_blocked_by_witems(
                witem,
                lambda item: (item.cache_is_read and
                              (witem.writeset_ident is None or
                               getattr(item, 'writeset_ident', None) != witem.writeset_ident)),
                "writes_all_blocked_by_reads")
            await self._wait_for_all_reads_complete(witem.writeset_ident)
            self._record_blocked_by_witems(
                witem,
                lambda item: (item.writes_all_memory and
                              (witem.writeset_ident is None or
                               getattr(item, 'writeset_ident', None) != witem.writeset_ident)),
                "writes_all_blocked_by_writes_all")
            await self._wait_for_writes_all_memory_complete(witem.writeset_ident)
        await self.wait_for_free_witem_slot(witem, use_reserved=use_reserved)
        self.waiting_items.append(witem)
        if witem.cache_is_read or witem.cache_is_write:
            witem.cache_is_avail = (
                    self.slot_states[witem.cache_slot].state in (CacheState.SHARED, CacheState.MODIFIED))

    async def _wait_for_all_writes_complete(self) -> None:
        """Wait until all pending write witems have completed."""
        while True:
            has_writes = any(item.cache_is_write for item in self.waiting_items)
            if not has_writes:
                break
            await self.clock.next_cycle

    async def _wait_for_reads_all_memory_complete(self) -> None:
        """Wait until all pending reads_all_memory witems have completed."""
        while True:
            if not self._any_reads_all_memory():
                break
            await self.clock.next_cycle

    async def _wait_for_writes_all_memory_complete(self, writeset_ident: int | None = None) -> None:
        """Wait until all pending writes_all_memory witems have completed."""
        while True:
            if not self._any_writes_all_memory(writeset_ident):
                break
            await self.clock.next_cycle

    async def _wait_for_all_reads_complete(self, writeset_ident: int | None = None) -> None:
        """Wait until all pending read witems have completed."""
        while True:
            has_reads = False
            for item in self.waiting_items:
                if item.cache_is_read:
                    if writeset_ident is not None and item.writeset_ident == writeset_ident:
                        continue
                    has_reads = True
                    break
            if not has_reads:
                break
            await self.clock.next_cycle

    async def update_cache(self, slot, witem: WaitingItem | None = None):
        slot_state = self.slot_states[slot]
        # We want to read an address.
        # We might be given a slot that is ready to go.
        # We might be given slot and told we need to evict the current contents.
        # We might be given a slot and told we need to read in the contents.

        cache_request_index = await self.get_free_cache_request(witem)
        # There is not slot for this memory address. We need to get a slot.
        if slot_state.state == CacheState.INVALID:
            request_type = CacheRequestType.READ_LINE
            n_sent = 1
            request_addr = slot_state.memory_loc * self.params.cache_line_bytes
        elif slot_state.state == CacheState.OLD_MODIFIED:
            request_type = CacheRequestType.WRITE_LINE_READ_LINE
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

        # Track cache request in monitor
        parent_span_id = None
        if witem is not None:
            source = getattr(witem, 'source', None)
            source_x = source[0] if source else None
            source_y = source[1] if source else None
            parent_span_id = self.monitor.get_witem_span_id(
                witem.instr_ident, self.kamlet_x, self.kamlet_y,
                source_x=source_x, source_y=source_y)
        self.monitor.record_cache_request_created(
            self.kamlet_x, self.kamlet_y, slot,
            request_type=request_type.value,
            memory_loc=slot_state.memory_loc,
            parent_span_id=parent_span_id,
        )

        # Update the slot state immediately to prevent duplicate cache requests
        if request_type == CacheRequestType.READ_LINE:
            slot_state.state = CacheState.READING
        elif request_type == CacheRequestType.WRITE_LINE_READ_LINE:
            slot_state.state = CacheState.WRITING_READING

    def _check_slots(self):
        assert len(self.free_slots) + len(self.used_slots) == self.n_slots
        assert len(set(self.free_slots)) == len(self.free_slots)
        assert len(set(self.used_slots)) == len(self.used_slots)

    def get_state(self, k_maddr):
        slot = self.addr_to_slot(k_maddr)
        return self.slot_states[slot]

    def can_read(self, k_maddr, writeset_ident: int | None = None):
        slot = self.addr_to_slot(k_maddr)
        if slot is None:
            return False
        # Block reads if any witem writes to all memory (unless same writeset_ident)
        if self._any_writes_all_memory(writeset_ident):
            return False
        state = self.get_state(k_maddr)
        good_state = state.state in (CacheState.SHARED, CacheState.MODIFIED)
        has_write = self.slot_has_write(slot)
        return good_state and not has_write

    def can_write(self, k_maddr, witem: WaitingItem | None = None):
        writeset_ident = witem.writeset_ident if witem is not None else None
        slot = self.addr_to_slot(k_maddr)
        loc = f'{self.clock.cycle}: CacheTable {self.name}'
        if slot is None:
            logger.debug(f'{loc} can_write: addr=0x{k_maddr.addr:x} writeset={writeset_ident} '
                         f'slot=None -> False')
            return False
        # Block writes if any witem reads from all memory
        for item in self.waiting_items:
            if item != witem and item.reads_all_memory:
                logger.debug(f'{loc} can_write: addr=0x{k_maddr.addr:x} writeset={writeset_ident} '
                             f'reads_all_memory by ident={item.instr_ident} -> False')
                return False
        # Block writes if any witem writes to all memory (unless same writeset_ident)
        if self._any_writes_all_memory(writeset_ident):
            logger.debug(f'{loc} can_write: addr=0x{k_maddr.addr:x} writeset={writeset_ident} '
                         f'writes_all_memory -> False')
            return False
        state = self.get_state(k_maddr)
        good_state = state.state in (CacheState.SHARED, CacheState.MODIFIED)
        in_use = self.slot_in_use(slot, writeset_ident=writeset_ident)
        if not good_state:
            logger.debug(f'{loc} can_write: addr=0x{k_maddr.addr:x} writeset={writeset_ident} '
                         f'slot={slot} state={state.state} -> False')
        elif in_use:
            logger.debug(f'{loc} can_write: addr=0x{k_maddr.addr:x} writeset={writeset_ident} '
                         f'slot={slot} in_use -> False')
        return good_state and not in_use

    def slot_has_write(self, slot):
        # Check to see if there are any waiting items using this slot.
        slot_in_use = False
        for item in self.waiting_items:
            using_cache = item.cache_is_write
            if item.cache_slot == slot and using_cache:
                slot_in_use = True
        if slot_in_use:
            assert slot in self.used_slots
        return slot_in_use

    def slot_in_use(self, slot, writeset_ident: int | None = None):
        # Check to see if there are any waiting items using this slot.
        slot_in_use = False
        for other_witem in self.waiting_items:
            # Skip items with matching writeset_ident (they're part of the same operation)
            if writeset_ident is not None and other_witem.writeset_ident == writeset_ident:
                continue
            using_cache = other_witem.cache_is_read or other_witem.cache_is_write
            if using_cache and other_witem.cache_slot == slot:
                slot_in_use = True
        if slot_in_use:
            assert slot in self.used_slots
        return slot_in_use

    def get_waiting_item_by_instr_ident(self, instr_ident: int,
                                         source: tuple[int, int]|None=None) -> WaitingItem|None:
        matching_items = []
        for item in self.waiting_items:
            if item.instr_ident != instr_ident:
                continue
            if item.use_source_to_match:
                assert source is not None, \
                    f'source must be provided when matching {type(item).__name__}'
                if item.source == source:
                    matching_items.append(item)
            else:
                matching_items.append(item)
        if not matching_items:
            return None
        assert len(matching_items) == 1
        return matching_items[0]

    def get_oldest_active_instr_ident_distance(self, baseline: int) -> int | None:
        """Return the distance to the oldest active instr_ident from baseline.

        Distance is computed as (ident - baseline) % max_response_tags, so older idents
        (further back in the circular space) have smaller distances.

        Returns None if no waiting items have an instr_ident set (all free).
        """
        max_tags = self.params.max_response_tags
        idents = [item.instr_ident for item in self.waiting_items
                  if item.instr_ident is not None]
        if not idents:
            return None  # All free
        distances = [(ident - baseline) % max_tags for ident in idents]
        return min(distances)

    def can_get_slot(self, k_maddr: KMAddr) -> bool:
        slot = self.addr_to_slot(k_maddr)
        if slot is None:
            return self._can_get_new_slot(k_maddr)
        else:
            return True

    def get_slot_if_exists(self, k_maddr: KMAddr) -> int|None:
        slot = self.addr_to_slot(k_maddr)
        if slot is None:
            return self._get_new_slot_if_exists(k_maddr)
        else:
            return slot

    def _can_get_new_slot(self, k_maddr: KMAddr) -> bool:
        # Block allocation if another slot is writing back this memory_loc
        memory_loc = k_maddr.addr // self.cache_line_bytes
        for slot_state in self.slot_states:
            if (slot_state.old_memory_loc == memory_loc and
                    slot_state.state == CacheState.WRITING_READING):
                return False
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
        # Block allocation if another slot is writing back this memory_loc
        memory_loc = k_maddr.addr // self.cache_line_bytes
        for slot_state in self.slot_states:
            if (slot_state.old_memory_loc == memory_loc and
                    slot_state.state == CacheState.WRITING_READING):
                return None
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
            slot_state = self.slot_states[slot]
            slot_state.old_memory_loc = slot_state.memory_loc
            slot_state.memory_loc = k_maddr.addr // self.cache_line_bytes
            # Transition state to trigger cache update
            assert slot_state.state in (
                CacheState.SHARED, CacheState.MODIFIED, CacheState.UNALLOCATED, CacheState.INVALID
            ), f'Unexpected cache state: {slot_state.state}'
            if slot_state.state == CacheState.SHARED:
                slot_state.state = CacheState.INVALID
            elif slot_state.state == CacheState.MODIFIED:
                slot_state.state = CacheState.OLD_MODIFIED
            elif slot_state.state == CacheState.UNALLOCATED:
                slot_state.state = CacheState.INVALID
            logger.debug(
                f'{self.clock.cycle}: CACHE_LINE_ALLOC: {self.name} slot={slot} '
                f'memory_loc=0x{slot_state.memory_loc:x}'
            )
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

        self._check_slots()
        return slot

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

    def clear_cache_request_sent(self, ident: int, j_in_k_index: int):
        """Clear the sent flag for a cache request after receiving a DROP.

        This allows the kamlet's _monitor_cache_requests to re-send the request.
        """
        request = self.cache_requests[ident]
        assert request is not None, f'No cache request for ident={ident}'
        assert request.request_type == CacheRequestType.WRITE_LINE_READ_LINE
        request.sent[j_in_k_index].set(False)
        logger.debug(
            f'{self.clock.cycle}: [CACHE_TABLE] clear_cache_request_sent ident={ident} '
            f'j_in_k_index={j_in_k_index}'
        )

    def resolve_read_line(self, request: CacheRequestState):
        assert self.cache_requests[request.ident] == request
        self.cache_requests[request.ident] = None
        state = self.slot_states[request.slot]
        assert state.state == CacheState.READING
        state.state = CacheState.SHARED
        for witem in self.waiting_items:
            if isinstance(witem, WaitingItemRequiresCache) and witem.cache_slot == request.slot:
                assert not witem.cache_is_avail
                witem.cache_is_avail = True
        self.monitor.record_cache_request_completed(
            self.kamlet_x, self.kamlet_y, request.slot)

    def resolve_write_line_read_line(self, request: CacheRequestState):
        assert self.cache_requests[request.ident] == request
        self.cache_requests[request.ident] = None
        state = self.slot_states[request.slot]
        assert state.state == CacheState.WRITING_READING
        state.state = CacheState.SHARED
        for item in self.waiting_items:
            if item.cache_slot == request.slot:
                logger.debug(f'{self.clock.cycle}: {self.name}: resolve_write_line_read_line '
                             f'slot={request.slot} setting cache_is_avail for {type(item).__name__} '
                             f'instr_ident={item.instr_ident}')
                item.cache_is_avail = True
        self.monitor.record_cache_request_completed(
            self.kamlet_x, self.kamlet_y, request.slot)

    async def _monitor_items(self) -> None:
        """
        Creates cache requests for items that have cache slots that need updating.
        """
        while True:
            await self.clock.next_cycle
            for witem in list(self.waiting_items):
                if witem not in self.waiting_items:
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
                            await self.update_cache(slot, witem=witem)

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
