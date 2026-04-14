'''
Ordered indexed store - single element handler.

When lamlet dispatches StoreIndexedElement to a kamlet, the jamlet that owns
the element:
1. Reads the index from index_reg to compute the address
2. Reads the data from src_reg
3. Sends STORE_INDEXED_ELEMENT_RESP to lamlet with (address, data)

The lamlet handles the actual write to memory.
'''
from typing import TYPE_CHECKING
import logging
from dataclasses import dataclass

from zamlet import addresses
from zamlet.addresses import GlobalAddress, TLBFaultType
from zamlet.kamlet.kinstructions import TrackedKInstr, Renamed
from zamlet.message import MessageType, SendType, ElementIndexHeader
from zamlet.transactions.helpers import read_element

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


@dataclass
class StoreIndexedElement(TrackedKInstr):
    """
    Ordered indexed store - gather a single element.

    Sent by lamlet to the jamlet that owns this element. The jamlet reads
    the index from index_reg and the data from src_reg, then sends
    STORE_INDEXED_ELEMENT_RESP back to the lamlet with the address and data.
    The lamlet handles the actual write to memory.

    If mask_reg is set and the element's mask bit is 0, immediately sends
    STORE_INDEXED_ELEMENT_RESP with masked=True without reading any data.
    """
    src_reg: int
    index_reg: int
    index_ew: int
    data_ew: int
    element_index: int
    base_addr: GlobalAddress
    word_order: addresses.WordOrder
    instr_ident: int
    mask_reg: int | None = None

    async def admit(self, kamlet: 'Kamlet') -> 'StoreIndexedElement | None':
        params = kamlet.params
        data_ew = self.data_ew
        index_ew = self.index_ew
        element_index = self.element_index

        elements_in_vline = params.vline_bytes * 8 // data_ew
        vw_index = element_index % params.j_in_l
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
            params, self.word_order, vw_index)

        assert k_index == kamlet.k_index, \
            f"StoreIndexedElement sent to wrong kamlet: expected {k_index}, got {kamlet.k_index}"

        src_v = element_index // elements_in_vline
        index_elements_in_vline = params.vline_bytes * 8 // index_ew
        index_v = element_index // index_elements_in_vline

        src_preg = kamlet.r(self.src_reg + src_v)
        index_preg = kamlet.r(self.index_reg + index_v)
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None

        new = self.rename(
            src_pregs={index_v: index_preg},
            src2_pregs={src_v: src_preg},
            mask_preg=mask_preg,
        )
        new._j_in_k_index = j_in_k_index
        new._src_v = src_v
        new._index_v = index_v
        return new

    async def execute(self, kamlet: 'Kamlet') -> None:
        r = self.renamed
        jamlet = kamlet.jamlets[self._j_in_k_index]
        src_preg = r.src2_pregs[self._src_v]
        index_preg = r.src_pregs[self._index_v]

        rf_ident = kamlet.rf_info.start(
            read_regs=r.read_pregs, write_regs=r.write_pregs)

        if r.mask_preg is not None and not _get_mask_bit(
                jamlet, r.mask_preg, self.element_index):
            logger.debug(f'{kamlet.clock.cycle}: StoreIndexedElement masked: '
                         f'element={self.element_index} mask_reg={self.mask_reg}')
            kamlet.rf_info.finish(
                rf_ident, read_regs=r.read_pregs, write_regs=r.write_pregs)
            await _send_short_circuit_resp(kamlet, jamlet, self, masked=True)
            return

        fault_type = _check_element_access(jamlet, self, index_preg)
        if fault_type != TLBFaultType.NONE:
            logger.debug(f'{kamlet.clock.cycle}: StoreIndexedElement fault: '
                         f'element={self.element_index} fault_type={fault_type}')
            kamlet.rf_info.finish(
                rf_ident, read_regs=r.read_pregs, write_regs=r.write_pregs)
            await _send_short_circuit_resp(kamlet, jamlet, self, fault=True)
            return

        byte_offset = _get_index_value(jamlet, self, index_preg)
        data = _get_data_value(jamlet, self, src_preg)
        g_addr = self.base_addr.bit_offset(byte_offset * 8)

        kamlet.rf_info.finish(
            rf_ident, read_regs=r.read_pregs, write_regs=r.write_pregs)

        header = ElementIndexHeader(
            target_x=jamlet.lamlet_x,
            target_y=jamlet.lamlet_y,
            source_x=jamlet.x,
            source_y=jamlet.y,
            message_type=MessageType.STORE_INDEXED_ELEMENT_RESP,
            send_type=SendType.SINGLE,
            length=2,
            ident=self.instr_ident,
            element_index=self.element_index,
        )
        packet = [header, g_addr.addr, data]

        kinstr_exec_span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)
        assert kinstr_exec_span_id is not None
        await jamlet.send_packet(packet, parent_span_id=kinstr_exec_span_id)
        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y)


