"""
Instruction identifier flow control for the lamlet.

This module handles allocation and tracking of instruction identifiers (idents)
which are used to match responses to requests in the distributed system.
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from zamlet.transactions.ident_query import IdentQuery
from zamlet.monitor import ResourceType
from zamlet.synchronization import (
    SyncAggOp, unpack_min_with_active_mask,
)

if TYPE_CHECKING:
    from zamlet.oamlet.oamlet import Oamlet
    from zamlet.params import ZamletParams
    from zamlet.synchronization import Synchronizer
    from zamlet.monitor import Monitor

logger = logging.getLogger(__name__)


@dataclass
class IdentQuerySlot:
    """State for one in-flight ident query.

    Lifecycle: allocated in create_ident_query, then consumed/freed when
    the lamlet sees the query sync complete. Sync-id reuse is tracked
    separately by the active-mask response.
    """
    baseline: int = 0
    sync_ident: int = 0
    lamlet_dist: int | None = None
    tokens: list[int] = field(default_factory=list)
    allocated_sync_idents_snapshot: set[int] = field(default_factory=set)
    # Span id of the IdentQuery kinstr. Captured at create_ident_query
    # time for debug and monitor cross-checking.
    span_id: int | None = None
    dispatch_cycle: int | None = None
    # True iff the poll has processed this slot's response.
    consumed: bool = False
    # Last cycle where we logged that this slot was blocking response polling.
    last_wait_log_cycle: int | None = None


def _format_iq_ring_state(lamlet: 'Oamlet') -> str:
    """Render the lamlet's IQ ring for debug logs."""
    n_iq = len(lamlet._iq_slots)
    parts = [
        f"oldest={lamlet._oldest_active_ident_query_slot}",
        f"submitted={list(lamlet._submitted_ident_query_slots)}",
        f"allocated_syncs={list(lamlet._allocated_ident_query_syncs)}",
        f"newest={lamlet._next_ident_query_slot}",
    ]
    for i in range(n_iq):
        slot = lamlet._iq_slots[i]
        if slot is None:
            parts.append(f"[{i}] ident={lamlet._iq_idents[i]} free")
            continue
        parts.append(
            f"[{i}] ident={lamlet._iq_idents[i]} sync={slot.sync_ident} "
            f"consumed={slot.consumed} span={slot.span_id} "
            f"baseline={slot.baseline}")
    return " | ".join(parts)


def _active_sync_idents_from_mask(params: 'ZamletParams', active_mask: int) -> set[int]:
    """Convert an IdentQuery active-mask payload into a Python set of sync ids."""
    return {
        sync_ident for sync_ident in range(params.max_concurrent_syncs)
        if active_mask & (1 << sync_ident)
    }


