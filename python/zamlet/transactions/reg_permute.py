"""
Base classes for vector register permutation kinstrs.

Shared machinery for operations that read a vs2 source vector register,
compute a source element index for each destination lane, and either write
vs2[idx] to vd[i] (via local RF read or a cross-jamlet ReadRegElement
transaction) or write 0 when idx >= vlmax. The subclass only has to say
*how* the source index is derived; everything else — dst allocation, vs2
locking, mask handling, local/remote routing, sync, response/drop — lives
here.

Concrete subclasses:
- RegGather (`transactions/reg_gather.py`):  idx = vs1[i]   (index vreg).
- RegSlide  (`transactions/reg_slide.py`):   idx = i +/- offset (scalar).

The hardware path is expected to share the same machinery, differing only
in the index-computation input; this python split mirrors that.
"""

from typing import List, TYPE_CHECKING
from dataclasses import dataclass
import logging

from zamlet import addresses
from zamlet.kamlet.kinstructions import KInstr
from zamlet.waiting_item import WaitingItem
from zamlet.kamlet.cache_table import SendState
from zamlet.message import RegElementHeader, MessageType, SendType
from zamlet.synchronization import WaitingItemSyncState as SyncState

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet
    from zamlet.kamlet.kamlet import Kamlet

logger = logging.getLogger(__name__)


@dataclass
class RegPermute(KInstr):
    """Base vector permutation kinstr.

    Fields are the subset common to every permutation variant: a single
    source data vreg (vs2), a destination range, data element width, and
    optional mask. Subclasses add fields that drive their index
    computation (vs1/index_ew for gather; offset/direction for slide).
    """
    vd: int
    vs2: int
    start_index: int
    n_elements: int
    data_ew: int
    word_order: addresses.WordOrder
    vlmax: int
    mask_reg: int | None
    instr_ident: int

    def _compute_extra_src_pregs(self, kamlet, dst_elements_in_vline) -> dict[int, int]:
        """Hook: extra per-vline pregs to lock beyond vs2 (e.g. vs1 for gather).

        Return a dict keyed by absolute vline index. Default: no extras.
        """
        return {}

    def _create_waiting_item(self, kamlet, rf_ident: int, renamed) -> 'WaitingRegPermute':
        """Hook: build the WaitingRegPermute subclass for this kinstr."""
        raise NotImplementedError(f"{type(self).__name__}._create_waiting_item")

    async def admit(self, kamlet) -> 'RegPermute | None':
        params = kamlet.params
        dst_elements_in_vline = params.vline_bytes * 8 // self.data_ew

        dst_start_vline = self.start_index // dst_elements_in_vline
        dst_end_vline = (self.start_index + self.n_elements - 1) // dst_elements_in_vline

        # vs2 is read across [0, vlmax); the entire range must be locked because
        # any element of vs2 may be read (the actual index is data-dependent
        # for gather, and statically bounded but still arbitrary for slide —
        # we keep the loose lock here so hardware doesn't have to peek inside
        # the instruction's index computation).
        vs2_n_vlines = (self.vlmax + dst_elements_in_vline - 1) // dst_elements_in_vline

        # Resolve src/mask phys lookups BEFORE allocating dst phys, so an arch
        # overlap (mask_reg == dst arch) resolves to the old phys.
        extra_src_pregs = self._compute_extra_src_pregs(kamlet, dst_elements_in_vline)
        vs2_pregs = {v: kamlet.r(self.vs2 + v) for v in range(vs2_n_vlines)}
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None

        exclude = set(extra_src_pregs.values()) | set(vs2_pregs.values())
        if mask_preg is not None:
            exclude.add(mask_preg)
        dst_preg_list = await kamlet.alloc_dst_pregs(
            base_arch=self.vd, start_vline=dst_start_vline, end_vline=dst_end_vline,
            start_index=self.start_index, n_elements=self.n_elements,
            elements_in_vline=dst_elements_in_vline,
            mask_present=self.mask_reg is not None,
            exclude_reuse=exclude)
        dst_pregs = {
            dst_start_vline + i: dst_preg_list[i] for i in range(len(dst_preg_list))
        }

        # vd cannot overlap vs2 or any extra index source (RVV constraint for
        # all supported permutations).
        assert not (set(dst_pregs.values()) & set(extra_src_pregs.values())), \
            f"vd overlaps extra src: {dst_pregs} & {extra_src_pregs}"
        assert not (set(dst_pregs.values()) & set(vs2_pregs.values())), \
            f"vd overlaps vs2: {dst_pregs} & {vs2_pregs}"
        if mask_preg is not None:
            assert mask_preg not in dst_pregs.values()

        return self.rename(
            needs_witem=1,
            src_pregs=extra_src_pregs, src2_pregs=vs2_pregs,
            dst_pregs=dst_pregs, mask_preg=mask_preg,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        logger.debug(f'kamlet ({kamlet.min_x}, {kamlet.min_y}): '
                     f'{type(self).__name__}.execute '
                     f'vd={self.vd} vs2={self.vs2} ident={self.instr_ident}')
        rf_ident = kamlet.rf_info.start(
            read_regs=r.read_pregs, write_regs=r.write_pregs)
        witem = self._create_waiting_item(kamlet, rf_ident, r)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, type(witem).__name__,
            read_regs=r.read_pregs, write_regs=r.write_pregs)
        kamlet.cache_table.add_witem_immediately(witem=witem)


