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
from zamlet.addresses import GlobalAddress
from zamlet.kamlet.kinstructions import KInstr
from zamlet.message import MessageType, SendType, ElementIndexHeader

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


@dataclass
class StoreIndexedElement(KInstr):
    """
    Ordered indexed store - gather a single element.

    Sent by lamlet to the jamlet that owns this element. The jamlet reads
    the index from index_reg and the data from src_reg, then sends
    STORE_INDEXED_ELEMENT_RESP back to the lamlet with the address and data.
    The lamlet handles the actual write to memory.
    """
    src_reg: int
    index_reg: int
    index_ew: int
    data_ew: int
    element_index: int
    base_addr: GlobalAddress
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await handle_store_indexed_element(kamlet, self)


async def handle_store_indexed_element(kamlet: 'Kamlet',
                                        instr: StoreIndexedElement):
    """Handle StoreIndexedElement instruction at kamlet level.

    Find the jamlet that owns this element, read index and data, send response to lamlet.
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

    src_regs = [instr.src_reg + element_index // elements_in_vline]
    index_elements_in_vline = params.vline_bytes * 8 // index_ew
    index_regs = [instr.index_reg + element_index // index_elements_in_vline]
    read_regs = list(src_regs) + list(index_regs)

    await kamlet.wait_for_rf_available(read_regs=read_regs, instr_ident=instr.instr_ident)
    rf_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=[])

    jamlet = kamlet.jamlets[j_in_k_index]
    byte_offset = _get_index_value(jamlet, instr)
    data = _get_data_value(jamlet, instr)
    g_addr = instr.base_addr.bit_offset(byte_offset * 8)

    kamlet.rf_info.finish(rf_ident, read_regs=read_regs, write_regs=[])

    header = ElementIndexHeader(
        target_x=0,
        target_y=-1,
        source_x=jamlet.x,
        source_y=jamlet.y,
        message_type=MessageType.STORE_INDEXED_ELEMENT_RESP,
        send_type=SendType.SINGLE,
        length=3,
        ident=instr.instr_ident,
        element_index=element_index,
    )
    packet = [header, g_addr.addr, data]

    kinstr_span_id = jamlet.monitor.get_kinstr_span_id(instr.instr_ident)
    assert kinstr_span_id is not None
    await jamlet.send_packet(packet, parent_span_id=kinstr_span_id)
    kamlet.monitor.finalize_kinstr_exec(instr.instr_ident, kamlet.min_x, kamlet.min_y)


def _get_index_value(jamlet: 'Jamlet', instr: StoreIndexedElement) -> int:
    """Read the byte offset from the index register."""
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


def _get_data_value(jamlet: 'Jamlet', instr: StoreIndexedElement) -> bytes:
    """Read the data from the source register."""
    wb = jamlet.params.word_bytes
    data_ew = instr.data_ew
    data_bytes = data_ew // 8
    element_index = instr.element_index

    elements_in_vline = jamlet.params.vline_bytes * 8 // data_ew
    element_in_jamlet = element_index // jamlet.params.j_in_l
    vline_index = element_in_jamlet // (wb * 8 // data_ew)
    element_in_word = element_in_jamlet % (wb * 8 // data_ew)

    src_reg = instr.src_reg + vline_index
    byte_offset = element_in_word * data_bytes

    word_data = jamlet.rf_slice[src_reg * wb: (src_reg + 1) * wb]
    return word_data[byte_offset:byte_offset + data_bytes]
