'''
Ordered indexed load - single element handler.

When lamlet dispatches LoadIndexedElement to a kamlet, the jamlet that owns
the element:
1. Reads the index from index_reg to compute the address
2. Sends ReadMemWordReq(s) to either another jamlet (VPU memory) or lamlet (scalar memory)
   - An element may span multiple source words, requiring multiple requests
3. Receives data via ReadMemWordResp for each tag
4. Writes data to dst_reg
5. Sends LOAD_INDEXED_ELEMENT_RESP to lamlet to free the buffer slot
'''
from typing import TYPE_CHECKING, List
import logging
from dataclasses import dataclass

from zamlet import addresses
from zamlet.addresses import GlobalAddress, TLBFaultType
from zamlet.waiting_item import WaitingItem
from zamlet.kamlet.kinstructions import TrackedKInstr
from zamlet.message import (
    MessageType, SendType, ReadMemWordHeader, ElementIndexHeader, TaggedHeader
)
from zamlet.kamlet.cache_table import SendState
from zamlet import utils
from zamlet.transactions.helpers import read_element

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


@dataclass
class RequiredBytes:
    is_vpu: bool
    g_addr: addresses.GlobalAddress
    n_bytes: int
    tag: int


@dataclass
class LoadIndexedElement(TrackedKInstr):
    """
    Ordered indexed load - load a single element.

    Sent by lamlet to the jamlet that owns this element. The jamlet reads
    the index from index_reg, computes the address, and either:
    - Sends ReadMemWordReq to another jamlet (VPU memory)
    - Sends ReadMemWordReq to the lamlet (scalar memory)

    An element may span multiple source words requiring multiple requests.

    After receiving all data, writes to dst_reg and sends
    LOAD_INDEXED_ELEMENT_RESP back to the lamlet.

    If mask_reg is set and the element's mask bit is 0, immediately sends
    LOAD_INDEXED_ELEMENT_RESP with masked=True without doing any work.
    """
    dst_reg: int
    index_reg: int
    index_ew: int
    data_ew: int
    element_index: int
    base_addr: GlobalAddress
    word_order: addresses.WordOrder
    instr_ident: int
    parent_ident: int  # Barrier instruction ident for ordering
    mask_reg: int | None = None

    async def update_kamlet(self, kamlet):
        await handle_load_indexed_element(kamlet, self)


def _get_mask_bit(jamlet: 'Jamlet', mask_reg: int, element_index: int) -> bool:
    """Read the mask bit for an element from the mask register.

    Returns True if the element is active (should be processed).
    """
    wb = jamlet.params.word_bytes
    bit_index = element_index // jamlet.params.j_in_l
    byte_index = bit_index // 8
    bit_in_byte = bit_index % 8
    mask_byte = jamlet.rf_slice[mask_reg * wb + byte_index]
    return bool((mask_byte >> bit_in_byte) & 1)


def _check_element_access(jamlet: 'Jamlet', instr: 'LoadIndexedElement') -> TLBFaultType:
    """Check TLB access for all bytes of the element. Returns fault type or NONE."""
    index_data = read_element(jamlet, instr.index_reg, instr.element_index, instr.index_ew)
    byte_offset = int.from_bytes(index_data, byteorder='little', signed=False)

    element_bytes = instr.data_ew // 8
    page_bytes = jamlet.params.page_bytes

    current_byte = 0
    while current_byte < element_bytes:
        g_addr = instr.base_addr.bit_offset((byte_offset + current_byte) * 8)
        fault_type = jamlet.tlb.check_access(g_addr, is_write=False)
        if fault_type != TLBFaultType.NONE:
            return fault_type
        # Skip to next page
        page_offset = g_addr.addr % page_bytes
        remaining_in_page = page_bytes - page_offset
        current_byte += remaining_in_page

    return TLBFaultType.NONE


