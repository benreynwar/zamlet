'''
When we load an element from an arbitrary location we need to:

Work out if it crosses a page boundary.

Get the page_info for the two pages (one if doesn't cross a boundary).

Get the element widths for the two pages.

We have 8 tags because we potentially have a 64 bit element with 8 bit source data.
so we need to read from 8 jamlets to gather the data.
We could also have 16 bit source data with an 8 bit offset that also spread the element
over 8 words. The result is the same. We need at most 8 tags.
We assume that the src page is not ew=1.
'''

from typing import List, Any
from dataclasses import dataclass
import logging

from zamlet import addresses
from zamlet.waiting_item import WaitingItem
from zamlet.message import TaggedHeader, MessageType, SendType
from zamlet.kamlet.cache_table import SendState
from zamlet.params import LamletParams
from zamlet.jamlet.jamlet import Jamlet
from zamlet import utils
from zamlet.kamlet.kinstructions import KInstr


logger = logging.getLogger(__name__)


@dataclass
class LoadStride(KInstr):
    """
    A load from the VPU memory into a vector register.
    The k_maddr points to the location of the start_index element.

    stride_bytes: byte stride between elements. None = unit stride (ew/8 bytes).

    n_elements is limited to j_in_l
    This is because we if we have multiple elements for one jamlet that it
    gets hard to keep track of the meta information (i.e. like the ew of the src page).
    If we have only one element for each jamlet we can track this information simply
    in the Waiting Item.
    """
    dst: int
    # The address of the start_index element in the global address space.
    # src ordering will be looked up in TLB
    g_addr: addresses.GlobalAddress
    start_index: int
    n_elements: int
    dst_ordering: addresses.Ordering
    mask_reg: int|None
    writeset_ident: int
    instr_ident: int
    stride_bytes: int|None = None

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x}, {kamlet.min_y}): load_stride.update_kamlet addr={hex(self.g_addr.addr)} ident={self.instr_ident}')
        dst_regs = kamlet.get_regs(
                start_index=self.start_index, n_elements=self.n_elements,
                ew=self.dst_ordering.ew, base_reg=self.dst)
        if self.mask_reg is not None:
            read_regs = [self.mask_reg]
        else:
            read_regs = []
        await kamlet.wait_for_rf_available(write_regs=dst_regs, read_regs=read_regs)
        rf_write_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=dst_regs)
        witem = WaitingLoadStride(
                params=kamlet.params, instr=self, rf_ident=rf_write_ident)
        await kamlet.cache_table.add_witem(witem=witem)


class WaitingLoadStride(WaitingItem):

    def __init__(self, instr: LoadStride, params: LamletParams, rf_ident: int|None=None):
        super().__init__(item=instr, instr_ident=instr.instr_ident, rf_ident=rf_ident)
        self.writeset_ident = instr.writeset_ident
        n_tags = params.word_bytes
        self.transaction_states: List[SendState] = [SendState.NEED_TO_SEND for _ in range(n_tags)]
        self.synchronized = False

    def ready_to_synchronize(self) -> bool:
        return all(state == SendState.COMPLETE for state in self.transaction_states)

    def ready(self) -> bool:
        return self.synchronized

    def n_tags(self, params: LamletParams) -> int:
        return self.item.n_tags(params) * params.j_in_k


@dataclass
class RequiredBytes:
    is_vpu: bool
    g_addr: addresses.GlobalAddress
    n_bytes: int
    tag: int


def get_request(jamlet: Jamlet, instr: LoadStride, tag: int):
    dst_vw = addresses.j_coords_to_vw_index(
            jamlet.params, word_order=instr.dst_ordering.word_order, j_x=jamlet.x, j_y=jamlet.y)
    dst_ew = instr.dst_ordering.ew
    dst_wb = tag * 8
    assert (dst_ew % 8) == 0
    dst_eb = dst_wb % dst_ew
    dst_we = dst_wb // dst_ew
    dst_ve = dst_we * jamlet.params.j_in_l + dst_vw
    # Where is this byte in the src memory?
    src_g_addr = (instr.g_addr.bit_offset(
        (dst_ve - instr.start_index) * instr.stride_bytes * 8 + dst_eb))
    src_page_info = jamlet.tlb.get_page_info(src_g_addr)
    page_byte_offset = src_g_addr.addr % jamlet.params.page_bytes
    remaining_page_bytes = jamlet.params.page_bytes - page_byte_offset
    if not src_page_info.local_address.is_vpu:
        # This byte is in the scalar memory.
        # All of the destination element that is on this page is put in one request.
        # This tag will produce a null-request if it isn't the first byte of this element on
        # this page.
        if dst_eb == 0 or page_byte_offset == 0:
            n_bytes = min(remaining_page_bytes, dst_ew//8)
            return RequiredBytes(is_vpu=False, g_addr=src_g_addr, n_bytes=n_bytes, tag=tag)
        else:
            return None
    else:
        # This byte is in the VPU memory.
        assert src_page_info.local_address.ordering is not None
        src_ew = src_page_info.local_address.ordering.ew
        src_eb = src_g_addr.bit_addr % src_ew
        # This tag will only produce a request if this is the first byte in a dst element
        # a src element, or the page
        if src_eb == 0 or dst_eb == 0 or page_byte_offset == 0:
            n_bytes = min((src_ew-src_eb)//8, (dst_ew-dst_eb)//8, remaining_page_bytes)
            return RequiredBytes(is_vpu=True, g_addr=src_g_addr, n_bytes=n_bytes, tag=tag)
        else:
            return None


async def send_req(jamlet: Jamlet, witem: WaitingLoadStride, tag: int) -> None:
    assert tag < witem.n_tags(jamlet.params)
    instr = witem.item
    request = get_request(jamlet, instr, tag)
    if request is None:
        return
    k_maddr = request.g_addr.to_k_maddr(jamlet.tlb)
    word_offset = k_maddr.addr % jamlet.params.word_bytes
    word_addr = k_maddr.bit_offset(-word_offset * 8)
    target_x, target_y = addresses.k_indices_to_j_coords(
            jamlet.params, k_maddr.k_index, k_maddr.j_in_k_index)
    header = TaggedHeader(
        target_x=target_x,
        target_y=target_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        message_type=MessageType.READ_MEM_WORD_REQ,
        send_type=SendType.SINGLE,
        length=2,
        ident=instr.instr_ident,
        tag=tag,
        )
    packet = [header, word_addr]
    await jamlet.send_packet(packet)


def process_resp(jamlet: Jamlet, packet: List[Any]):
    wb = jamlet.params.word_bytes
    header = packet[0]
    data = packet[1]
    assert isinstance(header, TaggedHeader)
    witem = jamlet.cache_table.get_waiting_item_by_instr_ident(header.ident)
    assert isinstance(witem, WaitingLoadStride)
    instr = witem.item
    state = witem.transaction_states[header.tag]
    assert state == SendState.WAITING_FOR_RESPONSE
    state = SendState.COMPLETE
    request = get_request(jamlet, instr, header.tag)
    assert request is not None
    k_maddr = request.g_addr.to_k_maddr(jamlet.tlb)
    src_byte_in_word = k_maddr.addr % wb
    dst_byte_in_word = header.tag

    old_word = jamlet.rf_slice[instr.dst * wb: (instr.dst+1) * wb]
    new_word = utils.shift_and_update_word(
            old_word=old_word,
            src_word=data,
            src_start=src_byte_in_word,
            dst_start=dst_byte_in_word,
            n_bytes=request.n_bytes,
            )
    jamlet.rf_slice[instr.dst * wb: (instr.dst+1) * wb] = new_word
