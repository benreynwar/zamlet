'''
Ordered indexed load - single element handler.

When lamlet dispatches LoadIndexedElement to a kamlet, the jamlet that owns
the element:
1. Reads the index from index_reg to compute the address
2. Sends ReadMemWordReq to either another jamlet (VPU memory) or lamlet (scalar memory)
3. Receives data via ReadMemWordResp
4. Writes data to dst_reg
5. Sends LOAD_INDEXED_ELEMENT_RESP to lamlet to free the buffer slot
'''
from typing import TYPE_CHECKING
import logging
from dataclasses import dataclass

from zamlet import addresses
from zamlet.addresses import GlobalAddress
from zamlet.waiting_item import WaitingItem
from zamlet.kamlet.kinstructions import KInstr
from zamlet.message import (
    MessageType, SendType, ReadMemWordHeader, ElementIndexHeader, TaggedHeader
)
from zamlet.kamlet.cache_table import SendState

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


@dataclass
class LoadIndexedElement(KInstr):
    """
    Ordered indexed load - load a single element.

    Sent by lamlet to the jamlet that owns this element. The jamlet reads
    the index from index_reg, computes the address, and either:
    - Sends ReadMemWordReq to another jamlet (VPU memory)
    - Sends ReadMemWordReq to the lamlet (scalar memory)

    After receiving the data, writes to dst_reg and sends
    LOAD_INDEXED_ELEMENT_RESP back to the lamlet.
    """
    dst_reg: int
    index_reg: int
    index_ew: int
    data_ew: int
    element_index: int
    base_addr: GlobalAddress
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await handle_load_indexed_element(kamlet, self)


