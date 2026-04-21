'''
Reduce a per-jamlet local value across all jamlets via the sync network.

The kamlet computes a per-jamlet value from `src` per `op`, aggregates
those values locally, and injects the result into the sync network. Once
the sync completes, the aggregate value is written to every ew=32 slot of
`dst` on every jamlet, so the lamlet can recover it via
read_register_element(dst, element_index=0, element_width=32).

`src_is_mask=True` (used by vfirst.m): `src` is a mask vline (ew=1). The
per-jamlet value is the global RVV element index of the first set mask
bit inside [0, n_elements), or the sentinel 0xFFFFFFFF when no bit is set.
With op=MINU and width=32, the sentinel is larger than any valid index
and naturally loses under min, so "no set bit" propagates.
'''

from dataclasses import dataclass
from typing import TYPE_CHECKING
import logging

from zamlet import addresses
from zamlet.kamlet.kinstructions import KInstr
from zamlet.synchronization import (
    SyncAggOp, WaitingItemSyncState, aggregate_sync_values,
)
from zamlet.waiting_item import WaitingItem

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet

logger = logging.getLogger(__name__)


MASK_SCAN_SENTINEL = 0xFFFFFFFF


@dataclass
class ReduceSync(KInstr):
    """Sync-network reduction kinstr.

    dst:          destination vreg; written with aggregate at ew=32 in every slot
    src:          source vreg
    op:           aggregation op (SyncAggOp)
    width:        operand width in bits
    n_elements:   number of active elements to scan (bound on bit*j_in_l+vw_index)
    sync_ident:   sync-network identifier (lamlet allocates)
    word_order:   ordering used to map (k_index, j_in_k_index) -> vw_index
    instr_ident:  kamlet kinstr identifier
    src_is_mask:  True if `src` is a mask vline (ew=1) to scan for first set bit.
                  When True, per-jamlet value is the global element index of
                  first set bit or MASK_SCAN_SENTINEL. Combined with op=MINU +
                  width=32, this implements vfirst.m aggregation.
    """
    dst: int
    src: int
    op: SyncAggOp
    width: int
    n_elements: int
    sync_ident: int
    word_order: addresses.WordOrder
    instr_ident: int
    src_is_mask: bool = False

    async def admit(self, kamlet) -> 'ReduceSync | None':
        src_preg = kamlet.r(self.src)
        dst_elements_in_vline = kamlet.params.vline_bytes * 8 // 32
        dst_pregs = await kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=0,
            start_index=0, n_elements=dst_elements_in_vline,
            elements_in_vline=dst_elements_in_vline,
            mask_present=False,
            exclude_reuse={src_preg})
        return self.rename(
            needs_witem=1,
            src_pregs={0: src_preg},
            dst_pregs={0: dst_pregs[0]},
        )

    def _local_value_for_jamlet(self, kamlet, jamlet, j_in_k_index: int) -> int:
        """Compute the per-jamlet local value.

        For mask-scan mode (src_is_mask=True): return global RVV element index
        of the first set mask bit in [0, n_elements), or MASK_SCAN_SENTINEL
        if no bit is set.
        """
        params = kamlet.params
        wb = params.word_bytes
        ww = wb * 8
        j_in_l = params.j_in_l
        vw_index = addresses.k_indices_to_vw_index(
            params, self.word_order, kamlet.k_index, j_in_k_index)
        src_base = self.renamed.src_pregs[0] * wb

        if self.src_is_mask:
            for bit in range(ww):
                e = bit * j_in_l + vw_index
                if e >= self.n_elements:
                    break
                byte = jamlet.rf_slice[src_base + bit // 8]
                if (byte >> (bit % 8)) & 1:
                    return e
            return MASK_SCAN_SENTINEL
        raise NotImplementedError(
            "ReduceSync non-mask-scan mode not implemented yet")

    async def execute(self, kamlet: 'Kamlet') -> None:
        r = self.renamed

        local_values = [
            self._local_value_for_jamlet(kamlet, jamlet, j_in_k_index)
            for j_in_k_index, jamlet in enumerate(kamlet.jamlets)
        ]
        kamlet_agg = aggregate_sync_values(
            self.op, local_values, width=self.width)

        rf_write_ident = kamlet.rf_info.start(
            read_regs=r.read_pregs, write_regs=r.write_pregs)

        witem = WaitingReduceSync(
            instr_ident=self.instr_ident,
            sync_ident=self.sync_ident,
            dst_preg=r.dst_pregs[0],
            src_preg=r.src_pregs[0],
            rf_ident=rf_write_ident,
        )
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingReduceSync',
            read_regs=r.read_pregs, write_regs=r.write_pregs)

        kinstr_span_id = kamlet.monitor.get_kinstr_span_id(self.instr_ident)
        kamlet.monitor.create_sync_local_span(
            self.sync_ident, kamlet.synchronizer.kx, kamlet.synchronizer.ky,
            kinstr_span_id)

        kamlet.cache_table.add_witem_immediately(witem=witem)
        kamlet.synchronizer.local_event(
            self.sync_ident, value=kamlet_agg, op=self.op, width=self.width)

        logger.debug(
            f'{kamlet.clock.cycle}: ReduceSync execute: kamlet '
            f'({kamlet.min_x},{kamlet.min_y}) ident={self.instr_ident} '
            f'sync_ident={self.sync_ident} op={self.op.name} '
            f'locals={local_values} kamlet_agg={kamlet_agg}')


