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
    SyncAggOp, MIN_PAIR_TOTAL_WIDTH, pack_min_pair, unpack_min_pair,
)

if TYPE_CHECKING:
    from zamlet.oamlet.oamlet import Oamlet

logger = logging.getLogger(__name__)


@dataclass
class IdentQuerySlot:
    """State for one in-flight ident query.

    Lifecycle: allocated (in create_ident_query) → consumed (poll sees
    sync complete, processes MIN_PAIR bookkeeping) → freed (a later
    query's MIN_PAIR.high confirms drain, completes kinstr, slot is
    available for reuse).
    """
    baseline: int = 0
    lamlet_dist: int | None = None
    tokens: list[int] = field(default_factory=list)
    # Span id of the IdentQuery kinstr. Captured at create_ident_query
    # time and completed when the slot is freed.
    span_id: int | None = None
    # True iff the poll has processed this slot's MIN_PAIR response.
    # Gates the in-order poll walk (we never consume slot X's response
    # before older unconsumed slots have been processed) and guards the
    # advance loop's invariant that every slot freed is one we
    # consumed.
    consumed: bool = False


def _format_iq_ring_state(lamlet: 'Oamlet') -> str:
    """Render the lamlet's IQ ring for debug logs."""
    n_iq = lamlet.params.n_ident_query_slots
    parts = [
        f"oldest={lamlet._oldest_active_ident_query_slot}",
        f"next_unconsumed={lamlet._next_unconsumed_ident_query_slot}",
        f"newest={lamlet._next_ident_query_slot}",
    ]
    for i in range(n_iq):
        slot = lamlet._iq_slots[i]
        if slot is None:
            parts.append(f"[{i}] ident={lamlet._iq_idents[i]} free")
            continue
        parts.append(
            f"[{i}] ident={lamlet._iq_idents[i]} "
            f"consumed={slot.consumed} span={slot.span_id} "
            f"baseline={slot.baseline}")
    return " | ".join(parts)


def get_oldest_pending_iq_slot_distance(
        lamlet: 'Oamlet', query_ident: int) -> int:
    """Lamlet-side analogue of Kamlet.get_oldest_pending_iq_slot_distance.

    Distance to the oldest IQ slot with pending sync state at the lamlet's
    own synchronizer, relative to the query ident. See the kamlet-side
    docstring for the distance convention.
    """
    max_tags = lamlet.params.max_response_tags
    n_iq = lamlet.params.n_ident_query_slots
    distances: list[int] = []
    for sync_ident in lamlet.synchronizer._sync_states:
        if sync_ident < max_tags or sync_ident >= max_tags + n_iq:
            continue
        d = (sync_ident - query_ident) % n_iq
        if d == 0:
            continue
        distances.append(d)
    if not distances:
        return n_iq
    return min(distances)


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
    n_iq = lamlet.params.n_ident_query_slots
    slot_idx = lamlet._next_ident_query_slot
    slot = lamlet._iq_slots[slot_idx]
    assert slot is None, f"IQ slot {slot_idx} is not free"
    slot = IdentQuerySlot()
    lamlet._iq_slots[slot_idx] = slot
    ident = lamlet._iq_idents[slot_idx]
    if lamlet._oldest_active_ident_query_slot is None:
        lamlet._oldest_active_ident_query_slot = slot_idx
    if lamlet._iq_slots[lamlet._next_unconsumed_ident_query_slot] is None:
        lamlet._next_unconsumed_ident_query_slot = slot_idx

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
        baseline=slot.baseline,
        previous_instr_ident=lamlet._last_sent_instr_ident,
    )
    kinstr_span_id = lamlet.monitor.record_kinstr_created(
        kinstr, lamlet._ident_query_span_id)
    slot.span_id = kinstr_span_id
    slot.consumed = False

    # Create sync tracking spans
    lamlet.monitor.create_sync_spans(ident, kinstr_span_id, lamlet.params)
    logger.info(
        f'{lamlet.clock.cycle}: lamlet: IQ slot={lamlet._next_ident_query_slot} '
        f'created sync spans for ident={ident} kinstr_span={kinstr_span_id}')

    # Lamlet participates in sync network with a packed MIN_PAIR value:
    # low = oldest-active-instr_ident distance (same as before), high =
    # distance to the oldest IQ slot the lamlet still holds state for.
    # The aggregated response's high field answers "is any participant
    # still holding state for an older IQ slot?" — the precondition for
    # reusing that slot's sync_ident.
    lamlet_iq_slot_dist = get_oldest_pending_iq_slot_distance(lamlet, ident)
    packed = pack_min_pair(slot.lamlet_dist, lamlet_iq_slot_dist)
    lamlet.synchronizer.local_event(
        ident, value=packed, op=SyncAggOp.MIN_PAIR,
        width=MIN_PAIR_TOTAL_WIDTH)

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
                 f'ident={ident} baseline={slot.baseline} '
                 f'previous_instr_ident={lamlet._last_sent_instr_ident} '
                 f'lamlet_dist={slot.lamlet_dist} '
                 f'iq_slot_dist={lamlet_iq_slot_dist} '
                 f'tokens={slot.tokens}')
    logger.debug(f'{lamlet.clock.cycle}: lamlet: IQ ring after create: '
                 f'{_format_iq_ring_state(lamlet)}')
    return kinstr


