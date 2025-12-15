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
from zamlet.kamlet.kinstructions import TrackedKInstr
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
    instr_ident: int
    mask_reg: int | None = None

    async def update_kamlet(self, kamlet):
        await handle_store_indexed_element(kamlet, self)


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


def _check_element_access(jamlet: 'Jamlet', instr: 'StoreIndexedElement') -> TLBFaultType:
    """Check TLB write access for all bytes of the element. Returns fault type or NONE."""
    index_data = read_element(jamlet, instr.index_reg, instr.element_index, instr.index_ew)
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


async def handle_store_indexed_element(kamlet: 'Kamlet',
                                        instr: StoreIndexedElement):
    """Handle StoreIndexedElement instruction at kamlet level.

    Find the jamlet that owns this element, read index and data, send response to lamlet.
    If masked, immediately send response without reading data.
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
        f"StoreIndexedElement sent to wrong kamlet: expected {k_index}, got {kamlet.k_index}"

    jamlet = kamlet.jamlets[j_in_k_index]

    # Check mask - if element is masked, immediately send response
    is_masked = (instr.mask_reg is not None and
                 not _get_mask_bit(jamlet, instr.mask_reg, element_index))

    if is_masked:
        logger.debug(f'{kamlet.clock.cycle}: StoreIndexedElement masked: '
                     f'element={element_index} mask_reg={instr.mask_reg}')
        header = ElementIndexHeader(
            target_x=jamlet.lamlet_x,
            target_y=jamlet.lamlet_y,
            source_x=jamlet.x,
            source_y=jamlet.y,
            message_type=MessageType.STORE_INDEXED_ELEMENT_RESP,
            send_type=SendType.SINGLE,
            length=1,
            ident=instr.instr_ident,
            element_index=element_index,
            masked=True,
        )
        kinstr_exec_span_id = kamlet.monitor.get_kinstr_exec_span_id(
            instr.instr_ident, kamlet.min_x, kamlet.min_y)
        assert kinstr_exec_span_id is not None
        await jamlet.send_packet([header], parent_span_id=kinstr_exec_span_id)
        kamlet.monitor.finalize_kinstr_exec(instr.instr_ident, kamlet.min_x, kamlet.min_y)
    else:
        src_regs = [instr.src_reg + element_index // elements_in_vline]
        index_elements_in_vline = params.vline_bytes * 8 // index_ew
        index_regs = [instr.index_reg + element_index // index_elements_in_vline]
        read_regs = list(src_regs) + list(index_regs)

        await kamlet.wait_for_rf_available(read_regs=read_regs, instr_ident=instr.instr_ident)
        rf_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=[])

        # Check TLB access - if fault, send fault response and release RF
        fault_type = _check_element_access(jamlet, instr)
        if fault_type != TLBFaultType.NONE:
            logger.debug(f'{kamlet.clock.cycle}: StoreIndexedElement fault: '
                         f'element={element_index} fault_type={fault_type}')
            kamlet.rf_info.finish(rf_ident, read_regs=read_regs, write_regs=[])
            header = ElementIndexHeader(
                target_x=jamlet.lamlet_x,
                target_y=jamlet.lamlet_y,
                source_x=jamlet.x,
                source_y=jamlet.y,
                message_type=MessageType.STORE_INDEXED_ELEMENT_RESP,
                send_type=SendType.SINGLE,
                length=1,
                ident=instr.instr_ident,
                element_index=element_index,
                fault=True,
            )
            kinstr_exec_span_id = kamlet.monitor.get_kinstr_exec_span_id(
                instr.instr_ident, kamlet.min_x, kamlet.min_y)
            assert kinstr_exec_span_id is not None
            await jamlet.send_packet([header], parent_span_id=kinstr_exec_span_id)
            kamlet.monitor.finalize_kinstr_exec(instr.instr_ident, kamlet.min_x, kamlet.min_y)
            return

        byte_offset = _get_index_value(jamlet, instr)
        data = _get_data_value(jamlet, instr)
        g_addr = instr.base_addr.bit_offset(byte_offset * 8)

        kamlet.rf_info.finish(rf_ident, read_regs=read_regs, write_regs=[])

        header = ElementIndexHeader(
            target_x=jamlet.lamlet_x,
            target_y=jamlet.lamlet_y,
            source_x=jamlet.x,
            source_y=jamlet.y,
            message_type=MessageType.STORE_INDEXED_ELEMENT_RESP,
            send_type=SendType.SINGLE,
            length=3,
            ident=instr.instr_ident,
            element_index=element_index,
        )
        packet = [header, g_addr.addr, data]

        kinstr_exec_span_id = kamlet.monitor.get_kinstr_exec_span_id(
            instr.instr_ident, kamlet.min_x, kamlet.min_y)
        assert kinstr_exec_span_id is not None
        await jamlet.send_packet(packet, parent_span_id=kinstr_exec_span_id)
        kamlet.monitor.finalize_kinstr_exec(instr.instr_ident, kamlet.min_x, kamlet.min_y)


def _get_index_value(jamlet: 'Jamlet', instr: StoreIndexedElement) -> int:
    """Read the byte offset from the index register."""
    index_data = read_element(jamlet, instr.index_reg, instr.element_index, instr.index_ew)
    return int.from_bytes(index_data, byteorder='little', signed=False)


def _get_data_value(jamlet: 'Jamlet', instr: StoreIndexedElement) -> bytes:
    """Read the data from the source register."""
    return read_element(jamlet, instr.src_reg, instr.element_index, instr.data_ew)