class WaitingReduceSync(WaitingItem):
    """Polls sync completion, then fans the aggregate into dst on every
    jamlet of this kamlet."""

    def __init__(self, instr_ident: int, sync_ident: int,
                 dst_preg: int, src_preg: int, rf_ident: int):
        super().__init__(item=None, instr_ident=instr_ident, rf_ident=rf_ident)
        self.sync_ident = sync_ident
        self.dst_preg = dst_preg
        self.src_preg = src_preg
        self.sync_state = WaitingItemSyncState.IN_PROGRESS
        self.aggregate: int | None = None
        self.dst_written = False

    def ready(self) -> bool:
        return self.dst_written

    async def monitor_kamlet(self, kamlet: 'Kamlet') -> None:
        if self.dst_written:
            return
        if self.sync_state == WaitingItemSyncState.IN_PROGRESS:
            if kamlet.synchronizer.is_complete(self.sync_ident):
                self.aggregate = kamlet.synchronizer.get_aggregated_value(
                    self.sync_ident)
                self.sync_state = WaitingItemSyncState.COMPLETE
        if self.sync_state == WaitingItemSyncState.COMPLETE:
            assert self.aggregate is not None, (
                f"ReduceSync sync_ident={self.sync_ident} completed with no "
                f"aggregate value; at least one kamlet must contribute")
            wb = kamlet.params.word_bytes
            dst_eb = 4
            dst_elements_per_word = wb // dst_eb
            value = self.aggregate & 0xFFFFFFFF
            result_bytes = value.to_bytes(dst_eb, byteorder='little', signed=False)
            witem_span_id = kamlet.monitor.get_witem_span_id(
                self.instr_ident, kamlet.min_x, kamlet.min_y)
            for jamlet in kamlet.jamlets:
                for idx in range(dst_elements_per_word):
                    byte_offset = idx * dst_eb
                    jamlet.write_vreg(
                        self.dst_preg, byte_offset, result_bytes,
                        span_id=witem_span_id,
                        event_details={'source': 'reduce_sync',
                                       'aggregate': value})
            self.dst_written = True
            logger.debug(
                f'{kamlet.clock.cycle}: ReduceSync witem complete: kamlet '
                f'({kamlet.min_x},{kamlet.min_y}) sync_ident={self.sync_ident} '
                f'aggregate=0x{value:x}')

    async def finalize(self, kamlet: 'Kamlet') -> None:
        assert self.dst_written
        assert self.rf_ident is not None
        kamlet.rf_info.finish(
            self.rf_ident,
            write_regs=[self.dst_preg], read_regs=[self.src_preg])
        kamlet.synchronizer.clear_sync(self.sync_ident)