def consume_ident_query_response(
        lamlet: 'Oamlet', slot_idx: int, packed_min: int) -> None:
    """Apply the MIN_PAIR bookkeeping for one IQ slot's completed sync.

    Updates _oldest_active_ident from the low field, returns the slot's
    tokens, and advances _oldest_active_ident_query_slot past any slots the high field
    confirms drained. Does NOT complete slot_idx's own kinstr span —
    slot_idx is freed (and its kinstr completed) only when a later
    query's MIN_PAIR.high advances _oldest_active_ident_query_slot past it.
    """
    n_iq = lamlet.params.n_ident_query_slots
    ident = lamlet._iq_idents[slot_idx]
    slot = lamlet._iq_slots[slot_idx]

    lamlet.monitor.record_ident_query_response()

    max_tags = lamlet.params.max_response_tags
    low_dist, high_dist = unpack_min_pair(packed_min)
    logger.debug(
        f'{lamlet.clock.cycle}: lamlet: consume_ident_query_response '
        f'ENTER slot_idx={slot_idx} ident={ident} packed=0x{packed_min:x} '
        f'low={low_dist} high={high_dist} | '
        f'{_format_iq_ring_state(lamlet)}')

    baseline = slot.baseline

    if low_dist is None:
        # All idents free - oldest active is the baseline itself
        lamlet._oldest_active_ident = baseline
    else:
        assert 1 <= low_dist < max_tags, (
            f"regular-ident distance {low_dist} out of range "
            f"[1, {max_tags})")
        lamlet._oldest_active_ident = (baseline + low_dist) % max_tags

    if lamlet.monitor.enabled:
        # Only check kinstrs dispatched before the query
        query_dispatch_cycle = lamlet.monitor.get_kinstr_dispatch_cycle(
            ident)
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
        effective_low = max_tags if low_dist is None else low_dist
        if monitor_distance < effective_low:
            span_id = lamlet.monitor.get_kinstr_span_id(monitor_oldest)
            dump = lamlet.monitor.format_span_tree(span_id)
            iq_span_id = lamlet.monitor.get_kinstr_span_id(ident)
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

    logger.debug(f'{lamlet.clock.cycle}: lamlet: ident query response '
                 f'ident={ident} baseline={baseline} '
                 f'low={low_dist} high={high_dist} '
                 f'oldest_active={lamlet._oldest_active_ident} '
                 f'tokens_returned={slot.tokens} '
                 f'available_tokens={lamlet._available_tokens}')

    # Advance _oldest_active_ident_query_slot past slots the high field confirms drained.
    # high_dist is the distance from slot_idx to the oldest pending IQ
    # slot across all participants' local_event times; slots strictly
    # between _oldest_active_ident_query_slot and that oldest-pending are drained everywhere.
    # When no participant has any other slot pending, high_dist is the
    # absent sentinel (= n_iq when it divides 2**MIN_PAIR_HIGH_WIDTH),
    # and (slot_idx + high_dist) % n_iq = slot_idx — so _oldest_active_ident_query_slot can
    # advance all the way to slot_idx (but not past; slot_idx is freed
    # only by a later query).
    oldest_pending_slot = (slot_idx + high_dist) % n_iq
    logger.debug(
        f'{lamlet.clock.cycle}: lamlet: advance loop start '
        f'slot_idx={slot_idx} oldest_pending_slot={oldest_pending_slot} '
        f'_oldest_active_ident_query_slot={lamlet._oldest_active_ident_query_slot} '
        f'_next_ident_query_slot={lamlet._next_ident_query_slot}')
    while lamlet._oldest_active_ident_query_slot != oldest_pending_slot:
        freed = lamlet._oldest_active_ident_query_slot
        freed_slot = lamlet._iq_slots[freed]
        logger.debug(
            f'{lamlet.clock.cycle}: lamlet: IQ reclaim slot={freed} '
            f'ident={lamlet._iq_idents[freed]} '
            f'consumed={freed_slot.consumed} span={freed_slot.span_id} '
            f'(triggered by slot_idx={slot_idx} response '
            f'high={high_dist}, oldest_pending={oldest_pending_slot})')
        free_ident_query_slot(lamlet, freed)
        lamlet._oldest_active_ident_query_slot = (lamlet._oldest_active_ident_query_slot + 1) % n_iq
    logger.debug(
        f'{lamlet.clock.cycle}: lamlet: advance loop end '
        f'_oldest_active_ident_query_slot={lamlet._oldest_active_ident_query_slot} | {_format_iq_ring_state(lamlet)}')


