'''
Strided Store Transaction

When we store an element to an arbitrary location we need to:
- Work out if it crosses a page boundary
- Get the page_info for the pages involved
- Get the element widths for the pages

We have 8 tags because we potentially have a 64 bit element with 8 bit destination data,
so we need to write to 8 jamlets to scatter the data.

This is the inverse of load_stride.py - data flows from register to memory.
'''

from typing import List, Any, TYPE_CHECKING
from dataclasses import dataclass
import logging

from zamlet import addresses
from zamlet.waiting_item import WaitingItem
from zamlet.message import WriteMemWordHeader, TaggedHeader, MessageType, SendType
from zamlet.kamlet.cache_table import SendState
from zamlet.params import LamletParams
from zamlet.kamlet.kinstructions import KInstr
from zamlet.synchronization import WaitingItemSyncState as SyncState

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet


logger = logging.getLogger(__name__)


@dataclass
class StoreStride(KInstr):
    """
    A store from a vector register to VPU memory with stride.
    The g_addr points to the location of the start_index element.

    stride_bytes: byte stride between elements in memory.

    n_elements is limited to j_in_l (same constraint as LoadStride).
    """
    src: int  # Source register
    g_addr: addresses.GlobalAddress  # Address of start_index element
    start_index: int
    n_elements: int
    src_ordering: addresses.Ordering  # Register ordering
    mask_reg: int | None
    writeset_ident: int
    instr_ident: int
    stride_bytes: int

    async def update_kamlet(self, kamlet):
        logger.debug(f'kamlet ({kamlet.min_x}, {kamlet.min_y}): store_stride.update_kamlet '
                     f'addr={hex(self.g_addr.addr)} ident={self.instr_ident}')
        src_regs = kamlet.get_regs(
            start_index=self.start_index, n_elements=self.n_elements,
            ew=self.src_ordering.ew, base_reg=self.src)
        if self.mask_reg is not None:
            read_regs = src_regs + [self.mask_reg]
        else:
            read_regs = src_regs
        await kamlet.wait_for_rf_available(write_regs=[], read_regs=read_regs)
        rf_read_ident = kamlet.rf_info.start(read_regs=read_regs, write_regs=[])
        witem = WaitingStoreStride(
            params=kamlet.params, instr=self, rf_ident=rf_read_ident)
        await kamlet.cache_table.add_witem(witem=witem)


class WaitingStoreStride(WaitingItem):

    writes_all_memory = True

    def __init__(self, instr: StoreStride, params: LamletParams, rf_ident: int | None = None):
        super().__init__(item=instr, instr_ident=instr.instr_ident, rf_ident=rf_ident)
        self.writeset_ident = instr.writeset_ident
        self.params = params
        # Each jamlet in the kamlet needs its own set of word_bytes tags
        n_tags = params.j_in_k * params.word_bytes
        self.transaction_states: List[SendState] = [SendState.NEED_TO_SEND for _ in range(n_tags)]
        self.sync_state = SyncState.NOT_STARTED

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
                sent = await send_req(jamlet, self, tag)
                if sent:
                    self.transaction_states[state_idx] = SendState.WAITING_FOR_RESPONSE
                else:
                    self.transaction_states[state_idx] = SendState.COMPLETE

    async def monitor_kamlet(self, kamlet) -> None:
        if self._ready_to_synchronize() and self.sync_state == SyncState.NOT_STARTED:
            self.sync_state = SyncState.IN_PROGRESS
            synchronize(kamlet, self)

    def process_response(self, jamlet: 'Jamlet', packet) -> None:
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        tag = header.tag
        state_idx = self._state_index(jamlet.j_in_k_index, tag)
        assert self.transaction_states[state_idx] == SendState.WAITING_FOR_RESPONSE
        self.transaction_states[state_idx] = SendState.COMPLETE
        logger.debug(f'{jamlet.clock.cycle}: StoreStride RESP: jamlet ({jamlet.x},{jamlet.y}) '
                     f'ident={self.instr_ident} tag={tag} complete')

    def process_drop(self, jamlet: 'Jamlet', packet) -> None:
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        tag = header.tag
        state_idx = self._state_index(jamlet.j_in_k_index, tag)
        assert self.transaction_states[state_idx] == SendState.WAITING_FOR_RESPONSE
        self.transaction_states[state_idx] = SendState.NEED_TO_SEND
        logger.debug(f'{jamlet.clock.cycle}: StoreStride DROP/RETRY: jamlet ({jamlet.x},{jamlet.y}) '
                     f'ident={self.instr_ident} tag={tag} will retry')

    async def finalize(self, kamlet) -> None:
        if self.rf_ident is not None:
            instr = self.item
            src_regs = kamlet.get_regs(
                start_index=instr.start_index, n_elements=instr.n_elements,
                ew=instr.src_ordering.ew, base_reg=instr.src)
            read_regs = src_regs + ([instr.mask_reg] if instr.mask_reg is not None else [])
            kamlet.rf_info.finish(self.rf_ident, write_regs=[], read_regs=read_regs)


