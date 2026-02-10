'''
Base class for scatter-style stores (strided and indexed).

Both StoreStride and StoreIndexedUnordered store elements from contiguous register
positions to non-contiguous memory locations. The only difference is how the
destination address is computed:
- StoreStride: base + (element_index * stride_bytes)
- StoreIndexed: base + index_register[element_index]

This module provides the shared implementation.

Two-phase synchronization:
1. Fault sync: Aggregates minimum faulting element across all kamlets
2. Completion sync: Waits for all transactions to finish

For non-idempotent memory, writes are delayed until fault sync completes,
then only elements < min_fault are written.
'''

from abc import ABC, abstractmethod
from typing import List, TYPE_CHECKING
from dataclasses import dataclass
import logging

from zamlet import addresses
from zamlet.addresses import TLBFaultType, MemoryType
from zamlet.waiting_item import WaitingItem
from zamlet.message import WriteMemWordHeader, TaggedHeader, MessageType, SendType
from zamlet.kamlet.cache_table import SendState
from zamlet.params import LamletParams
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


class WaitingStoreScatterBase(WaitingItem, ABC):
    """Base class for scatter-style store waiting items (strided and indexed)."""

    writes_all_memory = True

    def __init__(self, instr, params: LamletParams, rf_ident: int | None = None):
        super().__init__(item=instr, instr_ident=instr.instr_ident, rf_ident=rf_ident)
        self.writeset_ident = instr.writeset_ident
        self.params = params
        n_tags = params.j_in_k * params.word_bytes
        self.transaction_states: List[SendState] = [SendState.INITIAL for _ in range(n_tags)]
        self.fault_sync_state = SyncState.NOT_STARTED
        self.completion_sync_state = SyncState.NOT_STARTED
        # Track minimum faulting element (for TLB permission faults)
        self.min_fault_element: int | None = None
        # Global min fault element after fault sync completes
        self.global_min_fault: int | None = None

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

    def _state_index(self, j_in_k_index: int, tag: int) -> int:
        return j_in_k_index * self.params.word_bytes + tag

    def ready(self) -> bool:
        return self.completion_sync_state == SyncState.COMPLETE

    async def monitor_jamlet(self, jamlet: 'Jamlet') -> None:
        wb = jamlet.params.word_bytes
        for tag in range(wb):
            state_idx = self._state_index(jamlet.j_in_k_index, tag)
            state = self.transaction_states[state_idx]

            if state == SendState.INITIAL:
                request = self._get_request(jamlet, tag)
                if request is None:
                    self.transaction_states[state_idx] = SendState.COMPLETE
                elif request.g_addr is None:
                    # Unallocated page - record fault
                    _, src_e, _, _ = self._compute_src_element(jamlet, tag)
                    if self.min_fault_element is None or src_e < self.min_fault_element:
                        self.min_fault_element = src_e
                    self.transaction_states[state_idx] = SendState.COMPLETE
                else:
                    page_info = jamlet.tlb.get_page_info(request.g_addr.get_page())
                    if page_info.local_address.memory_type != MemoryType.SCALAR_NON_IDEMPOTENT:
                        self.transaction_states[state_idx] = SendState.NEED_TO_SEND
                    else:
                        self.transaction_states[state_idx] = SendState.WAITING_IN_CASE_FAULT

            elif state == SendState.WAITING_IN_CASE_FAULT:
                if self.fault_sync_state == SyncState.COMPLETE:
                    _, src_e, _, _ = self._compute_src_element(jamlet, tag)
                    if self.global_min_fault is not None and src_e >= self.global_min_fault:
                        self.transaction_states[state_idx] = SendState.COMPLETE
                    else:
                        self.transaction_states[state_idx] = SendState.NEED_TO_SEND

            elif state == SendState.NEED_TO_SEND:
                before = jamlet.clock.cycle
                sent = await self._send_req(jamlet, tag)
                after = jamlet.clock.cycle
                if sent:
                    self.transaction_states[state_idx] = SendState.WAITING_FOR_RESPONSE
                    if after > before:
                        logger.info(
                            f'{after}: scatter[{self.instr_ident}] '
                            f'jamlet ({jamlet.x},{jamlet.y}) tag={tag} '
                            f'send blocked {after - before} cycles')
                else:
                    self.transaction_states[state_idx] = SendState.COMPLETE

    async def monitor_kamlet(self, kamlet) -> None:
        # Use instr_ident for fault sync, instr_ident + 1 for completion sync
        fault_sync_ident = self.instr_ident
        completion_sync_ident = (self.instr_ident + 1) % self.params.max_response_tags
        kinstr_span_id = kamlet.monitor.get_kinstr_span_id(self.instr_ident)

        # Fault sync - after all INITIAL checks done
        if self.fault_sync_state == SyncState.NOT_STARTED:
            if all(s != SendState.INITIAL for s in self.transaction_states):
                self.fault_sync_state = SyncState.IN_PROGRESS
                kamlet.monitor.create_sync_local_span(
                    fault_sync_ident, kamlet.synchronizer.x, kamlet.synchronizer.y,
                    kinstr_span_id)
                kamlet.synchronizer.local_event(fault_sync_ident, value=self.min_fault_element)
        elif self.fault_sync_state == SyncState.IN_PROGRESS:
            if kamlet.synchronizer.is_complete(fault_sync_ident):
                self.fault_sync_state = SyncState.COMPLETE
                self.global_min_fault = kamlet.synchronizer.get_min_value(fault_sync_ident)

        # Completion sync - after all transactions complete (independent of fault sync)
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
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        tag = header.tag
        state_idx = self._state_index(jamlet.j_in_k_index, tag)
        assert self.transaction_states[state_idx] == SendState.WAITING_FOR_RESPONSE
        self.transaction_states[state_idx] = SendState.COMPLETE
        logger.debug(f'{jamlet.clock.cycle}: {self.__class__.__name__} RESP: '
                     f'jamlet ({jamlet.x},{jamlet.y}) ident={self.instr_ident} tag={tag} complete')
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
        logger.debug(f'{jamlet.clock.cycle}: {self.__class__.__name__} DROP/RETRY: '
                     f'jamlet ({jamlet.x},{jamlet.y}) ident={self.instr_ident} tag={tag} will resend')

    async def finalize(self, kamlet) -> None:
        instr = self.item
        src_regs = kamlet.get_regs(
            start_index=instr.start_index, n_elements=instr.n_elements,
            ew=instr.src_ordering.ew, base_reg=instr.src)
        read_regs = list(src_regs) + self.get_additional_read_regs(kamlet)
        if instr.mask_reg is not None:
            read_regs.append(instr.mask_reg)
        kamlet.rf_info.finish(self.rf_ident, write_regs=[], read_regs=read_regs)

    def _compute_src_element(self, jamlet: 'Jamlet', tag: int) -> tuple[int, int, int, int]:
        """Compute source element info for a given tag.

        Returns: (src_ve, src_e, src_eb, src_v)
            src_ve: element within vector line
            src_e: actual vector element index
            src_eb: byte within element
            src_v: vector line index (register offset from instr.src)
        """
        instr = self.item
        src_vw = addresses.j_coords_to_vw_index(
            jamlet.params, word_order=instr.src_ordering.word_order, j_x=jamlet.x, j_y=jamlet.y)
        src_ew = instr.src_ordering.ew
        src_wb = tag * 8
        assert (src_ew % 8) == 0
        src_eb = src_wb % src_ew
        src_we = src_wb // src_ew
        src_ve = src_we * jamlet.params.j_in_l + src_vw
        elements_in_vline = jamlet.params.vline_bytes * 8 // src_ew
        if src_ve < instr.start_index % elements_in_vline:
            src_v = instr.start_index // elements_in_vline + 1
        else:
            src_v = instr.start_index // elements_in_vline
        src_e = src_v * elements_in_vline + src_ve
        return (src_ve, src_e, src_eb, src_v)

    def _get_request(self, jamlet: 'Jamlet', tag: int) -> RequiredBytes | None:
        """Determine what bytes need to be written for this tag.

        Returns None if no write needed (out of range or masked).
        Returns RequiredBytes with g_addr=None if page is unallocated (fault).
        """
        instr = self.item
        src_ve, src_e, src_eb, src_v = self._compute_src_element(jamlet, tag)
        src_ew = instr.src_ordering.ew
        elements_in_vline = jamlet.params.vline_bytes * 8 // src_ew
        assert instr.start_index <= src_e < instr.start_index + elements_in_vline

        if src_e < instr.start_index or src_e >= instr.start_index + instr.n_elements:
            return None

        if instr.mask_reg is not None:
            wb = jamlet.params.word_bytes
            mask_word = int.from_bytes(
                jamlet.rf_slice[instr.mask_reg * wb: (instr.mask_reg + 1) * wb],
                byteorder='little')
            bit_index = src_e // jamlet.params.j_in_l
            mask_bit = (mask_word >> bit_index) & 1
            if not mask_bit:
                witem_span_id = jamlet.monitor.get_witem_span_id(
                    instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)
                jamlet.monitor.add_event(
                    witem_span_id, 'mask_skip',
                    jamlet_x=jamlet.x, jamlet_y=jamlet.y, element=src_e,
                    bit_index=bit_index, mask_word=hex(mask_word))
                return None

        # Get byte offset for this element (subclass-specific)
        element_byte_offset = self.get_element_byte_offset(jamlet, src_e)
        logger.debug(f'{jamlet.clock.cycle}: STORE _get_request: '
                     f'element={src_e} index_value={element_byte_offset}')

        # Compute destination address: base + element_byte_offset + byte_within_element
        dst_g_addr = instr.g_addr.bit_offset(element_byte_offset * 8 + src_eb)

        # Check TLB for write permission
        fault_type = jamlet.tlb.check_access(dst_g_addr, is_write=True)
        if fault_type != TLBFaultType.NONE:
            # Page fault - return empty RequiredBytes to signal fault
            return RequiredBytes(is_vpu=False, g_addr=None, n_bytes=0, tag=tag)

        dst_page_addr = dst_g_addr.get_page()
        dst_page_info = jamlet.tlb.get_page_info(dst_page_addr)

        page_byte_offset = dst_g_addr.addr % jamlet.params.page_bytes
        remaining_page_bytes = jamlet.params.page_bytes - page_byte_offset

        if not dst_page_info.local_address.is_vpu:
            if src_eb == 0 or page_byte_offset == 0:
                n_bytes = min(remaining_page_bytes, (src_ew - src_eb) // 8)
                return RequiredBytes(is_vpu=False, g_addr=dst_g_addr, n_bytes=n_bytes, tag=tag)
            else:
                return None
        else:
            assert dst_page_info.local_address.ordering is not None
            dst_ew = dst_page_info.local_address.ordering.ew
            dst_eb = dst_g_addr.bit_addr % dst_ew
            if dst_eb == 0 or src_eb == 0 or page_byte_offset == 0:
                n_bytes = min((dst_ew - dst_eb) // 8, (src_ew - src_eb) // 8, remaining_page_bytes)
                return RequiredBytes(is_vpu=True, g_addr=dst_g_addr, n_bytes=n_bytes, tag=tag)
            else:
                return None

    async def _send_req(self, jamlet: 'Jamlet', tag: int) -> bool:
        """Send a WRITE_MEM_WORD_REQ for this tag. Returns True if request was sent."""
        assert tag < jamlet.params.word_bytes
        instr = self.item
        request = self._get_request(jamlet, tag)
        if request is None or request.g_addr is None:
            return False

        wb = jamlet.params.word_bytes

        # Read source data from register file
        src_ve, src_e, src_eb, src_v = self._compute_src_element(jamlet, tag)
        src_reg = instr.src + src_v
        src_word = jamlet.rf_slice[src_reg * wb: (src_reg + 1) * wb]

        ident = (instr.instr_ident + tag + 1) % jamlet.params.max_response_tags

        if request.is_vpu:
            k_maddr = request.g_addr.to_k_maddr(jamlet.tlb)
            word_offset = k_maddr.addr % wb
            addr = k_maddr.bit_offset(-word_offset * 8)
            target_x, target_y = addresses.k_indices_to_j_coords(
                jamlet.params, k_maddr.k_index, k_maddr.j_in_k_index)
            dst_byte_in_word = k_maddr.addr % wb
        else:
            addr = request.g_addr.to_scalar_addr(jamlet.tlb)
            target_x, target_y = 0, -1
            dst_byte_in_word = addr % wb

        header = WriteMemWordHeader(
            target_x=target_x,
            target_y=target_y,
            source_x=jamlet.x,
            source_y=jamlet.y,
            message_type=MessageType.WRITE_MEM_WORD_REQ,
            send_type=SendType.SINGLE,
            length=3,
            ident=ident,
            tag=tag,
            dst_byte_in_word=dst_byte_in_word,
            n_bytes=request.n_bytes,
        )

        packet = [header, addr, src_word]

        logger.debug(f'{jamlet.clock.cycle}: {self.__class__.__name__} send_req: '
                     f'jamlet ({jamlet.x},{jamlet.y}) ident={instr.instr_ident} tag={tag} '
                     f'-> ({target_x},{target_y}) element={src_e} is_vpu={request.is_vpu} '
                     f'dst_byte={dst_byte_in_word} n_bytes={request.n_bytes}')

        witem_span_id = jamlet.monitor.get_witem_span_id(
            instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)

        transaction_span_id = jamlet.monitor.create_transaction(
            transaction_type='WriteMemWord',
            ident=ident,
            src_x=jamlet.x,
            src_y=jamlet.y,
            dst_x=target_x,
            dst_y=target_y,
            tag=tag,
            parent_span_id=witem_span_id,
            element=src_e,
        )

        await jamlet.send_packet(packet, parent_span_id=transaction_span_id)
        return True
