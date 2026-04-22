"""
Ident Query

This transaction queries each kamlet for its oldest active instr_ident and
synchronizes across all kamlets to aggregate a MIN_PAIR packed word. The
lamlet participates in the sync directly, so no mesh response is sent.

Used for flow control to prevent instr_ident collisions when wrapping.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from zamlet.waiting_item import WaitingItem
from zamlet.kamlet.kinstructions import (
    TrackedKInstr, Renamed, KInstrOpcode, KINSTR_WIDTH, OPCODE_WIDTH, SYNC_IDENT_WIDTH,
)
from zamlet.control_structures import pack_fields_to_int
from zamlet.monitor import SpanType, CompletionType
from zamlet.synchronization import (
    SyncAggOp, MIN_PAIR_TOTAL_WIDTH, pack_min_pair,
)

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet


logger = logging.getLogger(__name__)


@dataclass
class IdentQuery(TrackedKInstr):
    """Query the oldest active instr_ident across all kamlets.

    Each kamlet computes the distance from baseline to its oldest active
    ident and contributes to a MIN_PAIR sync aggregation over the kamlet
    grid plus the lamlet. The lamlet is itself a sync participant; it
    reads the aggregated result directly from its own synchronizer, so no
    mesh response is sent from any kamlet.

    Uses TrackedKInstr because the lamlet explicitly completes the kinstr
    once it consumes the aggregated value.
    """
    instr_ident: int  # Used for both sync and response (set to max_response_tags)
    baseline: int     # next_instr_ident at time of query
    previous_instr_ident: int | None = None  # instr_ident of instruction ahead in queue
    opcode: int = KInstrOpcode.IDENT_QUERY

    FIELD_SPECS = [
        ('opcode', OPCODE_WIDTH),
        ('baseline', SYNC_IDENT_WIDTH),
        ('instr_ident', SYNC_IDENT_WIDTH),
        ('_padding', KINSTR_WIDTH - OPCODE_WIDTH - 2 * SYNC_IDENT_WIDTH),
    ]

    def encode(self) -> int:
        return pack_fields_to_int(self, self.FIELD_SPECS)

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

    async def admit(self, kamlet: 'Kamlet') -> 'IdentQuery | None':
        # Snapshot the oldest-active distance at admit time: later-admitted
        # instructions can't have witems yet and must not skew the answer.
        distance = kamlet.get_oldest_active_instr_ident_distance(self.baseline)
        return self.rename(needs_witem=1, ident_query_distance=distance)

    async def execute(self, kamlet: 'Kamlet') -> None:
        distance = self.renamed.ident_query_distance

        logger.debug(f'{kamlet.clock.cycle}: IdentQuery: kamlet '
                     f'({kamlet.min_x},{kamlet.min_y}) witem created '
                     f'ident={self.instr_ident} baseline={self.baseline} '
                     f'distance={distance}')

        n_iq = kamlet.params.n_ident_query_slots
        max_tags = kamlet.params.max_response_tags
        next_instr_ident = max_tags + ((self.instr_ident + 1) % n_iq)
        next_iq_free = not kamlet.synchronizer.has_local_seen(next_instr_ident)
        witem = WaitingIdentQuery(
            ident=self.instr_ident, distance=distance)
        # Explicitly call monitor once so that they are guaranteed to try to
        # sync before the next IdentQuery comes.
        sync_keys = [x for x in range(512, 512+16) if kamlet.synchronizer.has_local_seen(x)]
        logger.info(f'{kamlet.clock.cycle}: ({kamlet.min_x}, {kamlet.min_y}) IdentQuery executing. sync keys are {sync_keys}')
        await witem.monitor_kamlet(kamlet)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingIdentQuery')
        kamlet.cache_table.add_witem_immediately(witem=witem)
        


class WaitingIdentQuery(WaitingItem):
    """Waiting item for IdentQuery instruction.

    Defers the synchronizer local_event until the kamlet has at least one
    IQ slot other than this query's free in its own sync states. Without
    that gating, a saturated kamlet would contribute "every slot still
    pending" to the MIN_PAIR aggregation and stall slot reclaim on the
    lamlet, since MIN_PAIR can never drop once every participant has
    contributed a saturated value.

    Once local_event has fired and the synchronizer's sync is complete,
    ready() returns True so finalize can clear the sync state.
    """

    def __init__(self, ident: int, distance: int | None):
        super().__init__(item=None, instr_ident=ident)
        self.distance = distance
        self.local_event_fired = False
        self.complete = False

    def ready(self) -> bool:
        return self.complete

    async def monitor_kamlet(self, kamlet: 'Kamlet') -> None:
        n_iq = kamlet.params.n_ident_query_slots
        max_tags = kamlet.params.max_response_tags
        next_instr_ident = max_tags + ((self.instr_ident + 1) % n_iq)
        next_iq_free = not kamlet.synchronizer.has_local_seen(next_instr_ident)
        if not self.local_event_fired and not next_iq_free:
            logger.info(
                f'{kamlet.clock.cycle}: IdentQuery: kamlet '
                f'({kamlet.min_x},{kamlet.min_y}) not firing local_event because next iq not free'
                f'ident={self.instr_ident} next_ident is {next_instr_ident}'
                )
        if not self.local_event_fired and next_iq_free:
            iq_slot_distance = (
                kamlet.get_oldest_pending_iq_slot_distance(self.instr_ident))
            packed = pack_min_pair(self.distance, iq_slot_distance)
            logger.info(
                f'{kamlet.clock.cycle}: IdentQuery: kamlet '
                f'({kamlet.min_x},{kamlet.min_y}) firing local_event '
                f'ident={self.instr_ident} distance={self.distance} '
                f'iq_slot_distance={iq_slot_distance} packed=0x{packed:x}')
            kamlet.synchronizer.local_event(
                self.instr_ident, value=packed,
                op=SyncAggOp.MIN_PAIR, width=MIN_PAIR_TOTAL_WIDTH)
            self.local_event_fired = True
        elif not self.complete and kamlet.synchronizer.is_complete(self.instr_ident):
            self.complete = True
            logger.debug(
                f'{kamlet.clock.cycle}: IdentQuery: kamlet '
                f'({kamlet.min_x},{kamlet.min_y}) witem complete '
                f'ident={self.instr_ident}')

    async def finalize(self, kamlet: 'Kamlet') -> None:
        # Clean up sync state
        logger.debug(
            f'{kamlet.clock.cycle}: IdentQuery: kamlet '
            f'({kamlet.min_x},{kamlet.min_y}) finalize cleared sync_state '
            f'ident={self.instr_ident}')
        kamlet.synchronizer.clear_sync(self.instr_ident)