class SyncIdentAllocator:
    """Sparse sync-id allocator driven by IdentQuery active-mask responses.

    Sync ids are globally reusable only after two facts are true at the lamlet:
    a later IdentQuery has observed the id inactive in the sync network, and
    the lamlet's local synchronizer has completed that id. Inactive
    observations are used only for the IdentQuery response that produced them.
    """

    def __init__(
            self, params: 'ZamletParams', synchronizer: 'Synchronizer',
            monitor: 'Monitor'):
        """Create an empty allocator with only the services it needs."""
        self.params = params
        self.synchronizer = synchronizer
        self.monitor = monitor
        self.allocated: set[int] = set()
        self.needs_finish: set[int] = set()

    def free_idents(self) -> list[int]:
        """Return currently unallocated sync ids in deterministic order."""
        return [
            sync_ident
            for sync_ident in range(self.params.max_concurrent_syncs)
            if sync_ident not in self.allocated
        ]

    def allocate_one(
            self, *, allow_last: bool = False,
            needs_finish: bool = False) -> int | None:
        """Allocate one sync id, or return None if only IQ reserves remain."""
        free = self.free_idents()
        if not free:
            return None
        if not allow_last and len(free) <= 2:
            return None
        sync_ident = free[0]
        self._allocate(sync_ident, needs_finish=needs_finish)
        return sync_ident

    def allocate_many(
            self, n_idents: int, *, allow_last: bool = False,
            needs_finish: bool | list[bool] = False) -> list[int] | None:
        """Allocate several sync ids atomically, preserving IdentQuery reserves."""
        if isinstance(needs_finish, bool):
            needs_finish_flags = [needs_finish] * n_idents
        else:
            needs_finish_flags = needs_finish
            assert len(needs_finish_flags) == n_idents, (
                f"needs_finish has {len(needs_finish_flags)} entries for "
                f"{n_idents} sync ids")

        free = self.free_idents()
        reserve = 0 if allow_last else 2
        if len(free) < n_idents + reserve:
            return None
        sync_idents = free[:n_idents]
        for sync_ident, needs_finish in zip(sync_idents, needs_finish_flags):
            self._allocate(sync_ident, needs_finish=needs_finish)
        return sync_idents

    def _allocate(self, sync_ident: int, *, needs_finish: bool) -> None:
        """Mark a sync id allocated and clear old state for its new use."""
        if self.synchronizer.is_complete(sync_ident):
            self.synchronizer.clear_sync(sync_ident)
        self.allocated.add(sync_ident)
        if needs_finish:
            self.needs_finish.add(sync_ident)
        else:
            self.needs_finish.discard(sync_ident)

    def finish(self, sync_ident: int) -> None:
        """Allow a sync id to be reclaimed after its user has consumed it.

        Some sync users need the completed synchronizer value after the sync
        network is done. For those users, completion alone is not enough to
        recycle the id; the user calls this after it has copied the result.
        """
        assert sync_ident in self.allocated, (
            f"Cannot finish unallocated sync_ident={sync_ident}")
        self.needs_finish.discard(sync_ident)

    def observe_active_mask(
            self, active_mask: int, allocated_snapshot: set[int]) -> set[int]:
        """Consume one IdentQuery active mask and reclaim safe sync ids.

        ``allocated_snapshot`` is the set of sync ids that were allocated when
        this IdentQuery was created. ``active_mask`` says which sync ids this
        IdentQuery saw as active.
        """
        active = _active_sync_idents_from_mask(self.params, active_mask)
        before = set(self.allocated)
        # An inactive observation is only useful for this IdentQuery response.
        # If the sync is not complete now, a later query must observe it
        # inactive again.
        observed_inactive = allocated_snapshot - active
        reclaimable = {
            sync_ident for sync_ident in self.allocated
            if sync_ident in observed_inactive
            and self.synchronizer.is_complete(sync_ident)
            and sync_ident not in self.needs_finish
        }
        for sync_ident in sorted(reclaimable):
            sync_span_id = self.monitor._sync_by_key.get((sync_ident, None))
            if sync_span_id is not None:
                sync_span = self.monitor.spans.get(sync_span_id)
                sync_tree = (
                    self.monitor.format_span_tree(sync_span_id)
                    if sync_span is not None else "<sync span missing>")
                assert False, (
                    f"IdentQuery attempted to reclaim sync_ident={sync_ident} "
                    f"while its monitor sync span still exists. "
                    f"active_mask=0x{active_mask:x} "
                    f"allocated_before={sorted(before)} "
                    f"snapshot={sorted(allocated_snapshot)} "
                    f"active={sorted(active)} "
                    f"sync_span_id={sync_span_id} "
                    f"sync_completed={None if sync_span is None else sync_span.completed_cycle}\n\n"
                    f"Sync span:\n{sync_tree}")
        self.allocated -= reclaimable
        self.needs_finish -= reclaimable
        return before - self.allocated

    def snapshot(self) -> set[int]:
        """Return the allocated-id set to embed in a new IdentQuery slot."""
        return set(self.allocated)


def _free_sync_idents(lamlet: 'Oamlet') -> list[int]:
    """Return sync ids that the lamlet allocator can hand out now."""
    return lamlet.sync_ident_allocator.free_idents()


def get_sync_ident(
        lamlet: 'Oamlet', *, allow_last: bool = False,
        needs_finish: bool = False) -> int | None:
    """Allocate a sparse sync id.

    Normal sync users leave two free ids reserved so IdentQuery can run to
    reclaim sync ids. IdentQuery passes allow_last=True.
    """
    return lamlet.sync_ident_allocator.allocate_one(
        allow_last=allow_last, needs_finish=needs_finish)