async def _send_short_circuit_resp(kamlet: 'Kamlet', jamlet: 'Jamlet',
                                   instr: 'StoreIndexedElement',
                                   masked: bool = False,
                                   fault: bool = False) -> None:
    """Send STORE_INDEXED_ELEMENT_RESP for a masked or faulted element and
    finalize the kinstr_exec span."""
    header = ElementIndexHeader(
        target_x=jamlet.lamlet_x,
        target_y=jamlet.lamlet_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        message_type=MessageType.STORE_INDEXED_ELEMENT_RESP,
        send_type=SendType.SINGLE,
        length=0,
        ident=instr.instr_ident,
        element_index=instr.element_index,
        masked=masked,
        fault=fault,
    )
    kinstr_exec_span_id = kamlet.monitor.get_kinstr_exec_span_id(
        instr.instr_ident, kamlet.min_x, kamlet.min_y)
    assert kinstr_exec_span_id is not None
    await jamlet.send_packet([header], parent_span_id=kinstr_exec_span_id)
    kamlet.monitor.finalize_kinstr_exec(
        instr.instr_ident, kamlet.min_x, kamlet.min_y)


def _get_mask_bit(jamlet: 'Jamlet', mask_preg: int, element_index: int) -> bool:
    """Read the mask bit for an element from the mask register (already
    resolved to a phys reg by the caller).

    Returns True if the element is active (should be processed).
    """
    wb = jamlet.params.word_bytes
    bit_index = element_index // jamlet.params.j_in_l
    byte_index = bit_index // 8
    bit_in_byte = bit_index % 8
    mask_byte = jamlet.rf_slice[mask_preg * wb + byte_index]
    return bool((mask_byte >> bit_in_byte) & 1)


def _check_element_access(jamlet: 'Jamlet', instr: 'StoreIndexedElement',
                          index_preg: int) -> TLBFaultType:
    """Check TLB write access for all bytes of the element. Returns fault type or NONE."""
    index_data = read_element(jamlet, index_preg, instr.element_index, instr.index_ew)
    byte_offset = int.from_bytes(index_data, byteorder='little', signed=False)

    element_bytes = instr.data_ew // 8
    page_bytes = jamlet.params.page_bytes

    current_byte = 0
    while current_byte < element_bytes:
        g_addr = instr.base_addr.bit_offset((byte_offset + current_byte) * 8)
        fault_type = jamlet.tlb.check_access(g_addr, is_write=True)
        if fault_type != TLBFaultType.NONE:
            return fault_type
        # Skip to next page
        page_offset = g_addr.addr % page_bytes
        remaining_in_page = page_bytes - page_offset
        current_byte += remaining_in_page

    return TLBFaultType.NONE


def _get_index_value(jamlet: 'Jamlet', instr: StoreIndexedElement,
                     index_preg: int) -> int:
    """Read the byte offset from the index register."""
    index_data = read_element(jamlet, index_preg, instr.element_index, instr.index_ew)
    return int.from_bytes(index_data, byteorder='little', signed=False)


def _get_data_value(jamlet: 'Jamlet', instr: StoreIndexedElement,
                    src_preg: int) -> int:
    """Read the data from the source register as an int for packet transmission."""
    data = read_element(jamlet, src_preg, instr.element_index, instr.data_ew)
    return int.from_bytes(data, 'little')