@dataclass
class RequiredBytes:
    is_vpu: bool
    g_addr: addresses.GlobalAddress
    n_bytes: int
    tag: int


def compute_src_element(jamlet: 'Jamlet', instr: StoreStride, tag: int) -> tuple[int, int, int, int]:
    """Compute source element info for a given tag.

    Returns: (src_ve, src_e, src_eb, src_v)
        src_ve: element within vector line
        src_e: actual vector element index
        src_eb: byte within element
        src_v: vector line index (register offset from instr.src)
    """
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


def get_request(jamlet: 'Jamlet', instr: StoreStride, tag: int) -> RequiredBytes | None:
    """Determine what bytes need to be written for this tag."""
    src_ve, src_e, src_eb, src_v = compute_src_element(jamlet, instr, tag)
    src_ew = instr.src_ordering.ew
    elements_in_vline = jamlet.params.vline_bytes * 8 // src_ew
    assert instr.start_index <= src_e < instr.start_index + elements_in_vline

    # This jamlet may not have any elements to store for this instruction
    if src_e < instr.start_index or src_e >= instr.start_index + instr.n_elements:
        return None

    # Where does this byte go in the destination memory?
    dst_g_addr = (instr.g_addr.bit_offset(
        (src_e - instr.start_index) * instr.stride_bytes * 8 + src_eb))
    dst_page_addr = dst_g_addr.get_page()
    dst_page_info = jamlet.tlb.get_page_info(dst_page_addr)
    page_byte_offset = dst_g_addr.addr % jamlet.params.page_bytes
    remaining_page_bytes = jamlet.params.page_bytes - page_byte_offset

    if not dst_page_info.local_address.is_vpu:
        # Destination is in scalar memory
        if src_eb == 0 or page_byte_offset == 0:
            n_bytes = min(remaining_page_bytes, src_ew // 8)
            return RequiredBytes(is_vpu=False, g_addr=dst_g_addr, n_bytes=n_bytes, tag=tag)
        else:
            return None
    else:
        # Destination is in VPU memory
        assert dst_page_info.local_address.ordering is not None
        dst_ew = dst_page_info.local_address.ordering.ew
        dst_eb = dst_g_addr.bit_addr % dst_ew
        # Only produce a request if this is the first byte in a src element,
        # dst element, or page
        if dst_eb == 0 or src_eb == 0 or page_byte_offset == 0:
            n_bytes = min((dst_ew - dst_eb) // 8, (src_ew - src_eb) // 8, remaining_page_bytes)
            return RequiredBytes(is_vpu=True, g_addr=dst_g_addr, n_bytes=n_bytes, tag=tag)
        else:
            return None


async def send_req(jamlet: 'Jamlet', witem: WaitingStoreStride, tag: int) -> bool:
    """Send a WRITE_MEM_WORD_REQ for this tag. Returns True if request was sent."""
    assert tag < jamlet.params.word_bytes
    instr = witem.item
    request = get_request(jamlet, instr, tag)
    if request is None:
        return False

    wb = jamlet.params.word_bytes

    # Read source data from register file
    src_ve, src_e, src_eb, src_v = compute_src_element(jamlet, instr, tag)
    src_reg = instr.src + src_v
    src_word = jamlet.rf_slice[src_reg * wb: (src_reg + 1) * wb]

    # Calculate destination address
    k_maddr = request.g_addr.to_k_maddr(jamlet.tlb)
    word_offset = k_maddr.addr % wb
    word_addr = k_maddr.bit_offset(-word_offset * 8)

    target_x, target_y = addresses.k_indices_to_j_coords(
        jamlet.params, k_maddr.k_index, k_maddr.j_in_k_index)

    src_byte_in_word = tag
    dst_byte_in_word = k_maddr.addr % wb

    header = WriteMemWordHeader(
        target_x=target_x,
        target_y=target_y,
        source_x=jamlet.x,
        source_y=jamlet.y,
        message_type=MessageType.WRITE_MEM_WORD_REQ,
        send_type=SendType.SINGLE,
        length=3,
        ident=(instr.instr_ident + tag + 1) % jamlet.params.max_response_tags,
        tag=tag,
        dst_byte_in_word=dst_byte_in_word,
        n_bytes=request.n_bytes,
    )

    packet = [header, word_addr, src_word]

    logger.debug(f'{jamlet.clock.cycle}: StoreStride send_req: jamlet ({jamlet.x},{jamlet.y}) '
                 f'ident={instr.instr_ident} tag={tag} -> ({target_x},{target_y}) '
                 f'element={src_e} g_addr=0x{request.g_addr.addr:x} k_maddr=0x{word_addr.addr:x} '
                 f'src_byte={src_byte_in_word} dst_byte={dst_byte_in_word} n_bytes={request.n_bytes}')

    await jamlet.send_packet(packet)
    return True


def synchronize(kamlet, witem: WaitingStoreStride):
    assert witem.instr_ident is not None
    kamlet.synchronizer.local_event(witem.instr_ident)
