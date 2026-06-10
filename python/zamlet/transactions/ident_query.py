"""
Ident Query

This transaction queries each kamlet for its oldest active instr_ident and
synchronizes across all kamlets to aggregate the oldest-ident distance and
the active sync-id set. The lamlet participates in the sync directly, so
no mesh response is sent.

Used for flow control to prevent instr_ident collisions when wrapping.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from zamlet.waiting_item import WaitingItem
from zamlet.kamlet.kinstructions import (
    KInstr, KInstrOpcode, _pack_slotted_kinstr,
)
from zamlet.synchronization import (
    SyncAggOp,
)

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet


logger = logging.getLogger(__name__)


@dataclass
class IdentQuery(KInstr):
    """Query the oldest active instr_ident across all kamlets.

    Each kamlet computes the distance from baseline to its oldest active
    ident and contributes to a sync aggregation over the kamlet grid plus
    the lamlet. The lamlet is itself a sync participant; it reads the
    aggregated result directly from its own synchronizer, so no mesh
    response is sent from any kamlet.

    The lamlet consumes the aggregated value for allocator bookkeeping,
    but the monitor span is fire-and-forget and completes when its sync
    and kamlet execution children complete.
    """
    instr_ident: int  # Reserved IdentQuery instruction ident.
    baseline: int     # next_instr_ident at time of query
    previous_instr_ident: int | None = None  # instr_ident of instruction ahead in queue
    sync_ident: int | None = None
    must_drain_valid: bool = False
    must_drain_sync_ident: int = 0
    opcode: int = KInstrOpcode.IDENT_QUERY

    def encode(self, params) -> int:
        assert self.sync_ident is not None
        assert 0 <= self.sync_ident < params.max_concurrent_syncs
        assert 0 <= self.must_drain_sync_ident < params.max_concurrent_syncs
        assert params.ident_width <= 12
        baseline_slots = int(self.baseline)
        return _pack_slotted_kinstr(
            opcode=self.opcode,
            instr_ident=self.instr_ident,
            f1=int(self.must_drain_sync_ident),
            f2=(baseline_slots >> 6) & 0x3f,
            f3=baseline_slots & 0x3f,
            f4=int(self.sync_ident) << params.sync_ident_width,
            misc=int(self.must_drain_valid) << 7,
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

        witem = WaitingIdentQuery(
            ident=self.instr_ident,
            sync_ident=self.sync_ident,
            distance=distance,
            must_drain_sync_ident=(
                self.must_drain_sync_ident if self.must_drain_valid else None))
        # Explicitly call monitor once so that they are guaranteed to try to
        # sync before the next IdentQuery comes.
        sync_keys = [x for x in range(kamlet.params.max_concurrent_syncs)
                     if kamlet.synchronizer.has_local_seen(x)]
        logger.debug(
            f'{kamlet.clock.cycle}: ({kamlet.min_x}, {kamlet.min_y}) '
            f'IdentQuery executing. sync keys are {sync_keys}')
        await witem.monitor_kamlet(kamlet)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingIdentQuery')
        kamlet.cache_table.add_witem_immediately(witem=witem)
        


class WaitingIdentQuery(WaitingItem):
    """Waiting item for IdentQuery instruction.

    The synchronizer may defer this query's local event until another
    sync id drains. This lets the query use the last free sync id while
    still guaranteeing its active-mask result can reclaim at least one
    sync id.

    Once local_event has fired and the synchronizer's sync is complete,
    ready() returns True so finalize can clear the sync state.
    """

    def __init__(
            self, ident: int, sync_ident: int, distance: int | None,
            must_drain_sync_ident: int | None):
        super().__init__(item=None, instr_ident=ident)
        self.sync_ident = sync_ident
        self.distance = distance
        self.must_drain_sync_ident = must_drain_sync_ident
        self.local_event_fired = False
        self.complete = False

    def ready(self) -> bool:
        return self.complete

    async def monitor_kamlet(self, kamlet: 'Kamlet') -> None:
        if not self.local_event_fired:
            distance = (kamlet.params.max_response_tags
                        if self.distance is None else self.distance)
            logger.debug(
                f'{kamlet.clock.cycle}: IdentQuery: kamlet '
                f'({kamlet.min_x},{kamlet.min_y}) firing local_event '
                f'ident={self.instr_ident} sync_ident={self.sync_ident} '
                f'distance={self.distance} must_drain={self.must_drain_sync_ident}')
            kamlet.synchronizer.local_event(
                self.sync_ident, value=distance,
                op=SyncAggOp.MIN_WITH_ACTIVE_MASK,
                width=kamlet.params.sync_value_width,
                must_drain_sync_ident=self.must_drain_sync_ident)
            self.local_event_fired = True
        elif not self.complete and kamlet.synchronizer.is_complete(self.sync_ident):
            self.complete = True
            logger.debug(
                f'{kamlet.clock.cycle}: IdentQuery: kamlet '
                f'({kamlet.min_x},{kamlet.min_y}) witem complete '
                f'ident={self.instr_ident} sync_ident={self.sync_ident}')

    async def finalize(self, kamlet: 'Kamlet') -> None:
        # Clean up sync state
        logger.debug(
            f'{kamlet.clock.cycle}: IdentQuery: kamlet '
            f'({kamlet.min_x},{kamlet.min_y}) finalize cleared sync_state '
            f'ident={self.instr_ident} sync_ident={self.sync_ident}')
        kamlet.synchronizer.clear_sync(self.sync_ident)
