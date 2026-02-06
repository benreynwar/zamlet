"""
Instruction identifier flow control for the lamlet.

This module handles allocation and tracking of instruction identifiers (idents)
which are used to match responses to requests in the distributed system.
"""

import logging
from enum import Enum
from typing import TYPE_CHECKING

from zamlet.transactions.ident_query import IdentQuery
from zamlet.monitor import ResourceType

if TYPE_CHECKING:
    from zamlet.lamlet.lamlet import Lamlet

logger = logging.getLogger(__name__)


class RefreshState(Enum):
    DORMANT = 0
    READY_TO_SEND = 1
    WAITING_FOR_RESPONSE = 2


def get_oldest_active_instr_ident_distance(lamlet: 'Lamlet', baseline: int) -> int | None:
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


def get_writeset_ident(lamlet: 'Lamlet') -> int:
    if lamlet.active_writeset_ident is not None:
        return lamlet.active_writeset_ident
    ident = lamlet.next_writeset_ident
    lamlet.next_writeset_ident += 1
    return ident


def get_available_idents(lamlet: 'Lamlet') -> int:
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


def create_ident_query(lamlet: 'Lamlet') -> IdentQuery:
    """Create an IdentQuery instruction and update state."""
    assert lamlet._ident_query_state == RefreshState.READY_TO_SEND

    # Find baseline from oldest regular ident in instruction buffer, skipping special idents.
    max_tags = lamlet.params.max_response_tags
    oldest_regular_ident = None
    for instr, _ in lamlet.instruction_buffer:
        if instr.instr_ident is not None and instr.instr_ident < max_tags:
            oldest_regular_ident = instr.instr_ident
            break
    if oldest_regular_ident is not None:
        lamlet._ident_query_baseline = (oldest_regular_ident - 1) % max_tags
    else:
        lamlet._ident_query_baseline = (lamlet.next_instr_ident - 1) % max_tags
    # Capture lamlet's waiting items distance now, not when response arrives
    lamlet._ident_query_lamlet_dist = get_oldest_active_instr_ident_distance(
        lamlet, lamlet._ident_query_baseline)

    kinstr = IdentQuery(
        instr_ident=lamlet._ident_query_ident,
        baseline=lamlet._ident_query_baseline,
        previous_instr_ident=lamlet._last_sent_instr_ident,
    )
    kinstr_span_id = lamlet.monitor.record_kinstr_created(kinstr, lamlet._ident_query_span_id)

    # Create sync tracking spans
    lamlet.monitor.create_sync_spans(lamlet._ident_query_ident, kinstr_span_id, lamlet.params)

    # Lamlet participates in sync network with its own distance value
    lamlet.synchronizer.local_event(lamlet._ident_query_ident, value=lamlet._ident_query_lamlet_dist)

    lamlet._ident_query_state = RefreshState.WAITING_FOR_RESPONSE
    logger.debug(f'{lamlet.clock.cycle}: lamlet: created ident query '
                 f'baseline={lamlet._ident_query_baseline} '
                 f'previous_instr_ident={lamlet._last_sent_instr_ident} '
                 f'lamlet_dist={lamlet._ident_query_lamlet_dist}')
    return kinstr


def receive_ident_query_response(lamlet: 'Lamlet', min_distance: int, query_span_id: int):
    """Process ident query response. Called from message handler.

    min_distance is the global minimum from the sync network (includes lamlet's value).
    query_span_id is passed in because the kinstr will be removed from the
    lookup table when completed.
    """
    assert lamlet._ident_query_state == RefreshState.WAITING_FOR_RESPONSE

    max_tags = lamlet.params.max_response_tags
    assert 0 <= min_distance <= max_tags

    baseline = lamlet._ident_query_baseline

    if min_distance == max_tags:
        # All idents free - oldest active is the baseline itself
        lamlet._oldest_active_ident = baseline
    else:
        lamlet._oldest_active_ident = (baseline + min_distance) % max_tags

    lamlet._ident_query_state = RefreshState.DORMANT

    # Clean up lamlet's sync state
    lamlet.synchronizer.clear_sync(lamlet._ident_query_ident)

    if lamlet.monitor.enabled:
        # Only check kinstrs dispatched before the query
        query_dispatch_cycle = lamlet.monitor.get_kinstr_dispatch_cycle(lamlet._ident_query_ident)
        monitor_oldest = lamlet.monitor.get_oldest_active_instr_ident()
        if monitor_oldest is None:
            monitor_distance = max_tags
        else:
            oldest_dispatch_cycle = lamlet.monitor.get_kinstr_dispatch_cycle(monitor_oldest)
            if oldest_dispatch_cycle is None or oldest_dispatch_cycle >= query_dispatch_cycle:
                monitor_distance = max_tags
            else:
                monitor_distance = (monitor_oldest - baseline) % max_tags
                if monitor_distance == 0:
                    monitor_distance = max_tags  # at baseline means newest, not oldest
        if monitor_distance < min_distance:
            span_id = lamlet.monitor.get_kinstr_span_id(monitor_oldest)
            dump = lamlet.monitor.format_span_tree(span_id)
            iq_span_id = lamlet.monitor.get_kinstr_span_id(lamlet._ident_query_ident)
            iq_dump = lamlet.monitor.format_span_tree(iq_span_id)
            assert False, \
                f"Monitor older than lamlet: monitor={monitor_oldest} (dist={monitor_distance}) " \
                f"lamlet={lamlet._oldest_active_ident} (dist={min_distance})\n\n" \
                f"Oldest kinstr:\n{dump}\n\nIdentQuery:\n{iq_dump}"

    # Return instruction queue tokens tracked in _tokens_in_active_query.
    # This includes the IdentQuery itself (counted via _use_token when sent).
    # Check > 1 because the IdentQuery token is reserved and can't be used by regular instructions.
    for k_index in range(lamlet.params.k_in_l):
        assert lamlet._tokens_in_active_query[k_index] >= 1, \
            f"Expected at least 1 token returned for k_index={k_index}, " \
            f"got {lamlet._tokens_in_active_query[k_index]}"
    tokens_returned = any(lamlet._tokens_in_active_query[k] > 1
                          for k in range(lamlet.params.k_in_l))
    for k_index in range(lamlet.params.k_in_l):
        lamlet._available_tokens[k_index] += lamlet._tokens_in_active_query[k_index]
    if tokens_returned:
        lamlet.monitor.record_resource_available(ResourceType.INSTR_BUFFER_TOKENS, None, None)

    logger.debug(f'{lamlet.clock.cycle}: lamlet: ident query response '
                 f'baseline={baseline} min_distance={min_distance} '
                 f'oldest_active={lamlet._oldest_active_ident} '
                 f'tokens_returned={lamlet._tokens_in_active_query} '
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


async def monitor_ident_query(lamlet: 'Lamlet'):
    """Coroutine to manage the ident query state machine.

    Sets state to READY_TO_SEND when ident space is running low.
    The actual sending is done by monitor_instruction_buffer.
    """
    max_tags = lamlet.params.max_response_tags

    while True:
        if lamlet._ident_query_state == RefreshState.DORMANT:
            # Transition to READY_TO_SEND when we have less than half idents free
            if get_available_idents(lamlet) < max_tags // 2:
                lamlet._ident_query_state = RefreshState.READY_TO_SEND

        await lamlet.clock.next_cycle


async def get_instr_ident(lamlet: 'Lamlet', n_idents: int = 1) -> int:
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
