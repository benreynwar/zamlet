'''
Base class for gather-style loads (strided and indexed).

Both LoadStride and LoadIndexedUnordered load elements from non-contiguous memory
locations into contiguous register positions. The only difference is how the
source address is computed:
- LoadStride: base + (element_index * stride_bytes)
- LoadIndexed: base + index_register[element_index]

This module provides the shared implementation.
'''

from abc import ABC, abstractmethod
from typing import List, TYPE_CHECKING
from dataclasses import dataclass
import logging

from zamlet import addresses
from zamlet.waiting_item import WaitingItem
from zamlet.message import TaggedHeader, ReadMemWordHeader, MessageType, SendType
from zamlet.kamlet.cache_table import SendState
from zamlet.params import LamletParams
from zamlet import utils
from zamlet.synchronization import WaitingItemSyncState as SyncState

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet


logger = logging.getLogger(__name__)


@dataclass
class RequiredBytes:
    is_vpu: bool
    g_addr: addresses.GlobalAddress
    n_bytes: int
    tag: int


class WaitingLoadGatherBase(WaitingItem, ABC):
    """Base class for gather-style load waiting items (strided and indexed)."""

    reads_all_memory = True

    def __init__(self, instr, params: LamletParams, rf_ident: int | None = None):
        super().__init__(item=instr, instr_ident=instr.instr_ident, rf_ident=rf_ident)
        self.writeset_ident = instr.writeset_ident
        self.params = params
        n_tags = params.j_in_k * params.word_bytes
        self.transaction_states: List[SendState] = [SendState.NEED_TO_SEND for _ in range(n_tags)]
        self.sync_state = SyncState.NOT_STARTED

    @abstractmethod
    def get_element_byte_offset(self, jamlet: 'Jamlet', element_index: int) -> int:
        """Return the byte offset in memory for the given element index.

        For strided: (element_index - start_index) * stride_bytes
        For indexed: index_register[element_index]
        """
        pass

    @abstractmethod
    def get_additional_read_regs(self, kamlet) -> List[int]:
        """Return additional registers that need to be read (e.g., index register)."""
        pass

    def is_ordered(self) -> bool:
        """Return True if this is an ordered operation. Override in subclasses."""
        return False

    def _state_index(self, j_in_k_index: int, tag: int) -> int:
        return j_in_k_index * self.params.word_bytes + tag

    def _ready_to_synchronize(self) -> bool:
        return all(state == SendState.COMPLETE for state in self.transaction_states)

    def ready(self) -> bool:
        return self.sync_state == SyncState.COMPLETE

    async def monitor_jamlet(self, jamlet: 'Jamlet') -> None:
        wb = jamlet.params.word_bytes
        for tag in range(wb):
            state_idx = self._state_index(jamlet.j_in_k_index, tag)
            if self.transaction_states[state_idx] == SendState.NEED_TO_SEND:
                sent = await self._send_req(jamlet, tag)
                if sent:
                    self.transaction_states[state_idx] = SendState.WAITING_FOR_RESPONSE
                else:
                    self.transaction_states[state_idx] = SendState.COMPLETE

    async def monitor_kamlet(self, kamlet) -> None:
        if self._ready_to_synchronize() and self.sync_state == SyncState.NOT_STARTED:
            self.sync_state = SyncState.IN_PROGRESS
            self._synchronize(kamlet)
        if self.sync_state == SyncState.IN_PROGRESS:
            if kamlet.synchronizer.is_complete(self.instr_ident):
                self.sync_state = SyncState.COMPLETE

    def process_response(self, jamlet: 'Jamlet', packet) -> None:
        wb = jamlet.params.word_bytes
        header = packet[0]
        data = packet[1]
        assert isinstance(header, TaggedHeader)
        tag = header.tag
        state_idx = self._state_index(jamlet.j_in_k_index, tag)
        assert self.transaction_states[state_idx] == SendState.WAITING_FOR_RESPONSE
        self.transaction_states[state_idx] = SendState.COMPLETE

        instr = self.item
        request = self._get_request(jamlet, tag)
        assert request is not None
        if request.is_vpu:
            k_maddr = request.g_addr.to_k_maddr(jamlet.tlb)
            src_byte_in_word = k_maddr.addr % wb
        else:
            src_byte_in_word = 0
        dst_byte_in_word = tag

        dst_ve, dst_e, dst_eb, dst_v = self._compute_dst_element(jamlet, tag)
        dst_reg = instr.dst + dst_v

        old_word = jamlet.rf_slice[dst_reg * wb: (dst_reg + 1) * wb]
        new_word = utils.shift_and_update_word(
            old_word=old_word,
            src_word=data,
            src_start=src_byte_in_word,
            dst_start=dst_byte_in_word,
            n_bytes=request.n_bytes,
        )
        jamlet.rf_slice[dst_reg * wb: (dst_reg + 1) * wb] = new_word
        logger.debug(f'{jamlet.clock.cycle}: RF_WRITE {self.__class__.__name__}: '
                     f'jamlet ({jamlet.x},{jamlet.y}) ident={instr.instr_ident} '
                     f'rf[{dst_reg}] old={old_word.hex()} new={new_word.hex()}')
        witem_span_id = jamlet.monitor.get_witem_span_id(
            instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)
        jamlet.monitor.add_event(
            witem_span_id,
            f'rf_write jamlet_x={jamlet.x}, jamlet_y={jamlet.y}, element={dst_e}, '
            f'reg={dst_reg}, src_byte={src_byte_in_word}, dst_byte={dst_byte_in_word}, '
            f'n_bytes={request.n_bytes}, payload={data.hex()}, old={old_word.hex()}, '
            f'new={new_word.hex()}')
        jamlet.monitor.complete_transaction(
            ident=header.ident,
            tag=tag,
            src_x=jamlet.x,
            src_y=jamlet.y,
            dst_x=header.source_x,
            dst_y=header.source_y,
        )

    def process_drop(self, jamlet: 'Jamlet', packet) -> None:
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        tag = header.tag
        state_idx = self._state_index(jamlet.j_in_k_index, tag)
        assert self.transaction_states[state_idx] == SendState.WAITING_FOR_RESPONSE
        self.transaction_states[state_idx] = SendState.NEED_TO_SEND

    async def finalize(self, kamlet) -> None:
        instr = self.item
        dst_regs = kamlet.get_regs(
            start_index=instr.start_index, n_elements=instr.n_elements,
            ew=instr.dst_ordering.ew, base_reg=instr.dst)
        read_regs = self.get_additional_read_regs(kamlet)
        if instr.mask_reg is not None:
            read_regs.append(instr.mask_reg)
        kamlet.rf_info.finish(self.rf_ident, write_regs=dst_regs, read_regs=read_regs)

    def _compute_dst_element(self, jamlet: 'Jamlet', tag: int) -> tuple[int, int, int, int]:
        """Compute destination element info for a given tag.

        Returns: (dst_ve, dst_e, dst_eb, dst_v)
            dst_ve: element within vector line
            dst_e: actual vector element index
            dst_eb: byte within element
            dst_v: vector line index (register offset from instr.dst)
        """
        instr = self.item
        dst_vw = addresses.j_coords_to_vw_index(
            jamlet.params, word_order=instr.dst_ordering.word_order, j_x=jamlet.x, j_y=jamlet.y)
        dst_ew = instr.dst_ordering.ew
        dst_wb = tag * 8
        assert (dst_ew % 8) == 0
        dst_eb = dst_wb % dst_ew
        dst_we = dst_wb // dst_ew
        dst_ve = dst_we * jamlet.params.j_in_l + dst_vw
        elements_in_vline = jamlet.params.vline_bytes * 8 // dst_ew
        if dst_ve < instr.start_index % elements_in_vline:
            dst_v = instr.start_index // elements_in_vline + 1
        else:
            dst_v = instr.start_index // elements_in_vline
        dst_e = dst_v * elements_in_vline + dst_ve
        return (dst_ve, dst_e, dst_eb, dst_v)

    def _get_request(self, jamlet: 'Jamlet', tag: int) -> RequiredBytes | None:
        instr = self.item
        dst_ve, dst_e, dst_eb, dst_v = self._compute_dst_element(jamlet, tag)
        dst_ew = instr.dst_ordering.ew
        elements_in_vline = jamlet.params.vline_bytes * 8 // dst_ew
        assert instr.start_index <= dst_e < instr.start_index + elements_in_vline

        if dst_e < instr.start_index or dst_e >= instr.start_index + instr.n_elements:
            logger.debug(f'_get_request: jamlet ({jamlet.x},{jamlet.y}) ident={instr.instr_ident} '
                         f'tag={tag} dst_e={dst_e} '
                         f'out of range [{instr.start_index}, {instr.start_index + instr.n_elements})')
            return None

        if instr.mask_reg is not None:
            wb = jamlet.params.word_bytes
            mask_word = int.from_bytes(
                jamlet.rf_slice[instr.mask_reg * wb: (instr.mask_reg + 1) * wb],
                byteorder='little')
            bit_index = dst_e // jamlet.params.j_in_l
            mask_bit = (mask_word >> bit_index) & 1
            if not mask_bit:
                witem_span_id = jamlet.monitor.get_witem_span_id(
                    instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)
                jamlet.monitor.add_event(
                    witem_span_id, 'mask_skip',
                    jamlet_x=jamlet.x, jamlet_y=jamlet.y, element=dst_e,
                    bit_index=bit_index, mask_word=hex(mask_word))
                return None

        # Get byte offset for this element (subclass-specific)
        element_byte_offset = self.get_element_byte_offset(jamlet, dst_e)

        # Compute source address: base + element_byte_offset + byte_within_element
        src_g_addr = instr.g_addr.bit_offset(element_byte_offset * 8 + dst_eb)
        src_page_addr = src_g_addr.get_page()
        src_page_info = jamlet.tlb.get_page_info(src_page_addr)
        page_byte_offset = src_g_addr.addr % jamlet.params.page_bytes
        remaining_page_bytes = jamlet.params.page_bytes - page_byte_offset

        if not src_page_info.local_address.is_vpu:
            if dst_eb == 0 or page_byte_offset == 0:
                n_bytes = min(remaining_page_bytes, dst_ew // 8)
                return RequiredBytes(is_vpu=False, g_addr=src_g_addr, n_bytes=n_bytes, tag=tag)
            else:
                return None
        else:
            assert src_page_info.local_address.ordering is not None
            src_ew = src_page_info.local_address.ordering.ew
            src_eb = src_g_addr.bit_addr % src_ew
            if src_eb == 0 or dst_eb == 0 or page_byte_offset == 0:
                n_bytes = min((src_ew - src_eb) // 8, (dst_ew - dst_eb) // 8, remaining_page_bytes)
                return RequiredBytes(is_vpu=True, g_addr=src_g_addr, n_bytes=n_bytes, tag=tag)
            else:
                return None

    async def _send_req(self, jamlet: 'Jamlet', tag: int) -> bool:
        """Send a READ_MEM_WORD_REQ for this tag. Returns True if request was sent."""
        assert tag < jamlet.params.word_bytes
        instr = self.item
        request = self._get_request(jamlet, tag)
        if request is None:
            return False

        ident = (instr.instr_ident + tag + 1) % jamlet.params.max_response_tags
        dst_ve, dst_e, dst_eb, dst_v = self._compute_dst_element(jamlet, tag)

        if request.is_vpu:
            k_maddr = request.g_addr.to_k_maddr(jamlet.tlb)
            word_offset = k_maddr.addr % jamlet.params.word_bytes
            addr = k_maddr.bit_offset(-word_offset * 8)
            target_x, target_y = addresses.k_indices_to_j_coords(
                jamlet.params, k_maddr.k_index, k_maddr.j_in_k_index)
        else:
            addr = request.g_addr.to_scalar_addr(jamlet.tlb)
            target_x, target_y = 0, -1

        header = ReadMemWordHeader(
            target_x=target_x,
            target_y=target_y,
            source_x=jamlet.x,
            source_y=jamlet.y,
            message_type=MessageType.READ_MEM_WORD_REQ,
            send_type=SendType.SINGLE,
            length=2,
            ident=ident,
            tag=tag,
            element_index=dst_e,
            ordered=self.is_ordered(),
        )
        packet = [header, addr]
        logger.debug(f'{jamlet.clock.cycle}: {self.__class__.__name__} send_req: '
                     f'jamlet ({jamlet.x},{jamlet.y}) ident={instr.instr_ident} tag={tag} '
                     f'-> ({target_x},{target_y}) is_vpu={request.is_vpu}')

        witem_span_id = jamlet.monitor.get_witem_span_id(
            instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)

        transaction_span_id = jamlet.monitor.create_transaction(
            transaction_type='ReadMemWord',
            ident=ident,
            src_x=jamlet.x,
            src_y=jamlet.y,
            dst_x=target_x,
            dst_y=target_y,
            tag=tag,
            parent_span_id=witem_span_id,
        )

        await jamlet.send_packet(packet, parent_span_id=transaction_span_id)
        return True

    def _synchronize(self, kamlet):
        assert self.instr_ident is not None
        kamlet.synchronizer.local_event(self.instr_ident)
