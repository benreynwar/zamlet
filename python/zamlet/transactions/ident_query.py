"""
Ident Query

This transaction queries each kamlet for its oldest active instr_ident,
synchronizes across all kamlets to find the global minimum distance,
and sends the result back to the lamlet.

Used for flow control to prevent instr_ident collisions when wrapping.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from zamlet.waiting_item import WaitingItem
from zamlet.kamlet.kinstructions import TrackedKInstr
from zamlet.message import IdentHeader, MessageType, SendType
from zamlet.monitor import SpanType, CompletionType
from zamlet.synchronization import WaitingItemSyncState

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet


logger = logging.getLogger(__name__)


@dataclass
class IdentQuery(TrackedKInstr):
    """Query the oldest active instr_ident across all kamlets.

    Each kamlet computes the distance from baseline to its oldest active ident,
    synchronizes to find the minimum, and kamlet (0,0) sends the result to lamlet.

    Uses TrackedKInstr because the lamlet explicitly completes the kinstr when
    it receives the response. Overrides can_complete_before_children because the
    response can arrive before all kamlets have finished processing (due to sync
    timing differences).
    """
    instr_ident: int  # Used for both sync and response (set to max_response_tags)
    baseline: int     # next_instr_ident at time of query
    previous_instr_ident: int  # instr_ident of instruction ahead in queue

    @property
    def finalize_after_send(self) -> bool:
        # Don't finalize after send - the response message will be added as a child
        return False

    def create_span(self, monitor, parent_span_id: int) -> int:
        return monitor.create_span(
            span_type=SpanType.KINSTR,
            component="lamlet",
            completion_type=CompletionType.TRACKED,
            parent_span_id=parent_span_id,
            instr_type=type(self).__name__,
            instr_ident=self.instr_ident,
            baseline=self.baseline,
        )

    async def update_kamlet(self, kamlet: 'Kamlet'):
        distance = kamlet.cache_table.get_oldest_active_instr_ident_distance(self.baseline)

        logger.debug(f'{kamlet.clock.cycle}: IdentQuery: kamlet ({kamlet.min_x},{kamlet.min_y}) '
                     f'baseline={self.baseline} previous={self.previous_instr_ident} '
                     f'distance={distance}')

        # Create waiting item to track sync completion and send response
        is_origin = (kamlet.min_x == 0 and kamlet.min_y == 0)
        witem = WaitingIdentQuery(
            ident=self.instr_ident,
            is_origin=is_origin,
            baseline=self.baseline,
            previous_instr_ident=self.previous_instr_ident,
        )
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingIdentQuery')
        await kamlet.cache_table.add_witem(witem)

        # Report to synchronizer (uses min aggregation, None if no waiting items)
        kamlet.synchronizer.local_event(self.instr_ident, value=distance)


class WaitingIdentQuery(WaitingItem):
    """Waiting item for IdentQuery instruction.

    Monitors sync completion and has kamlet (0,0) send the result to lamlet.
    """

    def __init__(self, ident: int, is_origin: bool, baseline: int, previous_instr_ident: int):
        super().__init__(item=None, instr_ident=ident)
        self.is_origin = is_origin
        self.baseline = baseline
        self.previous_instr_ident = previous_instr_ident
        self.response_sent = False
        self.sync_state = WaitingItemSyncState.IN_PROGRESS
        self.sync_min_value: int | None = None

    def ready(self) -> bool:
        return self.response_sent

    async def monitor_kamlet(self, kamlet: 'Kamlet') -> None:
        if self.response_sent:
            return

        # Poll synchronizer for completion
        if self.sync_state == WaitingItemSyncState.IN_PROGRESS:
            if kamlet.synchronizer.is_complete(self.instr_ident):
                self.sync_state = WaitingItemSyncState.COMPLETE
                self.sync_min_value = kamlet.synchronizer.get_min_value(self.instr_ident)

        if self.sync_state == WaitingItemSyncState.COMPLETE:
            if self.is_origin:
                # If no kamlet had waiting items, compute fallback distance
                min_distance = self.sync_min_value
                if min_distance is None:
                    max_tags = kamlet.params.max_response_tags
                    # No active items anywhere - all idents are free
                    min_distance = max_tags

                logger.debug(f'{kamlet.clock.cycle}: IdentQuery: kamlet (0,0) '
                             f'sending response min_distance={min_distance} '
                             f'(sync_min={self.sync_min_value}) ident={self.instr_ident}')
                await send_ident_query_response(kamlet, self.instr_ident, min_distance)
            self.response_sent = True

    async def finalize(self, kamlet: 'Kamlet') -> None:
        # Clean up sync state
        kamlet.synchronizer.clear_sync(self.instr_ident)


async def send_ident_query_response(kamlet: 'Kamlet', response_ident: int, min_distance: int):
    """Send the ident query result back to the lamlet."""
    jamlet = kamlet.jamlets[0]

    length = 2
    packet_data = [bytearray([min_distance])]

    header = IdentHeader(
        target_x=jamlet.lamlet_x,
        target_y=jamlet.lamlet_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        message_type=MessageType.IDENT_QUERY_RESP,
        send_type=SendType.SINGLE,
        length=length,
        ident=response_ident,
    )

    # Get kinstr span as parent (message completes when lamlet receives it)
    kinstr_span_id = jamlet.monitor.get_kinstr_span_id(response_ident)

    packet = [header] + packet_data
    await jamlet.send_packet(packet, parent_span_id=kinstr_span_id)