def _get_sync_idents(
        lamlet: 'Oamlet', n_idents: int, *, allow_last: bool = False,
        needs_finish: bool | list[bool] = False) -> list[int] | None:
    return lamlet.sync_ident_allocator.allocate_many(
        n_idents, allow_last=allow_last, needs_finish=needs_finish)


async def wait_for_sync_ident(
        lamlet: 'Oamlet', *, allow_last: bool = False,
        needs_finish: bool = False) -> int:
    """Allocate a sync id, waiting if only the IdentQuery reserves remain."""
    sync_idents = _get_sync_idents(
        lamlet, 1, allow_last=allow_last, needs_finish=needs_finish)
    if sync_idents is not None:
        return sync_idents[0]

    lamlet.monitor.record_resource_exhausted(
        ResourceType.SYNC_IDENT, None, None)
    wait_start = lamlet.clock.cycle
    last_log_cycle = wait_start
    while sync_idents is None:
        await lamlet.clock.next_cycle
        if lamlet.clock.cycle - last_log_cycle >= 1000:
            logger.warning(
                f'{lamlet.clock.cycle}: wait_for_sync_ident still waiting '
                f'allow_last={allow_last} needs_finish={needs_finish} '
                f'allocated={sorted(lamlet.sync_ident_allocator.allocated)} '
                f'needs_finish={sorted(lamlet.sync_ident_allocator.needs_finish)} '
                f'free={_free_sync_idents(lamlet)} '
                f'wait_cycles={lamlet.clock.cycle - wait_start}')
            last_log_cycle = lamlet.clock.cycle
        sync_idents = _get_sync_idents(
            lamlet, 1, allow_last=allow_last, needs_finish=needs_finish)
    lamlet.monitor.record_resource_available(
        ResourceType.SYNC_IDENT, None, None)
    return sync_idents[0]


async def wait_for_sync_idents(
        lamlet: 'Oamlet', n_idents: int, *, allow_last: bool = False,
        needs_finish: bool | list[bool] = False) -> list[int]:
    """Allocate multiple sync ids without consuming the IdentQuery reserves."""
    assert n_idents >= 1
    sync_idents = _get_sync_idents(
        lamlet, n_idents, allow_last=allow_last,
        needs_finish=needs_finish)
    if sync_idents is not None:
        return sync_idents

    lamlet.monitor.record_resource_exhausted(
        ResourceType.SYNC_IDENT, None, None)
    wait_start = lamlet.clock.cycle
    last_log_cycle = wait_start
    while sync_idents is None:
        await lamlet.clock.next_cycle
        if lamlet.clock.cycle - last_log_cycle >= 1000:
            logger.warning(
                f'{lamlet.clock.cycle}: wait_for_sync_idents still waiting '
                f'n_idents={n_idents} allow_last={allow_last} '
                f'needs_finish={needs_finish} '
                f'allocated={sorted(lamlet.sync_ident_allocator.allocated)} '
                f'needs_finish={sorted(lamlet.sync_ident_allocator.needs_finish)} '
                f'free={_free_sync_idents(lamlet)} '
                f'wait_cycles={lamlet.clock.cycle - wait_start}')
            last_log_cycle = lamlet.clock.cycle
        sync_idents = _get_sync_idents(
            lamlet, n_idents, allow_last=allow_last,
            needs_finish=needs_finish)
    lamlet.monitor.record_resource_available(
        ResourceType.SYNC_IDENT, None, None)
    return sync_idents


def reclaim_sync_idents(
        lamlet: 'Oamlet', active_mask: int,
        allocated_snapshot: set[int]) -> None:
    reclaimed = lamlet.sync_ident_allocator.observe_active_mask(
        active_mask, allocated_snapshot)
    for sync_ident in reclaimed:
        try:
            lamlet._allocated_ident_query_syncs.remove(sync_ident)
        except ValueError:
            pass
    if reclaimed:
        logger.debug(
            f'{lamlet.clock.cycle}: lamlet: reclaimed sync idents '
            f'{sorted(reclaimed)} active_mask=0x{active_mask:x} '
            f'snapshot={sorted(allocated_snapshot)}')


