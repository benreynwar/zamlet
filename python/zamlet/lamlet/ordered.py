"""
Ordered indexed load/store operations for the lamlet.

Handles vloxei/vsoxei instructions where memory accesses must happen in element order.
The lamlet orchestrates element-by-element processing using ordered buffers.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from zamlet import addresses
from zamlet.addresses import GlobalAddress, Ordering, TLBFaultType, VectorOpResult
from zamlet.kamlet.cache_table import SendState
from zamlet.kamlet import kinstructions
from zamlet.lamlet.ordered_buffer import OrderedBuffer, ElementState
from zamlet.lamlet.lamlet_waiting_item import (
    LamletWaitingLoadIndexedElement, LamletWaitingStoreIndexedElement)
from zamlet.message import (
    MessageType, SendType, Direction, ReadMemWordHeader, WriteMemWordHeader,
    ElementIndexHeader, TaggedHeader)
from zamlet.synchronization import WaitingItemSyncState as SyncState
from zamlet.transactions.load_indexed_element import LoadIndexedElement
from zamlet.transactions.store_indexed_element import StoreIndexedElement
from zamlet.waiting_item import WaitingItem
from zamlet.lamlet import ident_query

if TYPE_CHECKING:
    from zamlet.kamlet.kamlet import Kamlet
    from zamlet.lamlet.lamlet import Lamlet
    from zamlet.lamlet.ordered_buffer import ElementEntry

logger = logging.getLogger(__name__)


@dataclass
class OrderedIndexedLoad(kinstructions.KInstr):
    """
    A barrier instruction sent to all kamlets before ordered indexed loads.
    Creates a waiting item that serves as the "parent" for READ_MEM_WORD ordering checks.
    """
    instr_ident: int

    async def update_kamlet(self, kamlet: 'Kamlet'):
        witem = WaitingOrderedIndexedLoad(self.instr_ident)
        kamlet.monitor.record_witem_created(
            self.instr_ident, kamlet.min_x, kamlet.min_y, 'WaitingOrderedIndexedLoad')
        await kamlet.cache_table.add_witem(witem)


class WaitingOrderedIndexedLoad(WaitingItem):
    """
    A waiting item that waits for all previous writes to complete.
    Serves as a synchronization point for ordered indexed load ordering checks.
    Uses sync network to stay alive until lamlet signals completion.
    """
    reads_all_memory = True

    def __init__(self, instr_ident: int):
        super().__init__(item=None, instr_ident=instr_ident)
        self.sync_state = SyncState.NOT_STARTED

    def ready(self) -> bool:
        return self.sync_state == SyncState.COMPLETE

    async def monitor_kamlet(self, kamlet: 'Kamlet') -> None:
        sync_ident = self.instr_ident
        kinstr_span_id = kamlet.monitor.get_kinstr_span_id(self.instr_ident)

        if self.sync_state == SyncState.NOT_STARTED:
            self.sync_state = SyncState.IN_PROGRESS
            kamlet.monitor.create_sync_local_span(
                sync_ident, kamlet.synchronizer.x, kamlet.synchronizer.y, kinstr_span_id)
            kamlet.synchronizer.local_event(sync_ident)
        elif self.sync_state == SyncState.IN_PROGRESS:
            if kamlet.synchronizer.is_complete(sync_ident):
                self.sync_state = SyncState.COMPLETE

    async def finalize(self, kamlet: 'Kamlet') -> None:
        kamlet.monitor.complete_witem(self.instr_ident, kamlet.min_x, kamlet.min_y)


def get_free_buffer_id(lamlet: 'Lamlet') -> int | None:
    """Find a free ordered buffer slot, or None if all are in use."""
    for i, buf in enumerate(lamlet._ordered_buffers):
        if buf is None:
            return i
    return None


def handle_load_indexed_element_resp(lamlet: 'Lamlet', header: ElementIndexHeader):
    """Handle LOAD_INDEXED_ELEMENT_RESP: complete element and release witem.

    For VPU loads: element is DISPATCHED (kamlet handled internally)
    For scalar loads: element is IN_FLIGHT (lamlet sent data, waiting for this RESP)
    For masked elements: element was skipped, just complete it
    For faulted elements: record fault, complete element
    """
    witem = lamlet.get_witem_by_ident(header.ident)
    assert witem is not None, f"No witem for ident {header.ident}"
    assert isinstance(witem, LamletWaitingLoadIndexedElement)
    buf = lamlet._ordered_buffers[witem.buffer_id]
    assert buf is not None, f"No ordered buffer for buffer_id {witem.buffer_id}"
    assert buf.is_load
    if header.fault:
        logger.debug(f'{lamlet.clock.cycle}: handle_load_indexed_element_resp: '
                     f'fault element={header.element_index}')
        if buf.faulted_element is None or header.element_index < buf.faulted_element:
            buf.faulted_element = header.element_index
    elif header.masked:
        logger.debug(f'{lamlet.clock.cycle}: handle_load_indexed_element_resp: '
                     f'masked element={header.element_index}')
    buf.complete_element(witem.element_index)
    lamlet.remove_witem_by_ident(header.ident)
    lamlet.monitor.complete_kinstr(header.ident)


def handle_store_indexed_element_resp(lamlet: 'Lamlet', header: ElementIndexHeader,
                                      addr: int | None, data: bytes | None):
    """Handle STORE_INDEXED_ELEMENT_RESP: buffer the write for in-order processing.

    For masked elements, addr and data are None - just complete the element.
    For faulted elements: record fault, complete element (no write occurs).
    """
    witem = lamlet.get_witem_by_ident(header.ident)
    assert witem is not None, f"No witem for ident {header.ident}"
    assert isinstance(witem, LamletWaitingStoreIndexedElement)
    buf = lamlet._ordered_buffers[witem.buffer_id]
    assert buf is not None, f"No ordered buffer for buffer_id {witem.buffer_id}"
    assert not buf.is_load

    if header.fault:
        logger.debug(f'{lamlet.clock.cycle}: handle_store_indexed_element_resp: '
                     f'fault element={header.element_index}')
        if buf.faulted_element is None or header.element_index < buf.faulted_element:
            buf.faulted_element = header.element_index
        buf.complete_element(witem.element_index)
        lamlet.remove_witem_by_ident(header.ident)
        lamlet.monitor.complete_kinstr(header.ident)
    elif header.masked:
        logger.debug(f'{lamlet.clock.cycle}: handle_store_indexed_element_resp: '
                     f'masked element={header.element_index}')
        buf.complete_element(witem.element_index)
        lamlet.remove_witem_by_ident(header.ident)
        lamlet.monitor.complete_kinstr(header.ident)
    else:
        assert addr is not None and data is not None
        g_addr = GlobalAddress(bit_addr=addr * 8, params=lamlet.params)
        entry = buf.get_entry(witem.element_index)
        entry.state = ElementState.READY
        entry.addr = g_addr
        entry.data = data


def handle_ordered_write_mem_word_resp(lamlet: 'Lamlet', header: TaggedHeader):
    """Handle WRITE_MEM_WORD_RESP for ordered store VPU writes."""
    parent_ident = (header.ident - header.tag - 1) % lamlet.params.max_response_tags
    witem = lamlet.get_witem_by_ident(parent_ident)
    assert witem is not None, \
        f"No witem for parent_ident {parent_ident} (msg ident {header.ident})"
    assert isinstance(witem, LamletWaitingStoreIndexedElement)
    buf = lamlet._ordered_buffers[witem.buffer_id]
    assert buf is not None, f"No ordered buffer for buffer_id {witem.buffer_id}"
    assert not buf.is_load
    entry = buf.get_entry(buf.next_to_process)
    assert entry.state == ElementState.IN_FLIGHT

    assert witem.transaction_states[header.tag] == SendState.WAITING_FOR_RESPONSE
    witem.transaction_states[header.tag] = SendState.COMPLETE
    lamlet.monitor.complete_transaction(
        header.ident, header.tag, lamlet.instr_x, lamlet.instr_y,
        header.source_x, header.source_y)

    if witem.all_complete():
        buf.complete_element(buf.next_to_process)
        lamlet.remove_witem_by_ident(parent_ident)
        lamlet.monitor.complete_kinstr(parent_ident)


def handle_ordered_write_mem_word_drop(lamlet: 'Lamlet', header: TaggedHeader):
    """Handle WRITE_MEM_WORD_DROP for ordered store VPU writes - retry later."""
    parent_ident = (header.ident - header.tag - 1) % lamlet.params.max_response_tags
    witem = lamlet.get_witem_by_ident(parent_ident)
    assert witem is not None, \
        f"No witem for parent_ident {parent_ident} (msg ident {header.ident})"
    assert isinstance(witem, LamletWaitingStoreIndexedElement)
    buf = lamlet._ordered_buffers[witem.buffer_id]
    assert buf is not None, f"No ordered buffer for buffer_id {witem.buffer_id}"
    assert not buf.is_load
    entry = buf.get_entry(buf.next_to_process)
    assert entry.state == ElementState.IN_FLIGHT
    assert witem.transaction_states[header.tag] == SendState.WAITING_FOR_RESPONSE
    witem.transaction_states[header.tag] = SendState.NEED_TO_SEND


def handle_ordered_write_mem_word_retry(lamlet: 'Lamlet', header: TaggedHeader):
    """Handle WRITE_MEM_WORD_RETRY for ordered store VPU writes - cache ready, resend."""
    parent_ident = (header.ident - header.tag - 1) % lamlet.params.max_response_tags
    witem = lamlet.get_witem_by_ident(parent_ident)
    assert witem is not None, \
        f"No witem for parent_ident {parent_ident} (msg ident {header.ident})"
    assert isinstance(witem, LamletWaitingStoreIndexedElement)
    buf = lamlet._ordered_buffers[witem.buffer_id]
    assert buf is not None, f"No ordered buffer for buffer_id {witem.buffer_id}"
    assert not buf.is_load
    entry = buf.get_entry(buf.next_to_process)
    assert entry.state == ElementState.IN_FLIGHT
    assert witem.transaction_states[header.tag] == SendState.WAITING_FOR_RESPONSE
    witem.transaction_states[header.tag] = SendState.NEED_TO_SEND


def handle_read_mem_word_req_ordered(lamlet: 'Lamlet', header: 'ReadMemWordHeader',
                                     scalar_addr: int):
    """Handle ordered READ_MEM_WORD_REQ: buffer request for in-order processing."""
    parent_ident = (header.ident - header.tag - 1) % lamlet.params.max_response_tags
    witem = lamlet.get_witem_by_ident(parent_ident)
    assert witem is not None, f"No witem for parent_ident {parent_ident} (msg ident {header.ident})"
    assert isinstance(witem, LamletWaitingLoadIndexedElement)
    buf = lamlet._ordered_buffers[witem.buffer_id]
    assert buf is not None, f"No ordered buffer for buffer_id {witem.buffer_id}"
    assert buf.is_load
    entry = buf.get_entry(witem.element_index)
    entry.state = ElementState.READY
    entry.addr = scalar_addr
    entry.tag = header.tag
    transaction_span_id = lamlet.monitor.get_transaction_span_id(
        header.ident, header.tag, header.source_x, header.source_y, 0, -1)
    if transaction_span_id is not None:
        lamlet.monitor.add_event(
            transaction_span_id,
            f'ordered_req_buffered element={witem.element_index} '
            f'addr=0x{scalar_addr:x} next_to_process={buf.next_to_process}')


async def ordered_buffer_process(lamlet: 'Lamlet'):
    """Process pending requests/writes for active ordered buffers in element order."""
    while True:
        await lamlet.clock.next_cycle
        for buffer_id, buf in enumerate(lamlet._ordered_buffers):
            if buf is None:
                continue
            if buf.all_complete():
                lamlet._ordered_buffers[buffer_id] = None
                continue

            # Check for in-flight VPU stores that need to send/resend tags
            entry = buf.get_entry(buf.next_to_process)
            if entry is not None and entry.state == ElementState.IN_FLIGHT and not buf.is_load:
                await _send_pending_vpu_writes(lamlet, buf)
                continue

            if entry is None or entry.state != ElementState.READY:
                continue
            # For stores: don't write elements at or after a fault - just complete them
            # For loads: still process (sends fault response with no data)
            if not buf.is_load and buf.faulted_element is not None and buf.next_to_process >= buf.faulted_element:
                buf.complete_element(buf.next_to_process)
                lamlet.remove_witem_by_ident(entry.instr_ident)
                lamlet.monitor.complete_kinstr(entry.instr_ident)
                continue
            if buf.is_load:
                await _process_ordered_load(lamlet, buf, entry)
            else:
                await _process_ordered_store(lamlet, buf, entry, buf.data_ew)


async def _process_ordered_load(lamlet: 'Lamlet', buf: OrderedBuffer, entry: 'ElementEntry'):
    """Process a ready ordered load element."""

    wb = lamlet.params.word_bytes
    element_index = buf.next_to_process
    target_x, target_y = _element_index_to_jamlet(lamlet, element_index)

    tag = entry.tag
    assert tag is not None
    msg_ident = (entry.instr_ident + tag + 1) % lamlet.params.max_response_tags

    # Skip actual read if we're at/after a fault
    skip_read = buf.faulted_element is not None and element_index >= buf.faulted_element

    if skip_read:
        data = None
    else:
        word_addr = entry.addr - (entry.addr % wb)
        data = lamlet.scalar.get_memory(word_addr, wb)

    resp_header = ReadMemWordHeader(
        target_x=target_x,
        target_y=target_y,
        source_x=lamlet.instr_x,
        source_y=lamlet.instr_y,
        message_type=MessageType.READ_MEM_WORD_RESP,
        send_type=SendType.SINGLE,
        length=1 if skip_read else 2,
        tag=tag,
        ident=msg_ident,
        fault=skip_read,
    )
    packet = [resp_header] if skip_read else [resp_header, data]
    jamlet = lamlet.kamlets[0].jamlets[0]
    transaction_span_id = lamlet.monitor.get_transaction_span_id(
        msg_ident, tag, target_x, target_y, lamlet.instr_x, lamlet.instr_y)
    if transaction_span_id is not None:
        if skip_read:
            lamlet.monitor.add_event(
                transaction_span_id,
                f'ordered_scalar_read element={element_index} SKIPPED (fault)')
        else:
            lamlet.monitor.add_event(
                transaction_span_id,
                f'ordered_scalar_read element={element_index} '
                f'addr=0x{entry.addr:x} data={data.hex()}')
    await lamlet.send_packet(packet, jamlet, Direction.N, port=0,
                             parent_span_id=transaction_span_id)
    # Mark in-flight and advance to next element
    entry.state = ElementState.IN_FLIGHT
    buf.next_to_process += 1
    # Don't remove witem here - wait for LOAD_INDEXED_ELEMENT_RESP from kamlet


async def _process_ordered_store(lamlet: 'Lamlet', buf: OrderedBuffer,
                                 entry: 'ElementEntry', src_ew: int):
    """Process a ready ordered store element.

    An element may span multiple pages with different types (scalar/VPU) and
    different element widths. We iterate through bytes, writing scalar chunks
    immediately and sending VPU writes as messages.
    """
    data = entry.data
    assert data is not None
    element_bytes = len(data)
    assert element_bytes * 8 == src_ew
    page_bytes = lamlet.params.page_bytes

    witem = lamlet.get_witem_by_ident(entry.instr_ident)
    assert isinstance(witem, LamletWaitingStoreIndexedElement)

    src_eb = 0
    has_vpu_writes = False

    while src_eb < element_bytes:
        dst_g_addr = entry.addr.bit_offset(src_eb * 8)
        page_info = lamlet.tlb.get_page_info(dst_g_addr.get_page())
        remaining_element_bytes = element_bytes - src_eb

        if page_info.local_address.is_vpu:
            assert page_info.local_address.ordering is not None
            dst_ew = page_info.local_address.ordering.ew
            dst_eb = dst_g_addr.bit_addr % dst_ew
            n_bytes = min((dst_ew - dst_eb) // 8, remaining_element_bytes)
            has_vpu_writes = True
            witem.transaction_states[src_eb] = SendState.NEED_TO_SEND
        else:
            page_byte_offset = dst_g_addr.addr % page_bytes
            remaining_page_bytes = page_bytes - page_byte_offset
            n_bytes = min(remaining_element_bytes, remaining_page_bytes)
            scalar_addr = dst_g_addr.to_scalar_addr(lamlet.tlb)
            lamlet.scalar.set_memory(scalar_addr, data[src_eb:src_eb + n_bytes])

        src_eb += n_bytes

    if has_vpu_writes:
        entry.state = ElementState.IN_FLIGHT
    else:
        buf.complete_element(buf.next_to_process)
        lamlet.remove_witem_by_ident(entry.instr_ident)
        lamlet.monitor.complete_kinstr(entry.instr_ident)


def _element_index_to_jamlet(lamlet: 'Lamlet', element_index: int) -> tuple[int, int]:
    """Compute target jamlet coordinates from element index."""
    vw_index = element_index % lamlet.params.j_in_l
    k_index, j_in_k_index = addresses.vw_index_to_k_indices(
        lamlet.params, lamlet.word_order, vw_index)
    return addresses.k_indices_to_j_coords(lamlet.params, k_index, j_in_k_index)


async def _send_ordered_vpu_write(lamlet: 'Lamlet', instr_ident: int, data: bytes,
                                  dst_g_addr: GlobalAddress, tag: int, n_bytes: int,
                                  witem: LamletWaitingStoreIndexedElement):
    """Send WRITE_MEM_WORD_REQ for an ordered store VPU write."""
    wb = lamlet.params.word_bytes

    k_maddr = dst_g_addr.to_k_maddr(lamlet.tlb)
    target_x, target_y = addresses.k_indices_to_j_coords(
        lamlet.params, k_maddr.k_index, k_maddr.j_in_k_index)
    dst_byte_in_word = k_maddr.addr % wb

    msg_ident = (instr_ident + tag + 1) % lamlet.params.max_response_tags

    header = WriteMemWordHeader(
        target_x=target_x,
        target_y=target_y,
        source_x=lamlet.instr_x,
        source_y=lamlet.instr_y,
        message_type=MessageType.WRITE_MEM_WORD_REQ,
        send_type=SendType.SINGLE,
        length=3,
        ident=msg_ident,
        tag=tag,
        dst_byte_in_word=dst_byte_in_word,
        n_bytes=n_bytes,
    )

    word_offset = k_maddr.addr % wb
    k_maddr_aligned = k_maddr.bit_offset(-word_offset * 8)
    # Send a full word with actual data positioned at tag offset
    # (do_write_and_respond expects src_word to be word_bytes long)
    word_data = bytearray(wb)
    word_data[tag:tag + n_bytes] = data[tag:tag + n_bytes]
    packet = [header, k_maddr_aligned, bytes(word_data)]

    kinstr_span_id = lamlet.monitor.get_kinstr_span_id(instr_ident)
    assert kinstr_span_id is not None
    transaction_span_id = lamlet.monitor.create_transaction(
        transaction_type='WriteMemWord',
        ident=msg_ident,
        src_x=lamlet.instr_x,
        src_y=lamlet.instr_y,
        dst_x=target_x,
        dst_y=target_y,
        tag=tag,
        parent_span_id=kinstr_span_id,
    )
    jamlet = lamlet.kamlets[0].jamlets[0]
    await lamlet.send_packet(packet, jamlet, Direction.N, port=0,
                             parent_span_id=transaction_span_id)
    assert witem.transaction_states[tag] == SendState.NEED_TO_SEND
    witem.transaction_states[tag] = SendState.WAITING_FOR_RESPONSE


async def _send_pending_vpu_writes(lamlet: 'Lamlet', buf: OrderedBuffer):
    """Send/resend pending VPU writes for an in-flight ordered store element."""
    entry = buf.get_entry(buf.next_to_process)
    assert entry is not None and entry.state == ElementState.IN_FLIGHT

    witem = lamlet.get_witem_by_ident(entry.instr_ident)
    assert isinstance(witem, LamletWaitingStoreIndexedElement)

    element_bytes = len(entry.data)

    for tag, state in enumerate(witem.transaction_states):
        if state != SendState.NEED_TO_SEND:
            continue
        dst_g_addr = entry.addr.bit_offset(tag * 8)
        page_info = lamlet.tlb.get_page_info(dst_g_addr.get_page())
        assert page_info.local_address.is_vpu
        dst_ew = page_info.local_address.ordering.ew
        dst_eb = dst_g_addr.bit_addr % dst_ew
        n_bytes = min((dst_ew - dst_eb) // 8, element_bytes - tag)
        await _send_ordered_vpu_write(
            lamlet, entry.instr_ident, entry.data, dst_g_addr, tag, n_bytes, witem)


async def vload_indexed_ordered(lamlet: 'Lamlet', vd: int, base_addr: int, index_reg: int,
                                index_ew: int, data_ew: int, n_elements: int,
                                mask_reg: int | None, start_index: int,
                                parent_span_id: int) -> VectorOpResult:
    """Handle ordered indexed vector loads.

    Dispatches LoadIndexedElement instructions one at a time, blocking until complete.
    Returns VectorOpResult with fault info if any element faulted.
    """
    g_addr = GlobalAddress(bit_addr=base_addr * 8, params=lamlet.params)
    data_ordering = Ordering(word_order=lamlet.word_order, ew=data_ew)

    # Set up register file ordering for destination registers
    vline_bits = lamlet.params.maxvl_bytes * 8
    n_vlines = (data_ew * n_elements + vline_bits - 1) // vline_bits
    for vline_reg in range(vd, vd + n_vlines):
        lamlet.vrf_ordering[vline_reg] = data_ordering

    # Wait for an ordered buffer slot
    buffer_id = get_free_buffer_id(lamlet)
    while buffer_id is None:
        await lamlet.clock.next_cycle
        buffer_id = get_free_buffer_id(lamlet)

    buf = OrderedBuffer(
        buffer_id=buffer_id,
        n_elements=n_elements,
        is_load=True,
        capacity=lamlet.params.ordered_buffer_capacity,
        data_ew=data_ew,
        start_index=start_index,
    )
    lamlet._ordered_buffers[buffer_id] = buf

    # Send barrier instruction to all kamlets - serves as "parent" for READ_MEM_WORD ordering
    # Use dedicated barrier ident (outside normal pool) to avoid deadlock
    barrier_ident = lamlet._ordered_barrier_idents[buffer_id]
    barrier_instr = OrderedIndexedLoad(instr_ident=barrier_ident)
    await lamlet.add_to_instruction_buffer(barrier_instr, parent_span_id=parent_span_id,
                                           k_index=None)  # None = broadcast to all

    # Create sync span now (before children finalized), local_event called later
    barrier_kinstr_span_id = lamlet.monitor.get_kinstr_span_id(barrier_ident)
    lamlet.monitor.create_sync_local_span(barrier_ident, 0, -1, barrier_kinstr_span_id)

    # Dispatch all active elements
    for element_index in range(start_index, n_elements):
        # Stop dispatching once we know about a fault
        if buf.faulted_element is not None:
            break

        # Wait for buffer capacity
        while not buf.can_dispatch():
            await lamlet.clock.next_cycle

        # Allocate 1 + word_bytes idents: base ident + one per possible tag
        element_ident = await ident_query.get_instr_ident(
            lamlet, n_idents=1 + lamlet.params.word_bytes)

        vw_index = element_index % lamlet.params.j_in_l
        k_index, _ = addresses.vw_index_to_k_indices(
            lamlet.params, lamlet.word_order, vw_index)

        kinstr = LoadIndexedElement(
            dst_reg=vd,
            base_addr=g_addr,
            index_reg=index_reg,
            index_ew=index_ew,
            data_ew=data_ew,
            element_index=element_index,
            word_order=lamlet.word_order,
            instr_ident=element_ident,
            parent_ident=barrier_ident,
            mask_reg=mask_reg,
        )

        witem = LamletWaitingLoadIndexedElement(
            instr_ident=element_ident,
            buffer_id=buffer_id,
            element_index=element_index,
        )
        await lamlet.add_witem(witem)

        await lamlet.add_to_instruction_buffer(kinstr, parent_span_id=parent_span_id,
                                               k_index=k_index)
        dispatched_index = buf.add_dispatched(element_ident)
        assert dispatched_index == element_index

    # If we broke early due to fault, only wait for dispatched elements
    if buf.faulted_element is not None:
        buf.n_elements = buf.next_to_dispatch

    # Wait for all elements to complete
    while not buf.all_complete():
        await lamlet.clock.next_cycle

    # Signal barrier completion via sync network
    lamlet.synchronizer.local_event(barrier_ident)

    # Wait for barrier sync to complete (all kamlets done with barrier)
    while not lamlet.synchronizer.is_complete(barrier_ident):
        await lamlet.clock.next_cycle

    # Clean up ordered buffer
    lamlet._ordered_buffers[buffer_id] = None

    # Return result with fault info if any element faulted
    if buf.faulted_element is not None:
        return VectorOpResult(fault_type=TLBFaultType.READ_FAULT,
                              element_index=buf.faulted_element)
    return VectorOpResult()


async def vstore_indexed_ordered(lamlet: 'Lamlet', vs: int, base_addr: int, index_reg: int,
                                 index_ew: int, data_ew: int, n_elements: int,
                                 mask_reg: int | None, start_index: int,
                                 parent_span_id: int) -> VectorOpResult:
    """Handle ordered indexed vector stores.

    Dispatches StoreIndexedElement instructions one at a time.
    Returns VectorOpResult with fault info if any element faulted.
    """
    g_addr = GlobalAddress(bit_addr=base_addr * 8, params=lamlet.params)

    # Wait for an ordered buffer slot
    buffer_id = get_free_buffer_id(lamlet)
    while buffer_id is None:
        await lamlet.clock.next_cycle
        buffer_id = get_free_buffer_id(lamlet)

    buf = OrderedBuffer(
        buffer_id=buffer_id,
        n_elements=n_elements,
        is_load=False,
        capacity=lamlet.params.ordered_buffer_capacity,
        data_ew=data_ew,
        start_index=start_index,
    )
    lamlet._ordered_buffers[buffer_id] = buf

    # Dispatch all active elements
    for element_index in range(start_index, n_elements):
        # Stop dispatching once we know about a fault
        if buf.faulted_element is not None:
            break

        # Wait for buffer capacity
        while not buf.can_dispatch():
            await lamlet.clock.next_cycle

        # Allocate 1 + word_bytes idents: base ident + one per possible tag
        element_ident = await ident_query.get_instr_ident(
            lamlet, n_idents=1 + lamlet.params.word_bytes)

        vw_index = element_index % lamlet.params.j_in_l
        k_index, _ = addresses.vw_index_to_k_indices(
            lamlet.params, lamlet.word_order, vw_index)

        kinstr = StoreIndexedElement(
            src_reg=vs,
            base_addr=g_addr,
            index_reg=index_reg,
            index_ew=index_ew,
            data_ew=data_ew,
            element_index=element_index,
            word_order=lamlet.word_order,
            instr_ident=element_ident,
            mask_reg=mask_reg,
        )

        witem = LamletWaitingStoreIndexedElement(
            instr_ident=element_ident,
            buffer_id=buffer_id,
            element_index=element_index,
            element_bytes=data_ew // 8,
        )
        await lamlet.add_witem(witem)

        await lamlet.add_to_instruction_buffer(kinstr, parent_span_id=parent_span_id,
                                               k_index=k_index)
        dispatched_index = buf.add_dispatched(element_ident)
        assert dispatched_index == element_index

    # If we broke early due to fault, only wait for dispatched elements
    if buf.faulted_element is not None:
        buf.n_elements = buf.next_to_dispatch

    # Wait for all elements to complete
    while not buf.all_complete():
        await lamlet.clock.next_cycle

    # Return result with fault info if any element faulted
    if buf.faulted_element is not None:
        return VectorOpResult(fault_type=TLBFaultType.WRITE_FAULT,
                              element_index=buf.faulted_element)
    return VectorOpResult()