async def handle_load_indexed_element(kamlet: 'Kamlet',
                                       instr: LoadIndexedElement):
    """Handle LoadIndexedElement instruction at kamlet level.

    Find the jamlet that owns this element and create a waiting item for it.
    If masked, immediately send response without doing any work.
    """
    params = kamlet.params
    data_ew = instr.data_ew
    index_ew = instr.index_ew
    element_index = instr.element_index

    elements_in_vline = params.vline_bytes * 8 // data_ew
    vw_index = element_index % params.j_in_l
    k_index, j_in_k_index = addresses.vw_index_to_k_indices(
        params, instr.word_order, vw_index)

    assert k_index == kamlet.k_index, \
        f"LoadIndexedElement sent to wrong kamlet: expected {k_index}, got {kamlet.k_index}"

    jamlet = kamlet.jamlets[j_in_k_index]

    # Check mask - if element is masked, immediately send response
    is_masked = (instr.mask_reg is not None and
                 not _get_mask_bit(jamlet, instr.mask_reg, element_index))

    if is_masked:
        logger.debug(f'{kamlet.clock.cycle}: LoadIndexedElement masked: '
                     f'element={element_index} mask_reg={instr.mask_reg}')
        resp_header = ElementIndexHeader(
            target_x=jamlet.lamlet_x,
            target_y=jamlet.lamlet_y,
            source_x=jamlet.x,
            source_y=jamlet.y,
            message_type=MessageType.LOAD_INDEXED_ELEMENT_RESP,
            send_type=SendType.SINGLE,
            length=1,
            ident=instr.instr_ident,
            element_index=element_index,
            masked=True,
        )
        kinstr_span_id = kamlet.monitor.get_kinstr_span_id(instr.instr_ident)
        await jamlet.send_packet([resp_header], parent_span_id=kinstr_span_id)
        kamlet.monitor.finalize_kinstr_exec(instr.instr_ident, kamlet.min_x, kamlet.min_y)
    else:
        dst_regs = [instr.dst_reg + element_index // elements_in_vline]
        index_elements_in_vline = params.vline_bytes * 8 // index_ew
        index_regs = [instr.index_reg + element_index // index_elements_in_vline]
        read_regs = list(index_regs)

        await kamlet.wait_for_rf_available(write_regs=dst_regs, read_regs=read_regs,
                                           instr_ident=instr.instr_ident)
        rf_write_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=dst_regs)

        # Check TLB access - if fault, send fault response and release RF
        fault_type = _check_element_access(jamlet, instr)
        if fault_type != TLBFaultType.NONE:
            logger.debug(f'{kamlet.clock.cycle}: LoadIndexedElement fault: '
                         f'element={element_index} fault_type={fault_type}')
            kamlet.rf_info.finish(rf_write_ident, write_regs=dst_regs, read_regs=read_regs)
            resp_header = ElementIndexHeader(
                target_x=jamlet.lamlet_x,
                target_y=jamlet.lamlet_y,
                source_x=jamlet.x,
                source_y=jamlet.y,
                message_type=MessageType.LOAD_INDEXED_ELEMENT_RESP,
                send_type=SendType.SINGLE,
                length=1,
                ident=instr.instr_ident,
                element_index=element_index,
                fault=True,
            )
            kinstr_span_id = kamlet.monitor.get_kinstr_span_id(instr.instr_ident)
            await jamlet.send_packet([resp_header], parent_span_id=kinstr_span_id)
            kamlet.monitor.finalize_kinstr_exec(instr.instr_ident, kamlet.min_x, kamlet.min_y)
            return

        witem = WaitingLoadIndexedElement(
            instr=instr, params=params, rf_ident=rf_write_ident, j_in_k_index=j_in_k_index)
        kamlet.monitor.record_witem_created(
            instr.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingLoadIndexedElement',
            read_regs=read_regs, write_regs=dst_regs)
        await kamlet.cache_table.add_witem(witem=witem)


class WaitingLoadIndexedElement(WaitingItem):
    """Waiting item for ordered indexed element load.

    An element may span multiple source words (up to word_bytes tags).
    transaction_states tracks each tag's state.
    """

    def __init__(self, instr: LoadIndexedElement, params, rf_ident: int,
                 j_in_k_index: int):
        super().__init__(item=instr, instr_ident=instr.instr_ident, rf_ident=rf_ident)
        self.params = params
        self.j_in_k_index = j_in_k_index
        self.transaction_states: List[SendState] = [
            SendState.NEED_TO_SEND for _ in range(params.word_bytes)]
        self.resp_sent = False

    def ready(self) -> bool:
        return self.resp_sent

    def _all_transactions_complete(self) -> bool:
        return all(s == SendState.COMPLETE for s in self.transaction_states)

    async def monitor_jamlet(self, jamlet: 'Jamlet') -> None:
        if jamlet.j_in_k_index != self.j_in_k_index:
            return

        wb = jamlet.params.word_bytes
        for tag in range(wb):
            if self.transaction_states[tag] == SendState.NEED_TO_SEND:
                sent = await self._send_request(jamlet, tag)
                if sent:
                    self.transaction_states[tag] = SendState.WAITING_FOR_RESPONSE
                else:
                    self.transaction_states[tag] = SendState.COMPLETE

    async def monitor_kamlet(self, kamlet: 'Kamlet') -> None:
        if self.resp_sent:
            return
        if self._all_transactions_complete():
            jamlet = kamlet.jamlets[self.j_in_k_index]
            await self._send_resp_to_lamlet(jamlet)
            self.resp_sent = True

    def process_response(self, jamlet: 'Jamlet', packet) -> None:
        """Handle ReadMemWordResp - write data to RF."""
        if jamlet.j_in_k_index != self.j_in_k_index:
            return
        instr = self.item
        header = packet[0]
        assert isinstance(header, ReadMemWordHeader)
        tag = header.tag

        assert self.transaction_states[tag] == SendState.WAITING_FOR_RESPONSE
        self.transaction_states[tag] = SendState.COMPLETE

        # If faulted, skip the RF write - an earlier element faulted
        if header.fault:
            jamlet.monitor.complete_transaction(
                ident=header.ident, tag=tag,
                src_x=jamlet.x, src_y=jamlet.y,
                dst_x=header.source_x, dst_y=header.source_y)
            return

        data = packet[1]
        wb = jamlet.params.word_bytes
        data_ew = instr.data_ew

        request = self._get_request(jamlet, tag)
        assert request is not None

        if request.is_vpu:
            k_maddr = request.g_addr.to_k_maddr(jamlet.tlb)
            src_byte_in_word = k_maddr.addr % wb
        else:
            src_byte_in_word = request.g_addr.addr % wb

        dst_byte_in_word = tag

        element_index = instr.element_index
        elements_in_vline = jamlet.params.vline_bytes * 8 // data_ew
        element_in_jamlet = element_index // jamlet.params.j_in_l
        vline_index = element_in_jamlet // (wb * 8 // data_ew)
        dst_reg = instr.dst_reg + vline_index

        old_word = jamlet.rf_slice[dst_reg * wb: (dst_reg + 1) * wb]
        new_word = utils.shift_and_update_word(
            old_word=old_word,
            src_word=data,
            src_start=src_byte_in_word,
            dst_start=dst_byte_in_word,
            n_bytes=request.n_bytes,
        )
        jamlet.rf_slice[dst_reg * wb: (dst_reg + 1) * wb] = new_word

        witem_span_id = jamlet.monitor.get_witem_span_id(
            instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)
        assert witem_span_id is not None
        jamlet.monitor.add_event(
            witem_span_id,
            f'rf_write jamlet=({jamlet.x},{jamlet.y}) element={element_index} '
            f'tag={tag} reg={dst_reg} src_byte={src_byte_in_word} '
            f'dst_byte={dst_byte_in_word} n_bytes={request.n_bytes} '
            f'old={old_word.hex()} new={new_word.hex()}')
        jamlet.monitor.complete_transaction(
            ident=header.ident,
            tag=tag,
            src_x=jamlet.x,
            src_y=jamlet.y,
            dst_x=header.source_x,
            dst_y=header.source_y,
        )

    def process_drop(self, jamlet: 'Jamlet', packet) -> None:
        """Handle drop - need to resend."""
        if jamlet.j_in_k_index != self.j_in_k_index:
            return
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        tag = header.tag
        assert self.transaction_states[tag] == SendState.WAITING_FOR_RESPONSE
        self.transaction_states[tag] = SendState.NEED_TO_SEND

    async def finalize(self, kamlet: 'Kamlet') -> None:
        """Release RF after data received."""
        instr = self.item
        data_ew = instr.data_ew
        index_ew = instr.index_ew
        element_index = instr.element_index
        elements_in_vline = kamlet.params.vline_bytes * 8 // data_ew
        index_elements_in_vline = kamlet.params.vline_bytes * 8 // index_ew

        dst_regs = [instr.dst_reg + element_index // elements_in_vline]
        read_regs = [instr.index_reg + element_index // index_elements_in_vline]
        assert self.rf_ident is not None
        kamlet.rf_info.finish(self.rf_ident, write_regs=dst_regs, read_regs=read_regs)

    def _get_index_value(self, jamlet: 'Jamlet') -> int:
        """Read the byte offset from the index register."""
        instr = self.item
        index_data = read_element(jamlet, instr.index_reg, instr.element_index, instr.index_ew)
        return int.from_bytes(index_data, byteorder='little', signed=False)

    def _get_dst_byte_offset(self, jamlet: 'Jamlet') -> int:
        """Get the byte offset within the destination word for this element."""
        instr = self.item
        wb = jamlet.params.word_bytes
        data_ew = instr.data_ew
        element_index = instr.element_index

        element_in_jamlet = element_index // jamlet.params.j_in_l
        element_in_word = element_in_jamlet % (wb * 8 // data_ew)
        return element_in_word * (data_ew // 8)

    def _get_request(self, jamlet: 'Jamlet', tag: int) -> RequiredBytes | None:
        """Compute what bytes need to be fetched for this tag."""
        instr = self.item
        wb = jamlet.params.word_bytes
        data_ew = instr.data_ew
        element_bytes = data_ew // 8

        dst_byte_offset = self._get_dst_byte_offset(jamlet)

        if tag < dst_byte_offset or tag >= dst_byte_offset + element_bytes:
            return None

        src_eb = tag - dst_byte_offset

        byte_offset = self._get_index_value(jamlet)
        g_addr = instr.base_addr.bit_offset((byte_offset + src_eb) * 8)

        page_addr = g_addr.get_page()
        page_info = jamlet.tlb.get_page_info(page_addr)
        page_byte_offset = g_addr.addr % jamlet.params.page_bytes
        remaining_page_bytes = jamlet.params.page_bytes - page_byte_offset

        if not page_info.local_address.is_vpu:
            if src_eb == 0 or page_byte_offset == 0:
                n_bytes = min(remaining_page_bytes, element_bytes - src_eb)
                return RequiredBytes(is_vpu=False, g_addr=g_addr, n_bytes=n_bytes, tag=tag)
            else:
                return None
        else:
            assert page_info.local_address.ordering is not None
            src_ew = page_info.local_address.ordering.ew
            src_bit_in_element = g_addr.bit_addr % src_ew
            if src_bit_in_element == 0 or src_eb == 0 or page_byte_offset == 0:
                n_bytes = min((src_ew - src_bit_in_element) // 8,
                              element_bytes - src_eb, remaining_page_bytes)
                return RequiredBytes(is_vpu=True, g_addr=g_addr, n_bytes=n_bytes, tag=tag)
            else:
                return None

    async def _send_request(self, jamlet: 'Jamlet', tag: int) -> bool:
        """Send ReadMemWordReq to get the data for this tag. Returns True if sent."""
        instr = self.item
        request = self._get_request(jamlet, tag)
        if request is None:
            return False

        wb = jamlet.params.word_bytes
        msg_ident = (instr.instr_ident + tag + 1) % jamlet.params.max_response_tags

        if request.is_vpu:
            k_maddr = request.g_addr.to_k_maddr(jamlet.tlb)
            word_offset = k_maddr.addr % wb
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
            ident=msg_ident,
            tag=tag,
            element_index=instr.element_index,
            ordered=True,
            parent_ident=instr.parent_ident,
        )
        packet = [header, addr]

        witem_span_id = jamlet.monitor.get_witem_span_id(
            instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)
        assert witem_span_id is not None

        logger.debug(f'{jamlet.clock.cycle}: LoadIndexedElement _send_request: '
                     f'jamlet ({jamlet.x},{jamlet.y}) ident={instr.instr_ident} tag={tag} '
                     f'-> ({target_x},{target_y}) is_vpu={request.is_vpu}')

        transaction_span_id = jamlet.monitor.create_transaction(
            transaction_type='ReadMemWord',
            ident=msg_ident,
            src_x=jamlet.x,
            src_y=jamlet.y,
            dst_x=target_x,
            dst_y=target_y,
            tag=tag,
            parent_span_id=witem_span_id,
        )
        assert transaction_span_id is not None
        await jamlet.send_packet(packet, parent_span_id=transaction_span_id)
        return True

    async def _send_resp_to_lamlet(self, jamlet: 'Jamlet') -> None:
        """Send LOAD_INDEXED_ELEMENT_RESP to lamlet to free buffer slot."""
        instr = self.item
        kinstr_span_id = jamlet.monitor.get_kinstr_span_id(instr.instr_ident)

        resp_header = ElementIndexHeader(
            target_x=jamlet.lamlet_x,
            target_y=jamlet.lamlet_y,
            source_x=jamlet.x,
            source_y=jamlet.y,
            message_type=MessageType.LOAD_INDEXED_ELEMENT_RESP,
            send_type=SendType.SINGLE,
            length=1,
            ident=instr.instr_ident,
            element_index=instr.element_index,
        )
        await jamlet.send_packet([resp_header], parent_span_id=kinstr_span_id)