def get_oldest_active_instr_ident_distance(lamlet: 'Oamlet', baseline: int) -> int | None:
    """Return the distance to the oldest active instr_ident from baseline.

    Distance is computed as (ident - baseline) % max_response_tags, so older idents
    (further back in the circular space) have smaller distances.

    Only considers waiting items that have been dispatched to kamlets.

    Returns None if no dispatched waiting items have an instr_ident set (all free).
    """
    max_tags = lamlet.params.max_response_tags
    # Only include regular idents (< max_response_tags), not special idents like IdentQuery or barriers
    idents = [item.instr_ident for item in lamlet.waiting_items
              if item.instr_ident is not None and item.dispatched
              and item.instr_ident < max_tags]
    if not idents:
        return None  # All free
    distances = []
    for ident in idents:
        d = (ident - baseline) % max_tags
        if d == 0:
            d = max_tags  # ident at baseline is newest, not oldest
        distances.append(d)
    min_dist = min(distances)
    if min_dist == max_tags:
        return None  # only active ident is at baseline (newest)
    min_idx = distances.index(min_dist)
    logger.debug(f'{lamlet.clock.cycle}: lamlet: get_oldest_active_instr_ident_distance '
                 f'baseline={baseline} idents={idents} distances={distances} '
                 f'min_dist={min_dist} from ident={idents[min_idx]}')
    return min_dist


def get_writeset_ident(lamlet: 'Oamlet') -> int:
    if lamlet.active_writeset_ident is not None:
        return lamlet.active_writeset_ident
    ident = lamlet.next_writeset_ident
    lamlet.next_writeset_ident += 1
    return ident


def get_available_idents(lamlet: 'Oamlet') -> int:
    """Return the number of idents available before collision.

    We subtract 1 to always leave one ident unused, avoiding the wraparound
    ambiguity where distance 0 could mean either 'at baseline' or 'wrapped around'.
    """
    max_tags = lamlet.params.max_response_tags
    if lamlet._oldest_active_ident is None:
        # No query response yet - next_instr_ident is how many we've used since start
        # This path should not be taken if we're received any IdentQuery responses.
        result = max_tags - lamlet.next_instr_ident - 1
    else:
        result = (lamlet._oldest_active_ident - lamlet.next_instr_ident) % max_tags - 1
    assert result >= 0, f"available idents went negative: {result}"
    logger.debug(f'{lamlet.clock.cycle}: get_available_idents: '
                 f'oldest_active={lamlet._oldest_active_ident} '
                 f'next_instr_ident={lamlet.next_instr_ident} available={result}')
    return result


