"""
Vector register gather (vrgather.vv): vd[i] = (vs1[i] >= VLMAX) ? 0 : vs2[vs1[i]]

RF-to-RF gather: reads from arbitrary register positions based on index vector.
This is the inverse of RegScatter (used by vcompress).

Supports different element widths for index and data:
- vrgather.vv: index_ew = data_ew = SEW
- vrgatherei16.vv: index_ew = 16, data_ew = SEW
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
class RegGather(KInstr):
    """
    Vector register gather instruction.

    Each element i of vd gets the value vs2[vs1[i]], or 0 if vs1[i] >= vlmax.

    index_ew: element width for vs1 (indices)
    data_ew: element width for vs2 (source data) and vd (destination)
    start_index: first element to process (from vstart)
    n_elements: number of elements to process (vl)
    """
    vd: int
    vs2: int
    vs1: int
    start_index: int
    n_elements: int
    index_ew: int
    data_ew: int
    word_order: addresses.WordOrder
    vlmax: int
    mask_reg: int | None
    instr_ident: int

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x}, {kamlet.min_y}): RegGather.update_kamlet '
                     f'vd={self.vd} vs2={self.vs2} vs1={self.vs1} ident={self.instr_ident}')

        dst_regs = kamlet.get_regs(
            start_index=self.start_index, n_elements=self.n_elements,
            ew=self.data_ew, base_reg=self.vd)
        vs1_regs = kamlet.get_regs(
            start_index=self.start_index, n_elements=self.n_elements,
            ew=self.index_ew, base_reg=self.vs1)
        vs2_regs = kamlet.get_regs(
            start_index=0, n_elements=self.vlmax, ew=self.data_ew, base_reg=self.vs2)

        # Check for overlaps (vd cannot overlap vs1 or vs2)
        assert not (set(dst_regs) & set(vs1_regs)), \
            f"vd overlaps vs1: {dst_regs} & {vs1_regs}"
        assert not (set(dst_regs) & set(vs2_regs)), \
            f"vd overlaps vs2: {dst_regs} & {vs2_regs}"

        read_regs = list(set(vs1_regs) | set(vs2_regs))
        if self.mask_reg is not None:
            read_regs.append(self.mask_reg)
            assert self.mask_reg not in dst_regs

        await kamlet.wait_for_rf_available(write_regs=dst_regs, read_regs=read_regs,
                                           instr_ident=self.instr_ident)
        rf_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=dst_regs)
        witem = WaitingRegGather(params=kamlet.params, instr=self, rf_ident=rf_ident)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingRegGather',
            read_regs=read_regs, write_regs=dst_regs)
        await kamlet.cache_table.add_witem(witem=witem)


class WaitingRegGather(WaitingItem):
    """Waiting item for vector register gather (vrgather.vv)."""

    def __init__(self, params, instr: RegGather, rf_ident: int):
        super().__init__(item=instr, instr_ident=instr.instr_ident, rf_ident=rf_ident)
        self.params = params
        n_tags = params.j_in_k * params.word_bytes
        self.transaction_states: List[SendState] = [SendState.INITIAL for _ in range(n_tags)]
        self.completion_sync_state = SyncState.NOT_STARTED

    def _state_index(self, j_in_k_index: int, tag: int) -> int:
        return j_in_k_index * self.params.word_bytes + tag

    def ready(self) -> bool:
        return self.completion_sync_state == SyncState.COMPLETE

    def _compute_dst_element(self, jamlet: 'Jamlet', tag: int):
        """Compute destination element info for a given tag.

        Uses data_ew since destination uses data element width.

        Returns: (dst_ve, dst_e, dst_eb, dst_v)
            dst_ve: element within vector line
            dst_e: actual vector element index
            dst_eb: byte within element
            dst_v: vector line index (register offset from vd)
        """
        instr = self.item
        ew = instr.data_ew
        dst_vw = addresses.j_coords_to_vw_index(
            jamlet.params, word_order=instr.word_order, j_x=jamlet.x, j_y=jamlet.y)
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

    def _read_index(self, jamlet: 'Jamlet', element_index: int) -> int:
        """Read the index value from vs1[element_index].

        Uses index_ew since vs1 uses index element width.
        """
        instr = self.item
        wb = jamlet.params.word_bytes
        ew = instr.index_ew
        eb = ew // 8

        elements_in_vline = jamlet.params.vline_bytes * 8 // ew
        v = element_index // elements_in_vline
        ve = element_index % elements_in_vline
        we = ve // jamlet.params.j_in_l

        reg = instr.vs1 + v
        byte_in_word = (we * eb) % wb

        word_data = jamlet.rf_slice[reg * wb: (reg + 1) * wb]
        index_value = int.from_bytes(word_data[byte_in_word:byte_in_word + eb],
                                     byteorder='little', signed=False)
        return index_value

    def _compute_src_location(self, jamlet: 'Jamlet', index: int):
        """Compute where vs2[index] lives.

        Uses data_ew since vs2 uses data element width.

        Returns: (src_x, src_y, src_reg, src_byte_offset) or None if index >= vlmax
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
        src_x, src_y = addresses.k_indices_to_j_coords(jamlet.params, src_k, src_j_in_k)

        src_reg = instr.vs2 + src_v
        src_byte_offset = src_we * eb

        return (src_x, src_y, src_reg, src_byte_offset)

    async def monitor_jamlet(self, jamlet: 'Jamlet') -> None:
        wb = jamlet.params.word_bytes
        instr = self.item
        data_eb = instr.data_ew // 8

        for tag in range(wb):
            state_idx = self._state_index(jamlet.j_in_k_index, tag)
            state = self.transaction_states[state_idx]

            if state == SendState.INITIAL:
                dst_ve, dst_e, dst_eb, dst_v = self._compute_dst_element(jamlet, tag)

                # Skip if not the start of an element or out of range
                if dst_eb != 0 or dst_e >= instr.n_elements:
                    self.transaction_states[state_idx] = SendState.COMPLETE
                    continue

                # Check mask
                if instr.mask_reg is not None:
                    mask_word = int.from_bytes(
                        jamlet.rf_slice[instr.mask_reg * wb: (instr.mask_reg + 1) * wb],
                        byteorder='little')
                    bit_index = dst_e // jamlet.params.j_in_l
                    mask_bit = (mask_word >> bit_index) & 1
                    if not mask_bit:
                        self.transaction_states[state_idx] = SendState.COMPLETE
                        continue

                # Read index from vs1
                index = self._read_index(jamlet, dst_e)

                # Handle out-of-range: write 0
                if index >= instr.vlmax:
                    dst_reg = instr.vd + dst_v
                    dst_offset = dst_reg * wb + tag
                    jamlet.rf_slice[dst_offset:dst_offset + data_eb] = bytes(data_eb)
                    self.transaction_states[state_idx] = SendState.COMPLETE
                    continue

                # Compute source location
                src_loc = self._compute_src_location(jamlet, index)
                if src_loc is None:
                    # Should not happen since we checked index >= vlmax above
                    self.transaction_states[state_idx] = SendState.COMPLETE
                    continue

                src_x, src_y, src_reg, src_byte_offset = src_loc

                # Local read - same jamlet
                if src_x == jamlet.x and src_y == jamlet.y:
                    src_offset = src_reg * wb + src_byte_offset
                    src_data = jamlet.rf_slice[src_offset:src_offset + data_eb]
                    dst_reg = instr.vd + dst_v
                    dst_offset = dst_reg * wb + tag
                    jamlet.rf_slice[dst_offset:dst_offset + data_eb] = src_data
                    self.transaction_states[state_idx] = SendState.COMPLETE
                else:
                    # Need to send request to remote jamlet
                    self.transaction_states[state_idx] = SendState.NEED_TO_SEND

            elif state == SendState.NEED_TO_SEND:
                dst_ve, dst_e, dst_eb, dst_v = self._compute_dst_element(jamlet, tag)
                index = self._read_index(jamlet, dst_e)
                src_loc = self._compute_src_location(jamlet, index)
                assert src_loc is not None
                src_x, src_y, src_reg, src_byte_offset = src_loc

                header = RegElementHeader(
                    target_x=src_x,
                    target_y=src_y,
                    source_x=jamlet.x,
                    source_y=jamlet.y,
                    message_type=MessageType.READ_REG_ELEMENT_REQ,
                    send_type=SendType.SINGLE,
                    length=1,
                    ident=instr.instr_ident,
                    tag=tag,
                    src_reg=src_reg,
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
        # Completion sync - wait for all kamlets to finish their local transactions
        # before allowing WaitingRegGather to be removed
        completion_sync_ident = self.instr_ident
        kinstr_span_id = kamlet.monitor.get_kinstr_span_id(self.instr_ident)

        if self.completion_sync_state == SyncState.NOT_STARTED:
            if all(s == SendState.COMPLETE for s in self.transaction_states):
                self.completion_sync_state = SyncState.IN_PROGRESS
                kamlet.monitor.create_sync_local_span(
                    completion_sync_ident, kamlet.synchronizer.x, kamlet.synchronizer.y,
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

        dst_ve, dst_e, dst_eb, dst_v = self._compute_dst_element(jamlet, tag)
        dst_reg = instr.vd + dst_v
        dst_offset = dst_reg * wb + tag

        # Write received data to destination (extract only the needed bytes)
        jamlet.rf_slice[dst_offset:dst_offset + data_eb] = data[:data_eb]

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
        logger.debug(f'{jamlet.clock.cycle}: WaitingRegGather DROP: '
                     f'jamlet ({jamlet.x},{jamlet.y}) ident={self.instr_ident} tag={tag} will resend')

    async def finalize(self, kamlet) -> None:
        instr = self.item
        dst_regs = kamlet.get_regs(
            start_index=instr.start_index, n_elements=instr.n_elements,
            ew=instr.data_ew, base_reg=instr.vd)
        vs1_regs = kamlet.get_regs(
            start_index=instr.start_index, n_elements=instr.n_elements,
            ew=instr.index_ew, base_reg=instr.vs1)
        vs2_regs = kamlet.get_regs(
            start_index=0, n_elements=instr.vlmax, ew=instr.data_ew, base_reg=instr.vs2)
        read_regs = list(set(vs1_regs) | set(vs2_regs))
        if instr.mask_reg is not None:
            read_regs.append(instr.mask_reg)
        kamlet.rf_info.finish(self.rf_ident, write_regs=dst_regs, read_regs=read_regs)
