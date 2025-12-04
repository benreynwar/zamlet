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
from zamlet.kamlet.kinstructions import KInstr
from zamlet.message import IdentHeader, MessageType, SendType
from zamlet.synchronization import WaitingItemSyncState

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet


logger = logging.getLogger(__name__)


@dataclass
class IdentQuery(KInstr):
    """Query the oldest active instr_ident across all kamlets.

    Each kamlet computes the distance from baseline to its oldest active ident,
    synchronizes to find the minimum, and kamlet (0,0) sends the result to lamlet.
    """
    instr_ident: int  # Used for both sync and response (set to max_response_tags)
    baseline: int     # next_instr_ident at time of query
    previous_instr_ident: int  # instr_ident of instruction ahead in queue

    async def update_kamlet(self, kamlet: 'Kamlet'):
        distance = kamlet.cache_table.get_oldest_active_instr_ident_distance(self.baseline)

        # If no waiting items, use previous_instr_ident + 1 as the oldest
        # (the instruction ahead of this query must have completed or is completing)
        if distance is None:
            max_tags = kamlet.params.max_response_tags
            oldest_ident = (self.previous_instr_ident + 1) % max_tags
            distance = (oldest_ident - self.baseline) % max_tags

        logger.debug(f'{kamlet.clock.cycle}: IdentQuery: kamlet ({kamlet.min_x},{kamlet.min_y}) '
                     f'baseline={self.baseline} previous={self.previous_instr_ident} '
                     f'distance={distance}')

        # Create waiting item to track sync completion and send response
        is_origin = (kamlet.min_x == 0 and kamlet.min_y == 0)
        witem = WaitingIdentQuery(
            ident=self.instr_ident,
            is_origin=is_origin,
        )
        await kamlet.cache_table.add_witem(witem)

        # Report to synchronizer (uses min aggregation)
        kamlet.synchronizer.local_event(self.instr_ident, value=distance)


class WaitingIdentQuery(WaitingItem):
    """Waiting item for IdentQuery instruction.

    Monitors sync completion and has kamlet (0,0) send the result to lamlet.
    """

    def __init__(self, ident: int, is_origin: bool):
        super().__init__(item=None, instr_ident=ident)
        self.is_origin = is_origin
        self.response_sent = False
        self.sync_state = WaitingItemSyncState.IN_PROGRESS
        self.sync_min_value: int | None = None

    def ready(self) -> bool:
        return self.response_sent

    async def monitor_kamlet(self, kamlet: 'Kamlet') -> None:
        if self.response_sent:
            return

        if self.sync_state == WaitingItemSyncState.COMPLETE:
            if self.is_origin:
                # Kamlet (0,0) sends the response to lamlet
                logger.debug(f'{kamlet.clock.cycle}: IdentQuery: kamlet (0,0) '
                             f'sending response min_distance={self.sync_min_value} ident={self.instr_ident}')
                await send_ident_query_response(kamlet, self.instr_ident, self.sync_min_value)
            self.response_sent = True

    async def finalize(self, kamlet: 'Kamlet') -> None:
        # Clean up sync state
        kamlet.synchronizer.clear_sync(self.instr_ident)


async def send_ident_query_response(kamlet: 'Kamlet', response_ident: int, min_distance: int | None):
    """Send the ident query result back to the lamlet.

    If min_distance is None (all free), sends header only (length=1).
    If min_distance has a value, sends header + data byte (length=2).
    """
    jamlet = kamlet.jamlets[0]

    if min_distance is None:
        length = 1
        packet_data = []
    else:
        length = 2
        packet_data = [bytearray([min_distance])]

    header = IdentHeader(
        target_x=jamlet.x,
        target_y=-1,  # Lamlet is at y=-1
        source_x=jamlet.x,
        source_y=jamlet.y,
        message_type=MessageType.IDENT_QUERY_RESP,
        send_type=SendType.SINGLE,
        length=length,
        ident=response_ident,
    )

    packet = [header] + packet_data
    await jamlet.send_packet(packet)