def create_ident_query(lamlet: 'Oamlet') -> IdentQuery:
    """Create an IdentQuery instruction using the next available slot."""
    n_iq = len(lamlet._iq_slots)
    slot_idx = lamlet._next_ident_query_slot
    slot = lamlet._iq_slots[slot_idx]
    assert slot is None, f"IQ slot {slot_idx} is not free"
    sync_ident = get_sync_ident(
        lamlet, allow_last=True, needs_finish=True)
    assert sync_ident is not None, "IdentQuery must have a reserved sync id available"
    free_after_alloc = _free_sync_idents(lamlet)
    must_drain_sync_ident = None
    if not free_after_alloc:
        assert lamlet._allocated_ident_query_syncs, (
            "IdentQuery used the last sync id with no older allocated "
            f"IdentQuery sync to drain: sync_ident={sync_ident} "
            f"allocated={sorted(lamlet.sync_ident_allocator.allocated)} "
            f"needs_finish={sorted(lamlet.sync_ident_allocator.needs_finish)} | "
            f"{_format_iq_ring_state(lamlet)}")
        must_drain_sync_ident = lamlet._allocated_ident_query_syncs[0]

    slot = IdentQuerySlot()
    slot.sync_ident = sync_ident
    slot.allocated_sync_idents_snapshot = lamlet.sync_ident_allocator.snapshot()
    lamlet._iq_slots[slot_idx] = slot
    lamlet._submitted_ident_query_slots.append(slot_idx)
    lamlet._allocated_ident_query_syncs.append(sync_ident)
    ident = lamlet._iq_idents[slot_idx]
    if lamlet._oldest_active_ident_query_slot is None:
        lamlet._oldest_active_ident_query_slot = slot_idx

    # Find baseline from oldest regular ident in instruction buffer,
    # skipping special idents.
    max_tags = lamlet.params.max_response_tags
    oldest_regular_ident = None
    for instr, _ in lamlet.instruction_buffer:
        if instr.instr_ident is not None and instr.instr_ident < max_tags:
            oldest_regular_ident = instr.instr_ident
            break
    if oldest_regular_ident is not None:
        slot.baseline = (oldest_regular_ident - 1) % max_tags
    else:
        slot.baseline = (lamlet.next_instr_ident - 1) % max_tags
    # Capture lamlet's waiting items distance now, not when response arrives
    slot.lamlet_dist = get_oldest_active_instr_ident_distance(
        lamlet, slot.baseline)

    kinstr = IdentQuery(
        instr_ident=ident,
        sync_ident=sync_ident,
        must_drain_valid=must_drain_sync_ident is not None,
        must_drain_sync_ident=0 if must_drain_sync_ident is None else must_drain_sync_ident,
        baseline=slot.baseline,
        previous_instr_ident=lamlet._last_sent_instr_ident,
    )
    kinstr_span_id = lamlet.monitor.record_kinstr_created(
        kinstr, lamlet._ident_query_span_id)
    slot.span_id = kinstr_span_id
    slot.consumed = False

    # Create sync tracking spans
    lamlet.monitor.create_sync_spans(sync_ident, kinstr_span_id, lamlet.params)
    distance = (lamlet.params.max_response_tags
                if slot.lamlet_dist is None else slot.lamlet_dist)
    lamlet.synchronizer.local_event(
        sync_ident, value=distance, op=SyncAggOp.MIN_WITH_ACTIVE_MASK,
        width=lamlet.params.sync_value_width,
        must_drain_sync_ident=must_drain_sync_ident)

    # Snapshot tokens used since last query into this slot
    slot.tokens = list(lamlet._tokens_used_since_query)
    for i in range(lamlet.params.k_in_l):
        lamlet._tokens_used_since_query[i] = 0

    lamlet.monitor.add_event(kinstr_span_id, "tokens_to_refund",
                              tokens=list(slot.tokens))

    lamlet._last_ident_query_cycle = lamlet.clock.cycle

    # Advance newest pointer
    lamlet._next_ident_query_slot = (lamlet._next_ident_query_slot + 1) % n_iq

    lamlet.monitor.record_ident_query_sent()
    logger.debug(f'{lamlet.clock.cycle}: lamlet: created ident query '
                 f'ident={ident} sync_ident={sync_ident} baseline={slot.baseline} '
                 f'previous_instr_ident={lamlet._last_sent_instr_ident} '
                 f'lamlet_dist={slot.lamlet_dist} '
                 f'must_drain={must_drain_sync_ident} '
                 f'tokens={slot.tokens}')
    logger.debug(f'{lamlet.clock.cycle}: lamlet: IQ ring after create: '
                 f'{_format_iq_ring_state(lamlet)}')
    return kinstr


def record_ident_query_dispatch(lamlet: 'Oamlet', kinstr: IdentQuery) -> None:
    slot_idx = lamlet._iq_idents.index(kinstr.instr_ident)
    slot = lamlet._iq_slots[slot_idx]
    assert slot is not None
    slot.dispatch_cycle = lamlet.clock.cycle