async def handle_load_indexed_element(kamlet: 'Kamlet',
                                       instr: LoadIndexedElement):
    """Handle LoadIndexedElement instruction at kamlet level.

    Find the jamlet that owns this element and create a waiting item for it.
    """
    params = kamlet.params
    data_ew = instr.data_ew
    index_ew = instr.index_ew
    element_index = instr.element_index

    elements_in_vline = params.vline_bytes * 8 // data_ew
    vw_index = element_index % params.j_in_l
    k_index, j_in_k_index = addresses.vw_index_to_k_indices(
        params, addresses.WordOrder.STANDARD, vw_index)

    assert k_index == kamlet.k_index, \
        f"LoadIndexedElement sent to wrong kamlet: expected {k_index}, got {kamlet.k_index}"

    dst_regs = [instr.dst_reg + element_index // elements_in_vline]
    index_elements_in_vline = params.vline_bytes * 8 // index_ew
    index_regs = [instr.index_reg + element_index // index_elements_in_vline]
    read_regs = list(index_regs)

    await kamlet.wait_for_rf_available(write_regs=dst_regs, read_regs=read_regs,
                                       instr_ident=instr.instr_ident)
    rf_write_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=dst_regs)

    witem = WaitingLoadIndexedElement(
        instr=instr, params=params, rf_ident=rf_write_ident, j_in_k_index=j_in_k_index)
    kamlet.monitor.record_witem_created(
        instr.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingLoadIndexedElement')
    await kamlet.cache_table.add_witem(witem=witem)


@dataclass
class WaitingLoadIndexedElement(WaitingItem):
    """Waiting item for ordered indexed element load."""

    def __init__(self, instr: LoadIndexedElement, params, rf_ident: int,
                 j_in_k_index: int):
        super().__init__(item=instr, instr_ident=instr.instr_ident, rf_ident=rf_ident)
        self.params = params
        self.j_in_k_index = j_in_k_index
        self.send_state = SendState.NEED_TO_SEND
        self.data_received = False

    def ready(self) -> bool:
        return self.data_received

    async def monitor_jamlet(self, jamlet: 'Jamlet') -> None:
        if jamlet.j_in_k_index != self.j_in_k_index:
            return
        if self.send_state == SendState.NEED_TO_SEND:
            await self._send_request(jamlet)
            self.send_state = SendState.WAITING_FOR_RESPONSE

    def process_response(self, jamlet: 'Jamlet', packet) -> None:
        """Handle ReadMemWordResp - write data to RF."""
        if jamlet.j_in_k_index != self.j_in_k_index:
            return
        instr = self.item
        header = packet[0]
        data = packet[1]
        assert isinstance(header, TaggedHeader)

        wb = jamlet.params.word_bytes
        data_ew = instr.data_ew
        element_index = instr.element_index

        elements_in_vline = jamlet.params.vline_bytes * 8 // data_ew
        element_in_jamlet = element_index // jamlet.params.j_in_l
        vline_index = element_in_jamlet // (wb * 8 // data_ew)
        element_in_word = element_in_jamlet % (wb * 8 // data_ew)

        dst_reg = instr.dst_reg + vline_index
        byte_offset = element_in_word * (data_ew // 8)
        n_bytes = data_ew // 8

        old_word = jamlet.rf_slice[dst_reg * wb: (dst_reg + 1) * wb]
        new_word = bytearray(old_word)
        new_word[byte_offset:byte_offset + n_bytes] = data[:n_bytes]
        jamlet.rf_slice[dst_reg * wb: (dst_reg + 1) * wb] = bytes(new_word)

        witem_span_id = jamlet.monitor.get_witem_span_id(
            instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)
        assert witem_span_id is not None
        jamlet.monitor.add_event(
            witem_span_id,
            f'rf_write jamlet=({jamlet.x},{jamlet.y}) element={element_index} '
            f'reg={dst_reg} byte_offset={byte_offset} n_bytes={n_bytes} '
            f'old={old_word.hex()} new={bytes(new_word).hex()}')
        jamlet.monitor.complete_transaction(
            ident=header.ident,
            tag=header.tag,
            src_x=jamlet.x,
            src_y=jamlet.y,
            dst_x=header.source_x,
            dst_y=header.source_y,
        )

        self.send_state = SendState.COMPLETE
        self.data_received = True

    def process_drop(self, jamlet: 'Jamlet', packet) -> None:
        """Handle drop - need to resend."""
        if jamlet.j_in_k_index != self.j_in_k_index:
            return
        self.send_state = SendState.NEED_TO_SEND

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

    async def _send_request(self, jamlet: 'Jamlet') -> None:
        """Send ReadMemWordReq to get the data."""
        instr = self.item

        byte_offset = self._get_index_value(jamlet)
        g_addr = instr.base_addr.bit_offset(byte_offset * 8)

        page_addr = g_addr.get_page()
        page_info = jamlet.tlb.get_page_info(page_addr)

        if page_info.local_address.is_vpu:
            k_maddr = g_addr.to_k_maddr(jamlet.tlb)
            target_x, target_y = addresses.k_indices_to_j_coords(
                jamlet.params, k_maddr.k_index, k_maddr.j_in_k_index)
            addr = k_maddr
            is_vpu_target = True
        else:
            target_x, target_y = 0, -1
            addr = g_addr.to_scalar_addr(jamlet.tlb)
            is_vpu_target = False

        header = ReadMemWordHeader(
            target_x=target_x,
            target_y=target_y,
            source_x=jamlet.x,
            source_y=jamlet.y,
            message_type=MessageType.READ_MEM_WORD_REQ,
            send_type=SendType.SINGLE,
            length=2,
            ident=instr.instr_ident,
            tag=0,
            words_requested=1,
            element_index=instr.element_index,
            ordered=True,
        )
        packet = [header, addr]

        witem_span_id = jamlet.monitor.get_witem_span_id(
            instr.instr_ident, jamlet.k_min_x, jamlet.k_min_y)
        assert witem_span_id is not None
        transaction_span_id = jamlet.monitor.create_transaction(
            transaction_type='ReadMemWord',
            ident=instr.instr_ident,
            src_x=jamlet.x,
            src_y=jamlet.y,
            dst_x=target_x,
            dst_y=target_y,
            tag=0,
            parent_span_id=witem_span_id,
        )
        assert transaction_span_id is not None
        await jamlet.send_packet(packet, parent_span_id=transaction_span_id)

        if is_vpu_target:
            # VPU memory: lamlet doesn't process the request, so release its buffer slot now
            resp_header = ElementIndexHeader(
                target_x=0,
                target_y=-1,
                source_x=jamlet.x,
                source_y=jamlet.y,
                message_type=MessageType.LOAD_INDEXED_ELEMENT_RESP,
                send_type=SendType.SINGLE,
                length=1,
                ident=instr.instr_ident,
                element_index=instr.element_index,
            )
            await jamlet.send_packet([resp_header], parent_span_id=witem_span_id)

    def _get_index_value(self, jamlet: 'Jamlet') -> int:
        """Read the byte offset from the index register."""
        instr = self.item
        wb = jamlet.params.word_bytes
        index_ew = instr.index_ew
        index_bytes = index_ew // 8
        element_index = instr.element_index

        elements_in_vline = jamlet.params.vline_bytes * 8 // index_ew
        index_v = element_index // elements_in_vline
        index_ve = element_index % elements_in_vline
        index_we = index_ve // jamlet.params.j_in_l

        index_reg = instr.index_reg + index_v
        byte_in_word = (index_we * index_bytes) % wb

        word_data = jamlet.rf_slice[index_reg * wb: (index_reg + 1) * wb]
        index_value = int.from_bytes(word_data[byte_in_word:byte_in_word + index_bytes],
                                     byteorder='little', signed=False)
        return index_value