class WaitingRegPermute(WaitingItem):
    """Base waiting item for vector permutations.

    Holds the ReadRegElement-based routing and sync machinery. Subclasses
    override `_compute_src_index()` to supply the source element index for
    each destination lane and `_extra_read_regs()` to surface any
    additional source pregs (e.g. vs1 for gather) for finalize().
    """

    def __init__(self, params, instr: RegPermute, rf_ident: int,
                 dst_pregs: dict[int, int], vs2_pregs: dict[int, int],
                 mask_preg: int | None):
        super().__init__(item=instr, instr_ident=instr.instr_ident, rf_ident=rf_ident)
        self.params = params
        # Phys regs locked at start time, keyed by absolute vline index.
        # The kamlet rename table may rotate the arch regs by the time the
        # witem runs.
        self.dst_pregs = dst_pregs
        self.vs2_pregs = vs2_pregs
        self.mask_preg = mask_preg
        n_tags = params.j_in_k * params.word_bytes
        self.transaction_states: List[SendState] = [SendState.INITIAL for _ in range(n_tags)]
        self.completion_sync_state = SyncState.NOT_STARTED

    def _state_index(self, j_in_k_index: int, tag: int) -> int:
        return j_in_k_index * self.params.word_bytes + tag

    def ready(self) -> bool:
        return self.completion_sync_state == SyncState.COMPLETE

    def _compute_src_index(self, jamlet: 'Jamlet', dst_e: int) -> int:
        """Subclass hook: source element index for destination element dst_e.

        Return any non-negative integer. If >= vlmax, the destination lane
        is written with zeros.
        """
        raise NotImplementedError(f"{type(self).__name__}._compute_src_index")

    def _extra_read_regs(self) -> list[int]:
        """Subclass hook: additional source pregs to surface to finalize()."""
        return []

    def _compute_dst_element(self, jamlet: 'Jamlet', tag: int):
        """Compute destination element info for a given tag.

        Returns: (dst_ve, dst_e, dst_eb, dst_v)
            dst_ve: element within vector line
            dst_e: actual vector element index
            dst_eb: byte within element
            dst_v: vector line index (register offset from vd)
        """
        instr = self.item
        ew = instr.data_ew
        dst_vw = addresses.j_coords_to_vw_index(
            jamlet.params, word_order=instr.word_order, jx=jamlet.jx, jy=jamlet.jy)
        dst_wb = tag * 8
        assert (ew % 8) == 0
        dst_eb = dst_wb % ew
        dst_we = dst_wb // ew
        dst_ve = dst_we * jamlet.params.j_in_l + dst_vw
        elements_in_vline = jamlet.params.vline_bytes * 8 // ew
        if dst_ve < instr.start_index % elements_in_vline:
            dst_v = instr.start_index // elements_in_vline + 1
        else:
            dst_v = instr.start_index // elements_in_vline
        dst_e = dst_v * elements_in_vline + dst_ve
        return (dst_ve, dst_e, dst_eb, dst_v)

    def _compute_src_location(self, jamlet: 'Jamlet', index: int):
        """Compute where vs2[index] lives.

        Returns: (src_x, src_y, src_v, src_byte_offset) or None if index >= vlmax.
        src_v is the vline offset into vs2; the caller resolves it to a phys
        reg via self.vs2_pregs[src_v] for local reads, or sends it in the
        message header for remote reads (the receiver does the same lookup
        on its own kamlet's witem).
        """
        instr = self.item
        if index >= instr.vlmax:
            return None

        ew = instr.data_ew
        eb = ew // 8
        elements_in_vline = jamlet.params.vline_bytes * 8 // ew

        src_v = index // elements_in_vline
        src_ve = index % elements_in_vline
        src_vw = src_ve % jamlet.params.j_in_l
        src_we = src_ve // jamlet.params.j_in_l

        src_k, src_j_in_k = addresses.vw_index_to_k_indices(
            jamlet.params, instr.word_order, src_vw)
        src_x, src_y = addresses.k_indices_to_routing_coords(
            jamlet.params, src_k, src_j_in_k)

        src_byte_offset = src_we * eb

        return (src_x, src_y, src_v, src_byte_offset)

    async def monitor_jamlet(self, jamlet: 'Jamlet') -> None:
        wb = jamlet.params.word_bytes
        instr = self.item
        data_eb = instr.data_ew // 8
        witem_span_id = jamlet.monitor.get_witem_span_id(
            instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)

        for tag in range(wb):
            state_idx = self._state_index(jamlet.j_in_k_index, tag)
            state = self.transaction_states[state_idx]

            if state == SendState.INITIAL:
                dst_ve, dst_e, dst_eb, dst_v = self._compute_dst_element(jamlet, tag)

                # Skip if not the start of an element or out of range
                if (dst_eb != 0 or dst_e < instr.start_index
                        or dst_e >= instr.start_index + instr.n_elements):
                    self.transaction_states[state_idx] = SendState.COMPLETE
                    continue

                # Check mask
                if self.mask_preg is not None:
                    mask_word = int.from_bytes(
                        jamlet.rf_slice[self.mask_preg * wb: (self.mask_preg + 1) * wb],
                        byteorder='little')
                    bit_index = dst_e // jamlet.params.j_in_l
                    mask_bit = (mask_word >> bit_index) & 1
                    if not mask_bit:
                        self.transaction_states[state_idx] = SendState.COMPLETE
                        continue

                # Subclass-specific: derive source element index
                index = self._compute_src_index(jamlet, dst_e)

                # Out-of-range: write 0
                if index >= instr.vlmax:
                    dst_preg = self.dst_pregs[dst_v]
                    jamlet.write_vreg(
                        dst_preg, tag, bytes(data_eb),
                        span_id=witem_span_id,
                        event_details={'element': dst_e, 'tag': tag,
                                       'reason': 'index>=vlmax'},
                    )
                    self.transaction_states[state_idx] = SendState.COMPLETE
                    continue

                src_loc = self._compute_src_location(jamlet, index)
                assert src_loc is not None
                src_x, src_y, src_v, src_byte_offset = src_loc

                # Local read — same jamlet (and therefore same kamlet, so we
                # can use this kamlet's vs2_pregs directly).
                if src_x == jamlet.x and src_y == jamlet.y:
                    src_preg = self.vs2_pregs[src_v]
                    src_offset = src_preg * wb + src_byte_offset
                    src_data = jamlet.rf_slice[src_offset:src_offset + data_eb]
                    dst_preg = self.dst_pregs[dst_v]
                    jamlet.write_vreg(
                        dst_preg, tag, bytes(src_data),
                        span_id=witem_span_id,
                        event_details={'element': dst_e, 'tag': tag,
                                       'src_preg': src_preg,
                                       'src_byte': src_byte_offset,
                                       'source': 'local'},
                    )
                    self.transaction_states[state_idx] = SendState.COMPLETE
                else:
                    # Need to send request to remote jamlet
                    self.transaction_states[state_idx] = SendState.NEED_TO_SEND

            elif state == SendState.NEED_TO_SEND:
                dst_ve, dst_e, dst_eb, dst_v = self._compute_dst_element(jamlet, tag)
                index = self._compute_src_index(jamlet, dst_e)
                src_loc = self._compute_src_location(jamlet, index)
                assert src_loc is not None
                src_x, src_y, src_v, src_byte_offset = src_loc

                header = RegElementHeader(
                    target_x=src_x,
                    target_y=src_y,
                    source_x=jamlet.x,
                    source_y=jamlet.y,
                    message_type=MessageType.READ_REG_ELEMENT_REQ,
                    send_type=SendType.SINGLE,
                    length=0,
                    ident=instr.instr_ident,
                    tag=tag,
                    src_vline_offset=src_v,
                    src_byte_offset=src_byte_offset,
                    n_bytes=data_eb,
                )
                packet = [header]

                witem_span_id = jamlet.monitor.get_witem_span_id(
                    instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)
                transaction_span_id = jamlet.monitor.create_transaction(
                    transaction_type='ReadRegElement',
                    ident=instr.instr_ident,
                    src_x=jamlet.x,
                    src_y=jamlet.y,
                    dst_x=src_x,
                    dst_y=src_y,
                    tag=tag,
                    parent_span_id=witem_span_id,
                )

                await jamlet.send_packet(packet, parent_span_id=transaction_span_id)
                self.transaction_states[state_idx] = SendState.WAITING_FOR_RESPONSE

    async def monitor_kamlet(self, kamlet: 'Kamlet') -> None:
        # Completion sync: wait for every kamlet to finish its local
        # transactions before allowing the witem to be removed.
        completion_sync_ident = self.instr_ident
        kinstr_span_id = kamlet.monitor.get_kinstr_span_id(self.instr_ident)

        if self.completion_sync_state == SyncState.NOT_STARTED:
            if all(s == SendState.COMPLETE for s in self.transaction_states):
                self.completion_sync_state = SyncState.IN_PROGRESS
                kamlet.monitor.create_sync_local_span(
                    completion_sync_ident, kamlet.synchronizer.kx, kamlet.synchronizer.ky,
                    kinstr_span_id)
                kamlet.synchronizer.local_event(completion_sync_ident)
        elif self.completion_sync_state == SyncState.IN_PROGRESS:
            if kamlet.synchronizer.is_complete(completion_sync_ident):
                self.completion_sync_state = SyncState.COMPLETE

    def process_response(self, jamlet: 'Jamlet', packet) -> None:
        """Handle READ_REG_ELEMENT_RESP."""
        wb = jamlet.params.word_bytes
        instr = self.item
        data_eb = instr.data_ew // 8

        header = packet[0]
        data = packet[1]
        assert isinstance(header, RegElementHeader)
        tag = header.tag

        state_idx = self._state_index(jamlet.j_in_k_index, tag)
        assert self.transaction_states[state_idx] == SendState.WAITING_FOR_RESPONSE

        _, dst_e, _, dst_v = self._compute_dst_element(jamlet, tag)
        dst_preg = self.dst_pregs[dst_v]

        witem_span_id = jamlet.monitor.get_witem_span_id(
            instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)
        jamlet.write_vreg(
            dst_preg, tag, data.to_bytes(wb, 'little')[:data_eb],
            span_id=witem_span_id,
            event_details={'element': dst_e, 'tag': tag, 'source': 'remote'},
        )

        self.transaction_states[state_idx] = SendState.COMPLETE

        jamlet.monitor.complete_transaction(
            ident=header.ident,
            tag=tag,
            src_x=jamlet.x,
            src_y=jamlet.y,
            dst_x=header.source_x,
            dst_y=header.source_y,
        )

    def process_drop(self, jamlet: 'Jamlet', packet) -> None:
        """Handle READ_REG_ELEMENT_DROP: retry the request."""
        header = packet[0]
        assert isinstance(header, RegElementHeader)
        tag = header.tag
        state_idx = self._state_index(jamlet.j_in_k_index, tag)
        assert self.transaction_states[state_idx] == SendState.WAITING_FOR_RESPONSE
        self.transaction_states[state_idx] = SendState.NEED_TO_SEND
        logger.debug(f'{jamlet.clock.cycle}: {type(self).__name__} DROP: '
                     f'jamlet ({jamlet.x},{jamlet.y}) ident={self.instr_ident} '
                     f'tag={tag} will resend')

    async def finalize(self, kamlet) -> None:
        write_regs = list(self.dst_pregs.values())
        read_regs = list(set(self.vs2_pregs.values()) | set(self._extra_read_regs()))
        if self.mask_preg is not None:
            read_regs.append(self.mask_preg)
        kamlet.rf_info.finish(self.rf_ident, write_regs=write_regs, read_regs=read_regs)