def consume_ident_query_response(
        lamlet: 'Oamlet', slot_idx: int, packed_value: int) -> None:
    """Apply one IdentQuery response.

    Updates normal instr-ident flow control from the min distance, reclaims
    sync ids using the active mask, returns instruction-buffer tokens, and
    frees the IdentQuery slot.
    """
    ident = lamlet._iq_idents[slot_idx]
    slot = lamlet._iq_slots[slot_idx]

    lamlet.monitor.record_ident_query_response()

    max_tags = lamlet.params.max_response_tags
    low_dist, active_mask = unpack_min_with_active_mask(lamlet.params, packed_value)
    logger.debug(
        f'{lamlet.clock.cycle}: lamlet: consume_ident_query_response '
        f'ENTER slot_idx={slot_idx} ident={ident} sync_ident={slot.sync_ident} '
        f'packed=0x{packed_value:x} low={low_dist} active_mask=0x{active_mask:x} | '
        f'{_format_iq_ring_state(lamlet)}')

    baseline = slot.baseline

    if low_dist == max_tags:
        # All idents free - oldest active is the baseline itself
        lamlet._oldest_active_ident = baseline
    else:
        assert 1 <= low_dist < max_tags, (
            f"regular-ident distance {low_dist} out of range "
            f"[1, {max_tags})")
        lamlet._oldest_active_ident = (baseline + low_dist) % max_tags

    # Only check kinstrs dispatched before the query
    query_dispatch_cycle = slot.dispatch_cycle
    monitor_oldest = lamlet.monitor.get_oldest_active_instr_ident()
    if monitor_oldest is None:
        monitor_distance = max_tags
    else:
        oldest_dispatch_cycle = \
            lamlet.monitor.get_kinstr_dispatch_cycle(monitor_oldest)
        if (oldest_dispatch_cycle is None
                or oldest_dispatch_cycle >= query_dispatch_cycle):
            monitor_distance = max_tags
        else:
            monitor_distance = (monitor_oldest - baseline) % max_tags
            if monitor_distance == 0:
                monitor_distance = max_tags
    effective_low = low_dist
    if monitor_distance < effective_low:
        span_id = lamlet.monitor.get_kinstr_span_id(monitor_oldest)
        dump = lamlet.monitor.format_span_tree(span_id)
        iq_span_id = lamlet.monitor.get_kinstr_span_id(ident) or slot.span_id
        iq_dump = lamlet.monitor.format_span_tree(iq_span_id)
        assert False, \
            f"Monitor older than lamlet: " \
            f"monitor={monitor_oldest} " \
            f"(dist={monitor_distance}) " \
            f"lamlet={lamlet._oldest_active_ident} " \
            f"(dist={effective_low})\n\n" \
            f"Oldest kinstr:\n{dump}\n\nIdentQuery:\n{iq_dump}"

    # Return instruction queue tokens captured by this slot.
    # The slot's tokens include the IdentQuery broadcast token itself
    # (counted via _use_token when sent).
    for k_index in range(lamlet.params.k_in_l):
        assert slot.tokens[k_index] >= 1, \
            f"Expected at least 1 token returned for k_index={k_index}, " \
            f"got {slot.tokens[k_index]}"
    tokens_returned = any(slot.tokens[k] > 1
                          for k in range(lamlet.params.k_in_l))
    for k_index in range(lamlet.params.k_in_l):
        lamlet._available_tokens[k_index] += slot.tokens[k_index]
    if tokens_returned:
        lamlet.monitor.record_resource_available(
            ResourceType.INSTR_BUFFER_TOKENS, None, None)
    reclaim_sync_idents(
        lamlet, active_mask, slot.allocated_sync_idents_snapshot)

    logger.debug(f'{lamlet.clock.cycle}: lamlet: ident query response '
                 f'ident={ident} sync_ident={slot.sync_ident} '
                 f'baseline={baseline} '
                 f'low={low_dist} active_mask=0x{active_mask:x} '
                 f'oldest_active={lamlet._oldest_active_ident} '
                 f'tokens_returned={slot.tokens} '
                 f'available_tokens={lamlet._available_tokens}')
    free_ident_query_slot(lamlet, slot_idx)


def free_ident_query_slot(lamlet: 'Oamlet', slot_idx: int) -> None:
    """Reset a consumed IQ slot.

    Called after the query response is consumed. The query's sync id is
    reclaimed through the active-mask allocator path, not by freeing this
    instruction slot. The IdentQuery kinstr span is fire-and-forget and
    completes when its monitor children complete.
    """
    slot = lamlet._iq_slots[slot_idx]
    logger.debug(
        f'{lamlet.clock.cycle}: lamlet: free_ident_query_slot '
        f'slot_idx={slot_idx} ident={lamlet._iq_idents[slot_idx]} '
        f'consumed={slot.consumed} span_id={slot.span_id}')
    assert slot.consumed, (
        f"IQ slot {slot_idx} freed without its response being consumed")
    assert slot.span_id is not None
    lamlet._iq_slots[slot_idx] = None
    if lamlet._oldest_active_ident_query_slot == slot_idx:
        lamlet._oldest_active_ident_query_slot = None


