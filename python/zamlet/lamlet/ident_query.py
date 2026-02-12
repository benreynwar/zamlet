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

if TYPE_CHECKING:
    from zamlet.oamlet.oamlet import Oamlet

logger = logging.getLogger(__name__)


@dataclass
class IdentQuerySlot:
    """State for one in-flight ident query."""
    baseline: int = 0
    lamlet_dist: int | None = None
    tokens: list[int] = field(default_factory=list)


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
    assert not lamlet._iq_full

    n_iq = lamlet.params.n_ident_query_slots
    slot = lamlet._iq_slots[lamlet._iq_newest]
    ident = lamlet._iq_idents[lamlet._iq_newest]

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

    # Create sync tracking spans
    lamlet.monitor.create_sync_spans(ident, kinstr_span_id, lamlet.params)

    # Lamlet participates in sync network with its own distance value
    lamlet.synchronizer.local_event(ident, value=slot.lamlet_dist)

    # Snapshot tokens used since last query into this slot
    slot.tokens = list(lamlet._tokens_used_since_query)
    for i in range(lamlet.params.k_in_l):
        lamlet._tokens_used_since_query[i] = 0

    # Advance newest pointer
    lamlet._iq_newest = (lamlet._iq_newest + 1) % n_iq
    lamlet._iq_full = (lamlet._iq_newest == lamlet._iq_oldest)

    lamlet.monitor.record_ident_query_sent()
    logger.debug(f'{lamlet.clock.cycle}: lamlet: created ident query '
                 f'ident={ident} baseline={slot.baseline} '
                 f'previous_instr_ident={lamlet._last_sent_instr_ident} '
                 f'lamlet_dist={slot.lamlet_dist} '
                 f'tokens={slot.tokens}')
    return kinstr


def receive_ident_query_response(
        lamlet: 'Oamlet', response_ident: int,
        min_distance: int, query_span_id: int):
    """Process ident query response. Called from message handler.

    response_ident identifies which query this response is for (must match
    the oldest in-flight slot).
    min_distance is the global minimum from the sync network (includes
    lamlet's value).
    query_span_id is passed in because the kinstr will be removed from the
    lookup table when completed.
    """
    n_iq = lamlet.params.n_ident_query_slots
    # Must have at least one in-flight query
    assert lamlet._iq_oldest != lamlet._iq_newest or lamlet._iq_full

    ident = lamlet._iq_idents[lamlet._iq_oldest]
    assert response_ident == ident, \
        f"Expected response for ident {ident}, got {response_ident}"
    slot = lamlet._iq_slots[lamlet._iq_oldest]

    lamlet.monitor.record_ident_query_response()

    max_tags = lamlet.params.max_response_tags
    assert 0 <= min_distance <= max_tags

    baseline = slot.baseline

    if min_distance == max_tags:
        # All idents free - oldest active is the baseline itself
        lamlet._oldest_active_ident = baseline
    else:
        lamlet._oldest_active_ident = (baseline + min_distance) % max_tags

    # Clean up lamlet's sync state
    lamlet.synchronizer.clear_sync(ident)

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
        if monitor_distance < min_distance:
            span_id = lamlet.monitor.get_kinstr_span_id(monitor_oldest)
            dump = lamlet.monitor.format_span_tree(span_id)
            iq_span_id = lamlet.monitor.get_kinstr_span_id(ident)
            iq_dump = lamlet.monitor.format_span_tree(iq_span_id)
            assert False, \
                f"Monitor older than lamlet: " \
                f"monitor={monitor_oldest} " \
                f"(dist={monitor_distance}) " \
                f"lamlet={lamlet._oldest_active_ident} " \
                f"(dist={min_distance})\n\n" \
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

    # Advance oldest pointer
    lamlet._iq_oldest = (lamlet._iq_oldest + 1) % n_iq
    lamlet._iq_full = False

    logger.debug(f'{lamlet.clock.cycle}: lamlet: ident query response '
                 f'ident={ident} baseline={baseline} '
                 f'min_distance={min_distance} '
                 f'oldest_active={lamlet._oldest_active_ident} '
                 f'tokens_returned={slot.tokens} '
                 f'available_tokens={lamlet._available_tokens}')

    # Complete the IdentQuery kinstr span and its kinstr_exec children.
    # IdentQuery is special - when the response arrives, we force-complete all
    # kinstr_exec spans since they may still have pending MESSAGE children.
    kinstr_span = lamlet.monitor.get_span(query_span_id)
    for child_ref in kinstr_span.children:
        child_span = lamlet.monitor.get_span(child_ref.span_id)
        if not child_span.is_complete():
            lamlet.monitor.complete_span(child_ref.span_id, skip_children_check=True)
    lamlet.monitor.complete_span(query_span_id)


def should_send_ident_query(lamlet: 'Oamlet') -> bool:
    """Check if we should send an ident query (for tokens or idents).

    Returns True if a slot is available and enough tokens have
    accumulated since the last query to justify sending another.
    With N slots we send every 2*depth/N instructions, spacing
    queries evenly across the token budget.
    """
    if lamlet._iq_full:
        return False
    n_iq = lamlet.params.n_ident_query_slots
    # Token threshold: send after accumulating this many tokens
    token_threshold = (
        2 * lamlet.params.instruction_queue_length // n_iq)
    return any(t >= token_threshold
               for t in lamlet._tokens_used_since_query)


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