def free_ident_query_slot(lamlet: 'Oamlet', slot_idx: int) -> None:
    """Complete the kinstr span for a freed IQ slot and reset slot state.

    Called from the advance loop in consume_ident_query_response when
    _oldest_active_ident_query_slot advances past this slot. By that point every participant
    has drained its sync state for the slot's ident, so all child spans
    (sync_local, kinstr_exec) are already complete; no force-completion
    is needed.
    """
    slot = lamlet._iq_slots[slot_idx]
    logger.debug(
        f'{lamlet.clock.cycle}: lamlet: free_ident_query_slot '
        f'slot_idx={slot_idx} ident={lamlet._iq_idents[slot_idx]} '
        f'consumed={slot.consumed} span_id={slot.span_id}')
    assert slot.consumed, (
        f"IQ slot {slot_idx} freed without its response being consumed")
    assert slot.span_id is not None
    lamlet.monitor.complete_span(slot.span_id)
    lamlet._iq_slots[slot_idx] = None


def poll_ident_query_response(lamlet: 'Oamlet') -> None:
    """Consume any IQ slot responses whose syncs have completed.

    Walks forward from _oldest_active_ident_query_slot in allocation order. Skips slots
    already consumed (still allocated but pending free via a later
    query's MIN_PAIR.high); stops at the first unconsumed slot whose
    sync has not yet completed. This preserves in-order consumption so
    _oldest_active_ident advances monotonically and the advance loop's
    invariant (every freed slot was consumed) holds.
    """
    n_iq = lamlet.params.n_ident_query_slots

    # We're looking for the next unconsumed response.
    slot_idx = lamlet._next_unconsumed_ident_query_slot
    slot = lamlet._iq_slots[slot_idx]
    if slot is None:
        return
    assert not slot.consumed
    ident = lamlet._iq_idents[slot_idx]
    if lamlet.synchronizer.is_complete(ident):
        packed = lamlet.synchronizer.get_aggregated_value(ident)
        assert packed is not None, (
            f"IQ slot {slot_idx} ident={ident} is_complete but "
            f"aggregated value is None")
        logger.debug(
            f'{lamlet.clock.cycle}: lamlet: poll found complete '
            f'slot_idx={slot_idx} ident={ident} packed=0x{packed:x}')
        slot.consumed = True
        lamlet._next_unconsumed_ident_query_slot = (slot_idx + 1) % n_iq
        lamlet.synchronizer.clear_sync(ident)
        consume_ident_query_response(lamlet, slot_idx, packed)


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
    n_iq = lamlet.params.n_ident_query_slots
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
    slot_busy = lamlet._iq_slots[lamlet._next_ident_query_slot] is not None
    if want_to_send and slot_busy:
        lamlet.monitor.record_resource_exhausted(
            ResourceType.IDENT_QUERY_SLOT, None, None)
        return False
    lamlet.monitor.record_resource_available(
        ResourceType.IDENT_QUERY_SLOT, None, None)
    if slot_busy:
        return False
    # Broadcast requires >0 tokens on every kamlet. If some kamlet's
    # queue is drained, we must wait for an in-flight IQ response to
    # refund tokens before we can send another query.
    if not lamlet._have_tokens(None, is_ident_query=True):
        return False
    return want_to_send


async def get_instr_ident(lamlet: 'Oamlet', n_idents: int = 1) -> int:
    """Allocate n_idents consecutive instruction identifiers.

    Waits if not enough idents are available.
    """
    assert n_idents >= 1
    max_tags = lamlet.params.max_response_tags

    if get_available_idents(lamlet) < n_idents:
        lamlet.monitor.record_resource_exhausted(ResourceType.INSTR_IDENT, None, None)
        while get_available_idents(lamlet) < n_idents:
            await lamlet.clock.next_cycle
        lamlet.monitor.record_resource_available(ResourceType.INSTR_IDENT, None, None)

    ident = lamlet.next_instr_ident
    if lamlet._oldest_active_ident is None:
        lamlet._oldest_active_ident = ident
    lamlet.next_instr_ident = (lamlet.next_instr_ident + n_idents) % max_tags
    return ident