def poll_ident_query_response(lamlet: 'Oamlet') -> None:
    """Consume any IQ slot responses whose syncs have completed.

    Consumes at most one completed response per cycle. Responses are consumed
    in submit order because each response advances circular instr-ident flow
    control relative to the baseline captured when that IdentQuery was created.
    """
    if not lamlet._submitted_ident_query_slots:
        return
    slot_idx = lamlet._submitted_ident_query_slots[0]
    slot = lamlet._iq_slots[slot_idx]
    assert slot is not None, (
        f"IQ submit FIFO pointed at free slot {slot_idx}: "
        f"{_format_iq_ring_state(lamlet)}")
    assert not slot.consumed
    ident = lamlet._iq_idents[slot_idx]
    sync_ident = slot.sync_ident
    if lamlet.synchronizer.is_complete(sync_ident):
        packed = lamlet.synchronizer.get_aggregated_value(sync_ident)
        assert packed is not None, (
            f"IQ slot {slot_idx} ident={ident} sync_ident={sync_ident} is_complete but "
            f"aggregated value is None")
        lamlet.sync_ident_allocator.finish(sync_ident)
        logger.debug(
            f'{lamlet.clock.cycle}: lamlet: poll found complete '
            f'slot_idx={slot_idx} ident={ident} sync_ident={sync_ident} '
            f'packed=0x{packed:x}')
        slot.consumed = True
        consume_ident_query_response(lamlet, slot_idx, packed)
        popped = lamlet._submitted_ident_query_slots.popleft()
        assert popped == slot_idx
        lamlet._oldest_active_ident_query_slot = (
            lamlet._submitted_ident_query_slots[0]
            if lamlet._submitted_ident_query_slots else None)
        return

    # This monitor is expected to consume a completed IdentQuery quickly.
    # If the FIFO head sits incomplete for a while, log enough state to tell
    # whether the head really is incomplete or whether polling is looking at
    # the wrong slot.
    wait_start = (
        slot.dispatch_cycle
        if slot.dispatch_cycle is not None
        else lamlet._last_ident_query_cycle)
    wait_cycles = (
        None if wait_start is None else lamlet.clock.cycle - wait_start)
    should_log = (
        wait_cycles is not None
        and wait_cycles >= 100
        and (slot.last_wait_log_cycle is None
             or lamlet.clock.cycle - slot.last_wait_log_cycle >= 100))
    if should_log:
        slot.last_wait_log_cycle = lamlet.clock.cycle
        completed_submitted = []
        for pending_slot_idx in lamlet._submitted_ident_query_slots:
            pending_slot = lamlet._iq_slots[pending_slot_idx]
            if (pending_slot is not None
                    and lamlet.synchronizer.is_complete(pending_slot.sync_ident)):
                completed_submitted.append(
                    (pending_slot_idx, lamlet._iq_idents[pending_slot_idx],
                     pending_slot.sync_ident))
        sync_state = lamlet.synchronizer._sync_states.get(sync_ident)
        logger.debug(
            f'{lamlet.clock.cycle}: lamlet: waiting for IdentQuery head '
            f'slot={slot_idx} ident={ident} sync_ident={sync_ident} '
            f'wait_cycles={wait_cycles} '
            f'sync_exists={sync_state is not None} '
            f'local_seen={False if sync_state is None else sync_state.local_seen} '
            f'completed={False if sync_state is None else sync_state.completed} '
            f'completed_submitted={completed_submitted} '
            f'allocated_syncs={sorted(lamlet.sync_ident_allocator.allocated)} '
            f'needs_finish_syncs={sorted(lamlet.sync_ident_allocator.needs_finish)} '
            f'free_syncs={lamlet.sync_ident_allocator.free_idents()} | '
            f'{_format_iq_ring_state(lamlet)}')


def should_send_ident_query(lamlet: 'Oamlet') -> bool:
    """Check if we should send an ident query (for tokens or idents).

    Returns True if a slot is available and either enough tokens have
    accumulated since the last query, or the ident pool is running low.
    With N slots we send every 2*depth/N instructions, spacing
    queries evenly across the token budget.

    The ident-pressure path is load-bearing: without it, a caller
    blocked in get_instr_ident would stall the instruction dispatch
    loop, which would stop accumulating tokens, which would stop
    issuing IdentQueries — livelocking the ident recycler. It is
    rate-limited by min_cycles_since_last so we do not flood the
    network with back-to-back queries while a response is in flight.
    """
    n_iq = len(lamlet._iq_slots)
    token_threshold = (
        2 * lamlet.params.instruction_queue_length // n_iq)
    want_to_send = any(t >= token_threshold
                       for t in lamlet._tokens_used_since_query)
    ident_threshold = lamlet.params.max_response_tags // n_iq
    min_cycles_since_last = lamlet.params.ident_query_min_cycles
    cycles_since_last = (
        lamlet.clock.cycle - lamlet._last_ident_query_cycle
        if lamlet._last_ident_query_cycle is not None
        else min_cycles_since_last)
    if (get_available_idents(lamlet) < ident_threshold
            and cycles_since_last >= min_cycles_since_last):
        want_to_send = True
    # Normal indexed load/store chunks allocate two sync ids at once while
    # preserving two ids for IdentQuery. If only three ids are free, those
    # chunks are already blocked, so start a reclaim query before that point.
    if (len(_free_sync_idents(lamlet)) <= 3
            and cycles_since_last >= min_cycles_since_last):
        want_to_send = True
    if (any(t <= 1 for t in lamlet._available_tokens)
            and any(t > 0 for t in lamlet._tokens_used_since_query)
            and cycles_since_last >= min_cycles_since_last):
        # Regular instructions require one spare token beyond the reserved
        # IdentQuery token. If we are down to the reserve, send a query to
        # refund used tokens and make regular dispatch possible again.
        want_to_send = True
    slot_busy = lamlet._iq_slots[lamlet._next_ident_query_slot] is not None
    if want_to_send and slot_busy:
        lamlet.monitor.record_resource_exhausted(
            ResourceType.IDENT_QUERY_SLOT, None, None)
        return False
    lamlet.monitor.record_resource_available(
        ResourceType.IDENT_QUERY_SLOT, None, None)
    if slot_busy:
        return False
    if not want_to_send:
        return False
    if not _free_sync_idents(lamlet):
        lamlet.monitor.record_resource_exhausted(
            ResourceType.SYNC_IDENT, None, None)
        return False
    lamlet.monitor.record_resource_available(
        ResourceType.SYNC_IDENT, None, None)
    # Broadcast requires >0 tokens on every kamlet. If some kamlet's
    # queue is drained, we must wait for an in-flight IQ response to
    # refund tokens before we can send another query.
    if not lamlet._have_tokens(None, is_ident_query=True):
        return False
    return True


async def get_instr_ident(lamlet: 'Oamlet', n_idents: int = 1) -> int:
    """Allocate n_idents consecutive instruction identifiers.

    Waits if not enough idents are available.
    """
    assert n_idents >= 1
    max_tags = lamlet.params.max_response_tags

    if get_available_idents(lamlet) < n_idents:
        wait_start = lamlet.clock.cycle
        last_log_cycle = wait_start
        lamlet.monitor.record_resource_exhausted(ResourceType.INSTR_IDENT, None, None)
        while get_available_idents(lamlet) < n_idents:
            await lamlet.clock.next_cycle
            if lamlet.clock.cycle - last_log_cycle >= 1000:
                logger.warning(
                    f'{lamlet.clock.cycle}: get_instr_ident still waiting '
                    f'n_idents={n_idents} wait_cycles={lamlet.clock.cycle - wait_start} '
                    f'available={get_available_idents(lamlet)} '
                    f'next_instr_ident={lamlet.next_instr_ident} '
                    f'oldest_active_ident={lamlet._oldest_active_ident} '
                    f'submitted_iq_slots={list(lamlet._submitted_ident_query_slots)} '
                    f'allocated_syncs={sorted(lamlet.sync_ident_allocator.allocated)} '
                    f'free_syncs={lamlet.sync_ident_allocator.free_idents()} | '
                    f'{_format_iq_ring_state(lamlet)}')
                last_log_cycle = lamlet.clock.cycle
        lamlet.monitor.record_resource_available(ResourceType.INSTR_IDENT, None, None)

    ident = lamlet.next_instr_ident
    if lamlet._oldest_active_ident is None:
        lamlet._oldest_active_ident = ident
    lamlet.next_instr_ident = (lamlet.next_instr_ident + n_idents) % max_tags
    return ident
