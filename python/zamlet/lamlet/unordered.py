"""
Unordered vector load/store operations for the lamlet.

Handles regular vload/vstore, strided operations, unordered indexed operations,
and scalar memory operations.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Tuple

from zamlet import addresses
from zamlet.addresses import GlobalAddress, Ordering, TLBFaultType, VectorOpResult
from zamlet.kamlet import kinstructions
from zamlet.transactions.load import Load
from zamlet.transactions.store import Store
from zamlet.transactions.load_stride import LoadStride
from zamlet.transactions.store_stride import StoreStride
from zamlet.transactions.load_indexed_unordered import LoadIndexedUnordered
from zamlet.transactions.store_indexed_unordered import StoreIndexedUnordered
from zamlet.transactions.load_word import LoadWord
from zamlet.transactions.store_word import StoreWord
from zamlet import utils
from zamlet.lamlet import ident_query
from zamlet.message import (
    MessageType, SendType, Direction, TaggedHeader,
    ReadMemWordHeader, WriteMemWordHeader,
)
from zamlet.synchronization import (
    SyncAggOp, fault_info_width, unpack_fault_info)

if TYPE_CHECKING:
    from zamlet.oamlet.oamlet import Oamlet

logger = logging.getLogger(__name__)


async def wait_for_fault_sync(lamlet: 'Oamlet', fault_sync_ident: int) -> int | None:
    """Wait for fault sync to complete.

    Returns packed VectorFaultInfo for the minimum fault element, or None if no
    fault.
    """
    while not lamlet.synchronizer.is_complete(fault_sync_ident):
        await lamlet.clock.next_cycle
    global_min_fault = lamlet.synchronizer.get_aggregated_value(fault_sync_ident)
    logger.debug(f'{lamlet.clock.cycle}: wait_for_fault_sync: '
                 f'fault_sync {fault_sync_ident} complete, min_fault={global_min_fault}')
    return global_min_fault


@dataclass
class SectionInfo:
    """A section of memory that is guaranteed to all be on one page."""
    is_vpu: bool
    is_a_partial_element: bool
    start_index: int
    start_address: int
    end_address: int


def check_pages_for_access(lamlet: 'Oamlet', start_addr: int, n_elements: int,
                           element_bytes: int, is_write: bool) -> VectorOpResult:
    """
    Check TLB for all pages touched by an access.
    Returns VectorOpResult with fault info if any page is inaccessible.
    """
    page_bytes = lamlet.params.page_bytes
    end_addr = start_addr + n_elements * element_bytes

    current_addr = start_addr
    while current_addr < end_addr:
        g_addr = GlobalAddress(bit_addr=current_addr * 8, params=lamlet.params)
        fault_type = lamlet.tlb.check_access(g_addr, is_write)
        if fault_type != TLBFaultType.NONE:
            # Report mtval as the effective address of the faulting element.
            element_index = (current_addr - start_addr) // element_bytes
            fault_addr = start_addr + element_index * element_bytes
            return VectorOpResult(
                fault_type=fault_type, element_index=element_index,
                fault_addr=fault_addr)
        # Move to next page
        current_addr = ((current_addr // page_bytes) + 1) * page_bytes

    return VectorOpResult()


def check_page_range(
        lamlet: 'Oamlet', start_addr: int, end_addr: int,
        is_write: bool) -> Tuple[bool, bool]:
    """Check TLB for all pages in [start_addr, end_addr).

    Returns (accessible, all_vpu) where accessible is True if every page is
    accessible, and all_vpu is True if every page is VPU memory.
    """
    page_bytes = lamlet.params.page_bytes
    current_addr = start_addr
    all_vpu = True
    while current_addr < end_addr:
        g_addr = GlobalAddress(bit_addr=current_addr * 8, params=lamlet.params)
        fault_type = lamlet.tlb.check_access(g_addr, is_write)
        if fault_type != TLBFaultType.NONE:
            return False, False
        if not g_addr.is_vpu(lamlet.tlb):
            all_vpu = False
        current_addr = ((current_addr // page_bytes) + 1) * page_bytes
    return True, all_vpu


def get_memory_split(lamlet: 'Oamlet', g_addr: GlobalAddress, element_width: int,
                     n_elements: int, first_index: int) -> List[SectionInfo]:
    """
    Takes an address in global memory and a size.
    Works out what pages that is distributed across.
    For each page the data might be in scalar memory or vpu memory.
      - We need to split the it into accesses in scalar memory and vpu memory.
      - We need to consider elements that might be split across the transition from
        scalar memory to vpu memory.
    It returns a list of tuples where each tuple represents either a partial element
    of an element that straddles a vpu/scalar memory boundary or a list of elements
    entirely in the vpu or scalar memory.
    Each tuple is of the form
    (is_vpu, is_partial, starting_index, starting_address, ending_address)
    The ending address is the byte address after the final byte.
    """
    start_index = first_index
    start_addr = g_addr.addr
    lumps: List[Tuple[bool, int, int, int]] = []
    element_offset_bits = (start_addr*8) % element_width
    assert element_offset_bits % 8 == 0
    element_offset = element_offset_bits//8
    eb = element_width//8

    l_cache_line_bytes = lamlet.params.cache_line_bytes * lamlet.params.k_in_l

    while start_index < n_elements:
        current_element_addr = g_addr.addr + start_index * eb
        page_address = (start_addr//lamlet.params.page_bytes) * lamlet.params.page_bytes
        page_info = lamlet.tlb.get_page_info(GlobalAddress(bit_addr=page_address*8,
                                                           params=lamlet.params))
        remaining_elements = n_elements - start_index

        cache_line_boundary = ((start_addr // l_cache_line_bytes) + 1) * l_cache_line_bytes
        page_boundary = page_address + lamlet.params.page_bytes
        next_boundary = min(cache_line_boundary, page_boundary)

        end_addr = min(current_element_addr + remaining_elements * eb, next_boundary)

        # For VPU pages, split at vline boundaries where the ew changes.
        if page_info.is_vpu:
            vline_bytes = lamlet.params.vline_bytes
            first_vline_addr = (start_addr // vline_bytes) * vline_bytes
            first_g = GlobalAddress(bit_addr=first_vline_addr * 8, params=lamlet.params)
            first_ew = lamlet.tlb.get_vline_info(first_g).local_address.ordering
            vline_addr = first_vline_addr + vline_bytes
            while vline_addr < end_addr:
                vg = GlobalAddress(bit_addr=vline_addr * 8, params=lamlet.params)
                vline_ew = lamlet.tlb.get_vline_info(vg).local_address.ordering
                if vline_ew != first_ew:
                    end_addr = vline_addr
                    break
                vline_addr += vline_bytes

        lumps.append((page_info.is_vpu, start_index, start_addr, end_addr))
        start_index = (end_addr - g_addr.addr)//eb
        start_addr = end_addr

    sections: List[SectionInfo]
    if not element_offset:
        sections = [SectionInfo(is_vpu, False, start_index, start_addr, end_addr)
                    for is_vpu, start_index, start_addr, end_addr in lumps]
    else:
        sections = []
        next_index = first_index
        logger.debug(f'get_memory_split: Processing lumps with element_offset={element_offset}')
        for lump_is_vpu, lump_start_index, lump_start_addr, lump_end_addr in lumps:
            logger.debug(f'  Lump: is_vpu={lump_is_vpu}, start_idx={lump_start_index}, '
                       f'start_addr=0x{lump_start_addr:x}, end_addr=0x{lump_end_addr:x}')
            assert next_index == lump_start_index

            start_offset = (lump_start_addr - g_addr.addr) % eb
            if start_offset != 0:
                start_whole_addr = lump_start_addr + (eb - start_offset)
                assert start_whole_addr-1 <= lump_end_addr
                logger.debug(f'    Adding partial start: idx={next_index}, '
                           f'start=0x{lump_start_addr:x}, end=0x{start_whole_addr:x}')
                sections.append(SectionInfo(lump_is_vpu, True, next_index,
                                            lump_start_addr, start_whole_addr))
                next_index += 1
            else:
                start_whole_addr = lump_start_addr

            end_offset = (lump_end_addr - g_addr.addr) % eb
            if end_offset != 0:
                end_whole_addr = lump_end_addr - end_offset
            else:
                end_whole_addr = lump_end_addr

            if end_whole_addr - start_whole_addr > 0:
                logger.info(f'    Adding whole elements: idx={next_index}, '
                           f'start=0x{start_whole_addr:x}, end=0x{end_whole_addr:x}')
                sections.append(SectionInfo(lump_is_vpu, False, next_index,
                                            start_whole_addr, end_whole_addr))
                next_index += (end_whole_addr - start_whole_addr) // eb
            if lump_end_addr != end_whole_addr:
                logger.info(f'    Adding partial end: idx={next_index}, '
                           f'start=0x{end_whole_addr:x}, end=0x{lump_end_addr:x}')
                sections.append(SectionInfo(lump_is_vpu, True, next_index,
                                            end_whole_addr, lump_end_addr))
    logger.info(f'get_memory_split: Generated {len(sections)} sections')
    for i, section in enumerate(sections):
        logger.debug(f'  Section {i}: is_vpu={section.is_vpu}, partial={section.is_a_partial_element}, '
                    f'idx={section.start_index}, start=0x{section.start_address:x}, '
                    f'end=0x{section.end_address:x}')
    return sections


async def vload(lamlet: 'Oamlet', vd: int, addr: int, ordering: addresses.Ordering,
                n_elements: int, mask_reg: int | None, start_index: int,
                parent_span_id: int, stride_bytes: int | None = None) -> VectorOpResult:
    assert ordering.ew % 8 == 0
    element_bytes = ordering.ew // 8
    if stride_bytes is not None and stride_bytes != element_bytes:
        return await vloadstorestride(lamlet, vd, addr, ordering, n_elements, mask_reg,
                                      start_index, is_store=False,
                                      parent_span_id=parent_span_id,
                                      stride_bytes=stride_bytes)
    else:
        return await vloadstore(lamlet, vd, addr, ordering, n_elements, mask_reg, start_index,
                                is_store=False, parent_span_id=parent_span_id)


async def vstore(lamlet: 'Oamlet', vs: int, addr: int, ordering: addresses.Ordering,
                 n_elements: int, mask_reg: int | None, start_index: int,
                 parent_span_id: int, stride_bytes: int | None = None) -> VectorOpResult:
    assert ordering.ew % 8 == 0
    element_bytes = ordering.ew // 8
    if stride_bytes is not None and stride_bytes != element_bytes:
        return await vloadstorestride(lamlet, vs, addr, ordering, n_elements, mask_reg,
                                      start_index, is_store=True,
                                      parent_span_id=parent_span_id,
                                      stride_bytes=stride_bytes)
    else:
        return await vloadstore(lamlet, vs, addr, ordering, n_elements, mask_reg, start_index,
                                is_store=True, parent_span_id=parent_span_id)


async def remap_reg_ew(
    lamlet: 'Oamlet', src_regs: list[int], dst_regs: list[int],
    dst_ordering: Ordering, parent_span_id: int,
):
    """Remap register data from one ew layout to another via scratch VPU memory.

    Stores src_regs at their current ew, then loads into dst_regs at dst_ordering.ew.
    src_regs and dst_regs may overlap (for in-place remap).

    Caller is responsible for allocating/freeing any temp regs used as dst_regs.

    TODO: Replace with a dedicated register-to-register ew remap kinstr using
    J2J messages. See docs/TODO.md.
    """
    assert len(src_regs) == len(dst_regs)
    n = len(src_regs)
    vline_bits = lamlet.params.maxvl_bytes * 8
    assert lamlet.params.page_bytes >= lamlet.params.maxvl_bytes

    scratch_temp = lamlet.alloc_temp_regs(1)
    scratch_addresses = []
    for i in range(n):
        src_ordering = lamlet.vrf_ordering[src_regs[i]]
        src_elements_per_vline = vline_bits // src_ordering.ew
        scratch_addr = lamlet.get_scratch_page(scratch_temp[0], src_ordering.ew)
        await lamlet.vstore(
            src_regs[i], scratch_addr, src_ordering,
            n_elements=src_elements_per_vline, mask_reg=None, start_index=0,
            parent_span_id=parent_span_id, emul=1,
        )
        scratch_addresses.append(scratch_addr)

    dst_elements_per_vline = vline_bits // dst_ordering.ew
    for i, scratch_addr in enumerate(scratch_addresses):
        await lamlet.vload(
            dst_regs[i], scratch_addr, dst_ordering,
            n_elements=dst_elements_per_vline, mask_reg=None, start_index=0,
            parent_span_id=parent_span_id, emul=1,
        )
    await lamlet.free_temp_regs(scratch_temp, parent_span_id)


async def _handle_partial_element_scalar(
        lamlet: 'Oamlet', section: 'MemorySection', reg_base: int,
        ordering: addresses.Ordering, mask_reg: int | None,
        writeset_ident: int, is_store: bool, parent_span_id: int):
    """Handle a partial element that falls in scalar memory."""
    starting_g_addr = GlobalAddress(
        bit_addr=section.start_address * 8, params=lamlet.params)
    mask_index = section.start_index // lamlet.params.j_in_l
    size = section.end_address - section.start_address
    element_offset = starting_g_addr.bit_addr % (lamlet.params.word_bytes * 8)
    assert element_offset % 8 == 0
    start_is_page_boundary = section.start_address % lamlet.params.page_bytes == 0
    if start_is_page_boundary:
        # We're the second segment of the element
        start_byte_in_element = (ordering.ew - element_offset) // 8
    else:
        # We're the first segment of the element
        start_byte_in_element = element_offset // 8
    if is_store:
        await vstore_scalar_partial(
            lamlet, vd=reg_base, addr=section.start_address, size=size,
            src_ordering=ordering, mask_reg=mask_reg, mask_index=mask_index,
            element_index=section.start_index, writeset_ident=writeset_ident,
            start_byte=start_byte_in_element, parent_span_id=parent_span_id)
    else:
        await vload_scalar_partial(
            lamlet, vd=reg_base, addr=section.start_address, size=size,
            dst_ordering=ordering, mask_reg=mask_reg, mask_index=mask_index,
            element_index=section.start_index, writeset_ident=writeset_ident,
            start_byte=start_byte_in_element, parent_span_id=parent_span_id)


async def _handle_partial_element_vpu(
        lamlet: 'Oamlet', section: 'MemorySection', reg_base: int,
        reg_addr: addresses.RegAddr, ordering: addresses.Ordering,
        mask_reg: int | None, writeset_ident: int, is_store: bool,
        parent_span_id: int):
    """Handle a partial element that falls in VPU memory.

    The partial element's bytes may not be contiguous in VPU memory when the
    vline's ew differs from the instruction's ew. Split into chunks at vline
    element boundaries so each chunk is contiguous within a single word.
    """
    mask_index = section.start_index // lamlet.params.j_in_l
    wb = lamlet.params.word_bytes

    starting_g_addr = GlobalAddress(
        bit_addr=section.start_address * 8, params=lamlet.params)
    vline_info = lamlet.tlb.get_vline_info(starting_g_addr)
    vline_eb = vline_info.local_address.ordering.ew // 8
    vline_bytes = lamlet.params.vline_bytes
    vline_start_addr = (section.start_address // vline_bytes) * vline_bytes
    assert section.end_address <= vline_start_addr + vline_bytes

    pos = section.start_address
    while pos < section.end_address:
        offset_in_vline = pos - vline_start_addr
        remaining_in_vline_element = vline_eb - (offset_in_vline % vline_eb)
        chunk_end = min(pos + remaining_in_vline_element, section.end_address)
        chunk_size = chunk_end - pos

        chunk_g_addr = GlobalAddress(bit_addr=pos * 8, params=lamlet.params)
        chunk_k_maddr = lamlet.to_k_maddr(chunk_g_addr)
        chunk_reg_addr = reg_addr.offset_bytes(pos - section.start_address)

        start_word_byte = chunk_k_maddr.addr % wb
        assert start_word_byte + chunk_size <= wb
        byte_mask = [0] * wb
        for byte_index in range(start_word_byte, start_word_byte + chunk_size):
            byte_mask[byte_index] = 1
        byte_mask_as_int = utils.list_of_uints_to_uint(byte_mask, width=1)
        instr_ident = await ident_query.get_instr_ident(lamlet, 2)
        if is_store:
            kinstr = StoreWord(
                src=chunk_reg_addr, dst=chunk_k_maddr,
                byte_mask=byte_mask_as_int,
                writeset_ident=writeset_ident, mask_reg=mask_reg,
                mask_index=mask_index, instr_ident=instr_ident,
            )
        else:
            kinstr = LoadWord(
                dst=chunk_reg_addr, src=chunk_k_maddr,
                byte_mask=byte_mask_as_int,
                writeset_ident=writeset_ident, mask_reg=mask_reg,
                mask_index=mask_index, instr_ident=instr_ident,
            )
        await lamlet.add_to_instruction_buffer(kinstr, parent_span_id)
        pos = chunk_end


async def _handle_full_elements_vpu(
        lamlet: 'Oamlet', section: 'MemorySection', reg_base: int,
        ordering: addresses.Ordering, mask_reg: int | None,
        writeset_ident: int, is_store: bool, parent_span_id: int):
    section_elements = ((section.end_address - section.start_address) * 8) // ordering.ew
    starting_g_addr = GlobalAddress(bit_addr=section.start_address * 8, params=lamlet.params)
    k_maddr = lamlet.to_k_maddr(starting_g_addr)

    l_cache_line_bytes = lamlet.params.cache_line_bytes * lamlet.params.k_in_l
    assert (section.start_address // l_cache_line_bytes
            == (section.end_address - 1) // l_cache_line_bytes)

    instr_ident = await ident_query.get_instr_ident(lamlet)
    if is_store:
        kinstr = Store(
            src=reg_base,
            k_maddr=k_maddr,
            start_index=section.start_index,
            n_elements=section_elements,
            src_ordering=ordering,
            mask_reg=mask_reg,
            writeset_ident=writeset_ident,
            instr_ident=instr_ident,
        )
    else:
        kinstr = Load(
            dst=reg_base,
            k_maddr=k_maddr,
            start_index=section.start_index,
            n_elements=section_elements,
            dst_ordering=ordering,
            mask_reg=mask_reg,
            writeset_ident=writeset_ident,
            instr_ident=instr_ident,
        )
    await lamlet.add_to_instruction_buffer(kinstr, parent_span_id)


async def vloadstore(lamlet: 'Oamlet', reg_base: int, addr: int, ordering: addresses.Ordering,
                     n_elements: int, mask_reg: int | None, start_index: int, is_store: bool,
                     parent_span_id: int) -> VectorOpResult:
    """
    We have 3 different kinds of vector loads/stores.
    - In VPU memory and aligned (this is the fastest by far)
    - In VPU memory but not aligned
        (We need to read from another jamlets memory).
    - In Scalar memory. We need to send the data element by element.

    And we could have a load that spans scalar and VPU regions of memory. Potentially
    an element could be half in VPU memory and half in scalar memory.

    Returns VectorOpResult with fault info if a TLB fault occurred.
    """
    g_addr = GlobalAddress(bit_addr=addr*8, params=lamlet.params)
    temp_regs = None

    vline_bits = lamlet.params.maxvl_bytes * 8
    elements_per_vline = vline_bits // ordering.ew
    n_vlines = (n_elements + elements_per_vline - 1) // elements_per_vline
    await lamlet.await_vreg_write_pending(reg_base, n_vlines)

    # For stores where the register ew doesn't match the instruction ew, remap
    # via scratch memory first. See docs/TODO.md for replacing this workaround.
    if is_store:
        needs_remap = False
        for i in range(n_vlines):
            reg_ord = lamlet.vrf_ordering[reg_base + i]
            assert reg_ord is not None
            if reg_ord.ew != ordering.ew:
                needs_remap = True
                break
        if needs_remap:
            src_regs = list(range(reg_base, reg_base + n_vlines))
            temp_regs = lamlet.alloc_temp_regs(n_vlines)
            await remap_reg_ew(lamlet, src_regs, temp_regs, ordering, parent_span_id)
            reg_base = temp_regs[0]

    # Check all pages for access before dispatching
    element_bytes = ordering.ew // 8
    result = check_pages_for_access(lamlet, addr, n_elements, element_bytes, is_store)
    if not result.success:
        # Reduce n_elements to only process up to the faulting element
        n_elements = result.element_index

    if n_elements == 0:
        if temp_regs is not None:
            await lamlet.free_temp_regs(temp_regs, parent_span_id)
        return result

    # This is an identifier that groups a number of writes to a vector register together.
    # These writes are guanteed to work on separate bytes so that the write order does not matter.
    writeset_ident = ident_query.get_writeset_ident(lamlet)

    # Verify vrf_ordering is set for affected registers.
    # For loads, vload() sets ordering for the full lmul group before calling here.
    # For stores, the producing instruction set it.
    regs = []
    for element_index in range(start_index, n_elements):
        reg = reg_base + (element_index * ordering.ew) // vline_bits
        if reg not in regs:
            regs.append(reg)
            assert lamlet.vrf_ordering[reg] == ordering

    base_reg_addr = addresses.RegAddr(
        reg=reg_base, addr=0, params=lamlet.params, ordering=ordering)

    for section in get_memory_split(lamlet, g_addr, ordering.ew, n_elements, start_index):
        # Set ordering on any uninitialized VPU vlines so address translation works.
        # For aligned unit-stride, oamlet.vstore/vload already handles this.
        # For unaligned unit-stride, the vline may not have been touched yet.
        if section.is_vpu:
            vline_bytes = lamlet.params.vline_bytes
            vline_start = (section.start_address // vline_bytes) * vline_bytes
            vline_end = ((section.end_address - 1) // vline_bytes) * vline_bytes
            for vline_addr in range(vline_start, vline_end + 1, vline_bytes):
                vline_g_addr = GlobalAddress(
                    bit_addr=vline_addr * 8, params=lamlet.params)
                vline_info = lamlet.tlb.get_vline_info(vline_g_addr)
                if vline_info.local_address.ordering is None:
                    lamlet.tlb.set_vline_ordering(vline_g_addr, ordering)
        if section.is_a_partial_element:
            reg_addr = base_reg_addr.offset_bytes(section.start_address - g_addr.addr)
            # The partial is either the start of an element or the end of an element.
            # Either the starting_addr or the ending_addr must be a cache line boundary
            start_is_cacheline_boundary = (
                section.start_address % lamlet.params.cache_line_bytes == 0)
            end_is_cacheline_boundary = (
                section.end_address % lamlet.params.cache_line_bytes == 0)
            if not (start_is_cacheline_boundary or end_is_cacheline_boundary):
                logger.error(
                    f'Partial element not at cache line boundary: '
                    f'start=0x{section.start_address:x}, '
                    f'end=0x{section.end_address:x}, '
                    f'cache_line_bytes={lamlet.params.cache_line_bytes}, '
                    f'start_idx={section.start_index}')
            assert start_is_cacheline_boundary or end_is_cacheline_boundary
            assert not (start_is_cacheline_boundary and end_is_cacheline_boundary)
            assert ordering.ew % 8 == 0
            if section.is_vpu:
                await _handle_partial_element_vpu(
                    lamlet, section, reg_base, reg_addr, ordering, mask_reg,
                    writeset_ident, is_store, parent_span_id)
            else:
                await _handle_partial_element_scalar(
                    lamlet, section, reg_base, ordering, mask_reg,
                    writeset_ident, is_store, parent_span_id)
        else:
            if section.is_vpu:
                await _handle_full_elements_vpu(
                    lamlet, section, reg_base, ordering, mask_reg,
                    writeset_ident, is_store, parent_span_id)
            else:
                section_elements = ((section.end_address - section.start_address) * 8)//ordering.ew
                await vloadstore_scalar(lamlet, reg_base, section.start_address, ordering,
                                        section_elements, mask_reg, section.start_index,
                                        writeset_ident, is_store, parent_span_id)
    if temp_regs is not None:
        await lamlet.free_temp_regs(temp_regs, parent_span_id)
    return result


async def vloadstorestride(lamlet: 'Oamlet', reg_base: int, addr: int,
                           ordering: addresses.Ordering, n_elements: int,
                           mask_reg: int | None, start_index: int,
                           is_store: bool, parent_span_id: int, stride_bytes: int
                           ) -> VectorOpResult:
    """
    Handle strided vector loads/stores by decomposing into vid + vmul + indexed.

    Computes byte offsets (i * stride) into a temporary register using vector
    ALU instructions, then issues an indexed load/store. This avoids requiring
    a hardware multiplier in the WitemMonitor.

    When the full index vector doesn't fit in the available temp registers,
    elements are processed in batches. Each batch adjusts the base address
    and populates the temp register with offsets for that batch only.
    """

    # Set up register file ordering for data registers
    vline_bits = lamlet.params.maxvl_bytes * 8
    n_data_vlines = (ordering.ew * n_elements + vline_bits - 1) // vline_bits
    await lamlet.await_vreg_write_pending(reg_base, n_data_vlines)
    for vline_reg in range(reg_base, reg_base + n_data_vlines):
        if is_store:
            assert lamlet.vrf_ordering[vline_reg] == ordering
        else:
            lamlet.vrf_ordering[vline_reg] = ordering

    index_ew = 64
    elements_per_vline_64 = vline_bits // index_ew
    # Use at most half the scratch arch pool so the kamlet has spare pregs
    # to rotate through for vid -> vmul -> indexed pipelining within and
    # across batches. Floor of 1 in case the pool is tiny.
    n_scratch = lamlet.params.n_vregs - lamlet.params.n_arch_vregs
    n_temp_regs = max(1, n_scratch // 2)
    batch_capacity = n_temp_regs * elements_per_vline_64

    temp_regs = lamlet.alloc_temp_regs(n_temp_regs)
    temp_base = temp_regs[0]
    for reg in temp_regs:
        await lamlet.await_vreg_write_pending(reg, 1)
        lamlet.vrf_ordering[reg] = Ordering(
            word_order=addresses.WordOrder.STANDARD, ew=index_ew)

    # Align batch_start to j_in_l so that index element (d - batch_start) lands
    # on the same jamlet as data element d (both have the same % j_in_l).
    j_in_l = lamlet.params.j_in_l
    aligned_start = (start_index // j_in_l) * j_in_l
    n_to_process = n_elements - aligned_start
    prev_fault_sync = None
    all_completion_syncs = []
    writeset_ident = ident_query.get_writeset_ident(lamlet)
    for batch_offset in range(0, n_to_process, batch_capacity):
        batch_n = min(batch_capacity, n_to_process - batch_offset)
        batch_start = aligned_start + batch_offset
        batch_base = addr + batch_start * stride_bytes
        actual_start_index = max(start_index, batch_start)

        # vid.v: temp[i] = i for i in [0, batch_n)
        vid_ident = await ident_query.get_instr_ident(lamlet)
        vid_kinstr = kinstructions.VidOp(
            dst=temp_base,
            n_elements=batch_n,
            element_width=index_ew,
            word_order=addresses.WordOrder.STANDARD,
            mask_reg=None,
            instr_ident=vid_ident,
        )
        await lamlet.add_to_instruction_buffer(vid_kinstr, parent_span_id)

        # vmul.vx: temp[i] = i * stride
        mul_ident = await ident_query.get_instr_ident(lamlet)
        stride_as_bytes = stride_bytes.to_bytes(8, byteorder='little', signed=True)
        mul_kinstr = kinstructions.VArithVxOp(
            op=kinstructions.VArithOp.MUL,
            dst=temp_base,
            scalar_bytes=stride_as_bytes,
            src2=temp_base,
            mask_reg=None,
            n_elements=batch_n,
            element_width=index_ew,
            word_order=addresses.WordOrder.STANDARD,
            instr_ident=mul_ident,
        )
        await lamlet.add_to_instruction_buffer(mul_kinstr, parent_span_id)

        # Indexed load/store with adjusted base and index_offset
        result = await _vloadstore_indexed_unordered(
            lamlet, reg=reg_base, base_addr=batch_base, index_reg=temp_base,
            index_ew=index_ew, data_ew=ordering.ew,
            n_elements=batch_start + batch_n,
            mask_reg=mask_reg, start_index=actual_start_index,
            parent_span_id=parent_span_id, is_store=is_store,
            index_offset=-batch_start,
            chain_from_ident=prev_fault_sync,
            writeset_ident=writeset_ident)
        prev_fault_sync = result.last_fault_sync_ident
        if result.completion_sync_idents:
            all_completion_syncs.extend(result.completion_sync_idents)

    # Temp regs are safe to free: the last instruction reading them is
    # already in the FIFO, and the kamlet handles register file blocking.
    await lamlet.free_temp_regs(temp_regs, parent_span_id)
    if prev_fault_sync is not None:
        result = await resolve_fault_sync(
            lamlet,
            VectorOpResult(
                fault_type=TLBFaultType.NOT_WAITED,
                completion_sync_idents=all_completion_syncs,
                last_fault_sync_ident=prev_fault_sync),
            is_store=is_store)
    else:
        result = VectorOpResult(completion_sync_idents=all_completion_syncs)
    return result


async def resolve_fault_sync(lamlet: 'Oamlet', result: VectorOpResult,
                             is_store: bool) -> VectorOpResult:
    """Wait for a NOT_WAITED fault sync and return a resolved result."""
    assert result.fault_type == TLBFaultType.NOT_WAITED
    assert result.last_fault_sync_ident is not None
    packed_fault_info = await wait_for_fault_sync(
        lamlet, result.last_fault_sync_ident)
    if packed_fault_info is not None:
        fault_info = unpack_fault_info(lamlet.params, packed_fault_info)
        return VectorOpResult(
            fault_type=fault_info.fault_type,
            element_index=fault_info.element_index,
            fault_addr=fault_info.fault_addr,
            completion_sync_idents=result.completion_sync_idents,
            last_fault_sync_ident=result.last_fault_sync_ident)
    return VectorOpResult(
        completion_sync_idents=result.completion_sync_idents,
        last_fault_sync_ident=result.last_fault_sync_ident)


async def vload_indexed_unordered(lamlet: 'Oamlet', vd: int, base_addr: int, index_reg: int,
                                  index_ew: int, data_ew: int, n_elements: int,
                                  mask_reg: int | None, start_index: int,
                                  parent_span_id: int,
                                  index_offset: int = 0) -> VectorOpResult:
    """Handle unordered indexed vector loads (vluxei).

    Indexed (gather) load: element i is loaded from address (base_addr + index_reg[i]).
    """
    result = await _vloadstore_indexed_unordered(
        lamlet, reg=vd, base_addr=base_addr, index_reg=index_reg,
        index_ew=index_ew, data_ew=data_ew, n_elements=n_elements,
        mask_reg=mask_reg, start_index=start_index,
        parent_span_id=parent_span_id, is_store=False,
        index_offset=index_offset)
    if result.fault_type == TLBFaultType.NOT_WAITED:
        result = await resolve_fault_sync(lamlet, result, is_store=False)
    return result


async def vstore_indexed_unordered(lamlet: 'Oamlet', vs: int, base_addr: int, index_reg: int,
                                   index_ew: int, data_ew: int, n_elements: int,
                                   mask_reg: int | None, start_index: int,
                                   parent_span_id: int,
                                   index_offset: int = 0) -> VectorOpResult:
    """Handle unordered indexed vector stores (vsuxei).

    Indexed (scatter) store: element i is stored to address (base_addr + index_reg[i]).
    """
    result = await _vloadstore_indexed_unordered(
        lamlet, reg=vs, base_addr=base_addr, index_reg=index_reg,
        index_ew=index_ew, data_ew=data_ew, n_elements=n_elements,
        mask_reg=mask_reg, start_index=start_index,
        parent_span_id=parent_span_id, is_store=True,
        index_offset=index_offset)
    if result.fault_type == TLBFaultType.NOT_WAITED:
        result = await resolve_fault_sync(lamlet, result, is_store=True)
    return result


async def _vloadstore_indexed_unordered(
        lamlet: 'Oamlet', reg: int, base_addr: int, index_reg: int,
        index_ew: int, data_ew: int, n_elements: int,
        mask_reg: int | None, start_index: int,
        parent_span_id: int, is_store: bool,
        index_offset: int = 0,
        chain_from_ident: int | None = None,
        writeset_ident: int | None = None,
        ) -> VectorOpResult:
    """Shared implementation for unordered indexed vector loads and stores.

    The index register contains byte offsets with element width index_ew.
    The data element width comes from SEW (data_ew).
    """
    g_addr = GlobalAddress(bit_addr=base_addr * 8, params=lamlet.params)
    data_ordering = Ordering(word_order=lamlet.word_order, ew=data_ew)
    index_ordering = Ordering(word_order=lamlet.word_order, ew=index_ew)

    if writeset_ident is None:
        writeset_ident = ident_query.get_writeset_ident(lamlet)

    if is_store:
        # Scatter stores send WRITE_MEM_WORD_REQ from the kamlet back to the lamlet.
        # The lamlet doesn't know which scalar addresses will be written until the
        # messages arrive, so we must wait for prior writesets to drain before
        # dispatching to avoid write-write conflicts at the scalar memory.
        while (lamlet.scalar.has_conflicting_writes(writeset_ident)
               or lamlet.scalar.has_conflicting_reads(writeset_ident)):
            await lamlet.clock.next_cycle

    vline_bits = lamlet.params.maxvl_bytes * 8
    n_vlines = (data_ew * n_elements + vline_bits - 1) // vline_bits
    # The strided caller batches and passes index_offset=-batch_start; the index
    # reg then covers positions [0, n_elements + index_offset) = [0, batch_n).
    n_index_positions = n_elements + index_offset
    n_index_vlines = (index_ew * n_index_positions + vline_bits - 1) // vline_bits
    await lamlet.await_vreg_write_pending(reg, n_vlines)
    await lamlet.await_vreg_write_pending(index_reg, n_index_vlines)
    if not is_store:
        # Set up register file ordering for destination registers
        for vline_reg in range(reg, reg + n_vlines):
            lamlet.vrf_ordering[vline_reg] = data_ordering

    # If index bound active and all pages in the bounded range are accessible,
    # skip per-element fault detection. Otherwise fall back to normal fault sync
    # since only the kamlets can identify which element faulted.
    skip_fault_wait = False
    range_is_vpu = False
    if lamlet.index_bound_bits > 0:
        end_addr = base_addr + (1 << lamlet.index_bound_bits)
        accessible, all_vpu = check_page_range(
            lamlet, base_addr, end_addr, is_write=is_store)
        if accessible:
            skip_fault_wait = True
            range_is_vpu = all_vpu
    # Process in chunks of elements_in_vline elements (max one vline per kinstr)
    # Active elements are [start_index, n_elements), so n_active = n_elements - start_index
    elements_in_vline = lamlet.params.vline_bytes * 8 // data_ew
    n_active = n_elements - start_index

    prev_fault_sync = chain_from_ident
    completion_sync_idents = []

    for chunk_offset in range(0, n_active, elements_in_vline):
        chunk_n = min(elements_in_vline, n_active - chunk_offset)
        instr_ident = await ident_query.get_instr_ident(
            lamlet, n_idents=lamlet.params.word_bytes + 1)

        if is_store:
            kinstr = StoreIndexedUnordered(
                src=reg,
                g_addr=g_addr,
                index_reg=index_reg,
                index_ordering=index_ordering,
                start_index=start_index + chunk_offset,
                n_elements=chunk_n,
                src_ordering=data_ordering,
                mask_reg=mask_reg,
                writeset_ident=writeset_ident,
                instr_ident=instr_ident,
                index_offset=index_offset,
            )
        else:
            kinstr = LoadIndexedUnordered(
                dst=reg,
                g_addr=g_addr,
                index_reg=index_reg,
                index_ordering=index_ordering,
                start_index=start_index + chunk_offset,
                n_elements=chunk_n,
                dst_ordering=data_ordering,
                mask_reg=mask_reg,
                writeset_ident=writeset_ident,
                instr_ident=instr_ident,
                index_offset=index_offset,
            )
        await lamlet.add_to_instruction_buffer(kinstr, parent_span_id)
        kinstr_span_id = lamlet.monitor.get_kinstr_span_id(instr_ident)

        fault_sync_ident = instr_ident
        completion_sync_ident = (
            (instr_ident + 1) % lamlet.params.max_response_tags)

        lamlet.monitor.create_sync_local_span(
            completion_sync_ident, 0, -1, kinstr_span_id)
        lamlet.synchronizer.local_event(completion_sync_ident)
        completion_sync_idents.append(completion_sync_ident)

        if not range_is_vpu:
            if is_store:
                lamlet.scalar.register_might_touch_write(
                    completion_sync_ident, writeset_ident)
            else:
                lamlet.scalar.register_might_touch_read(
                    completion_sync_ident, writeset_ident)

        lamlet.monitor.create_sync_local_span(
            fault_sync_ident, 0, -1, kinstr_span_id)
        if skip_fault_wait:
            lamlet.synchronizer.local_event(
                fault_sync_ident, value=None,
                op=SyncAggOp.MIN_FAULT_INFO,
                width=fault_info_width(lamlet.params))
        elif prev_fault_sync is not None:
            lamlet.synchronizer.chain_fault_sync(
                prev_fault_sync, fault_sync_ident)
            prev_fault_sync = fault_sync_ident
        else:
            lamlet.synchronizer.local_event(
                fault_sync_ident, value=None,
                op=SyncAggOp.MIN_FAULT_INFO,
                width=fault_info_width(lamlet.params))
            prev_fault_sync = fault_sync_ident

    fault_type = (TLBFaultType.NOT_WAITED if prev_fault_sync is not None
                  else TLBFaultType.NONE)
    return VectorOpResult(
        fault_type=fault_type,
        completion_sync_idents=completion_sync_idents,
        last_fault_sync_ident=prev_fault_sync)


async def vloadstore_scalar(
        lamlet: 'Oamlet', vd: int, addr: int, ordering: Ordering, n_elements: int,
        mask_reg: int, start_index: int, writeset_ident: int, is_store: bool,
        parent_span_id: int):
    """
    Reads elements from the scalar memory and sends them to the appropriate kamlets where they
    will update the vector register.

    FIXME: This function is untested. Add tests for vector loads/stores to scalar memory.
    """
    # Wait for prior scalar operations with different writeset_idents to complete.
    # This ensures the lamlet doesn't need to reorder or buffer incoming messages
    # to apply them in the correct order.
    if is_store:
        while (lamlet.scalar.has_conflicting_writes(writeset_ident)
               or lamlet.scalar.has_conflicting_reads(writeset_ident)):
            await lamlet.clock.next_cycle
    else:
        while lamlet.scalar.has_conflicting_writes(writeset_ident):
            await lamlet.clock.next_cycle
    for element_index in range(start_index, start_index+n_elements):
        start_addr_bits = addr * 8 + (element_index - start_index) * ordering.ew
        g_addr = GlobalAddress(bit_addr=start_addr_bits, params=lamlet.params)
        scalar_addr = g_addr.to_scalar_addr(lamlet.tlb)
        vw_index = element_index % lamlet.params.j_in_l
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                lamlet.params, ordering.word_order, vw_index)
        wb = lamlet.params.word_bytes
        mask_index = element_index // lamlet.params.j_in_l
        assert ordering.ew >= 8
        eb = ordering.ew // 8
        vlb = lamlet.params.vline_bytes
        byte_offset = element_index * eb
        reg_addr = addresses.RegAddr(
            vd + byte_offset // vlb, byte_offset % vlb, ordering, lamlet.params)
        instr_ident = await ident_query.get_instr_ident(lamlet)
        if is_store:
            lamlet.scalar.register_known_write(writeset_ident)
            logger.debug(
                f'vloadstore_scalar: store element_index={element_index} '
                f'reg_addr={reg_addr} scalar_addr=0x{scalar_addr:x} eb={eb}')
            kinstr = kinstructions.StoreScalar(
                src=reg_addr,
                scalar_addr=scalar_addr,
                dst_byte_in_word=scalar_addr % wb,
                n_bytes_or_bits=eb,
                bit_mode=False,
                dst_bit_in_byte=0,
                writeset_ident=writeset_ident,
                mask_reg=mask_reg,
                mask_index=mask_index,
                instr_ident=instr_ident,
            )
        elif eb == 1:
            lamlet.scalar.register_known_read(writeset_ident)
            byte_imm = (await lamlet.scalar.get_memory(
                scalar_addr, 1, writeset_ident=writeset_ident, known=True))[0]
            kinstr = kinstructions.LoadImmByte(
                dst=reg_addr,
                imm=byte_imm,
                bit_mask=(1 << 8) - 1,
                mask_reg=mask_reg,
                mask_index=mask_index,
                writeset_ident=writeset_ident,
                instr_ident=instr_ident,
            )
        else:
            lamlet.scalar.register_known_read(writeset_ident)
            start_byte = (mask_index * eb) % wb
            element_data = await lamlet.scalar.get_memory(
                scalar_addr, eb, writeset_ident=writeset_ident, known=True)
            word_imm = bytearray(wb)
            for i in range(eb):
                word_imm[start_byte + i] = element_data[i]
            word_imm = bytes(word_imm)
            byte_mask = [0] * wb
            for i in range(start_byte, start_byte + eb):
                byte_mask[i] = 1
            byte_mask_as_int = utils.list_of_uints_to_uint(byte_mask, width=1)
            kinstr = kinstructions.LoadImmWord(
                dst=reg_addr,
                imm=word_imm,
                byte_mask=byte_mask_as_int,
                mask_reg=mask_reg,
                mask_index=mask_index,
                writeset_ident=writeset_ident,
                instr_ident=instr_ident,
            )
        await lamlet.add_to_instruction_buffer(kinstr, parent_span_id, k_index=k_index)


async def vload_scalar_partial(lamlet: 'Oamlet', vd: int, addr: int, size: int,
                               dst_ordering: Ordering, mask_reg: int, mask_index: int,
                               element_index: int, start_byte: int, writeset_ident: int,
                               parent_span_id: int):
    """
    Reads a partial element from the scalar memory and sends it to the appropriate jamlet
    where it will update a vector register.

    start_byte: Which byte in element we starting loading from.
    size: How many bytes from the element we load.

    FIXME: This function is untested. Add tests for vector loads/stores to scalar memory.
    """
    while lamlet.scalar.has_conflicting_writes(writeset_ident):
        await lamlet.clock.next_cycle
    assert start_byte + size < lamlet.params.word_bytes
    g_addr = GlobalAddress(bit_addr=addr*8, params=lamlet.params)
    scalar_addr = g_addr.to_scalar_addr(lamlet.tlb)
    vw_index = element_index % lamlet.params.j_in_l
    k_index, j_in_k_index = addresses.vw_index_to_k_indices(
        lamlet.params, dst_ordering.word_order, vw_index)
    kinstr: kinstructions.KInstr
    instr_ident = await ident_query.get_instr_ident(lamlet)
    if size == 1:
        lamlet.scalar.register_known_read(writeset_ident)
        bit_mask = (1 << 8) - 1
        byte_imm = (await lamlet.scalar.get_memory(
            scalar_addr.addr, 1, writeset_ident=writeset_ident, known=True))[0]
        kinstr = kinstructions.LoadImmByte(
            dst=addresses.RegAddr(vd, start_byte, dst_ordering, lamlet.params),
            imm=byte_imm,
            bit_mask=bit_mask,
            mask_reg=mask_reg,
            mask_index=mask_index,
            writeset_ident=writeset_ident,
            instr_ident=instr_ident,
        )
    else:
        lamlet.scalar.register_known_read(writeset_ident)
        word_addr = scalar_addr - start_byte
        word_imm = await lamlet.scalar.get_memory(
            word_addr, lamlet.params.word_bytes,
            writeset_ident=writeset_ident, known=True)
        byte_mask = [0]*lamlet.params.word_bytes
        for byte_index in range(start_byte, start_byte+size):
            byte_mask[byte_index] = 1
        byte_mask = utils.list_of_uints_to_uint(byte_mask, width=1)
        kinstr = kinstructions.LoadImmWord(
            dst=addresses.RegAddr(vd, 0, dst_ordering, lamlet.params),
            imm=word_imm,
            byte_mask=byte_mask,
            mask_reg=mask_reg,
            mask_index=mask_index,
            writeset_ident=writeset_ident,
            instr_ident=instr_ident,
        )
    await lamlet.add_to_instruction_buffer(kinstr, parent_span_id, k_index=k_index)


async def vstore_scalar_partial(lamlet: 'Oamlet', vd: int, addr: int, size: int,
                                src_ordering: Ordering, mask_reg: int, mask_index: int,
                                element_index: int, writeset_ident: int, start_byte: int,
                                parent_span_id: int):
    """
    Stores a partial element from a vector register to scalar memory.

    start_byte: Which byte in element we start storing from.
    size: How many bytes from the element we store.
    """
    while (lamlet.scalar.has_conflicting_writes(writeset_ident)
           or lamlet.scalar.has_conflicting_reads(writeset_ident)):
        await lamlet.clock.next_cycle
    assert start_byte + size < lamlet.params.word_bytes
    wb = lamlet.params.word_bytes
    g_addr = GlobalAddress(bit_addr=addr*8, params=lamlet.params)
    scalar_addr = g_addr.to_scalar_addr(lamlet.tlb)
    vw_index = element_index % lamlet.params.j_in_l
    k_index, j_in_k_index = addresses.vw_index_to_k_indices(
        lamlet.params, src_ordering.word_order, vw_index)
    lamlet.scalar.register_known_write(writeset_ident)
    instr_ident = await ident_query.get_instr_ident(lamlet)
    reg_addr = addresses.RegAddr(vd, start_byte, src_ordering, lamlet.params)
    kinstr = kinstructions.StoreScalar(
        src=reg_addr,
        scalar_addr=scalar_addr,
        dst_byte_in_word=scalar_addr % wb,
        n_bytes_or_bits=size,
        bit_mode=False,
        dst_bit_in_byte=0,
        writeset_ident=writeset_ident,
        mask_reg=mask_reg,
        mask_index=mask_index,
        instr_ident=instr_ident,
    )
    await lamlet.add_to_instruction_buffer(kinstr, parent_span_id, k_index=k_index)


async def handle_read_mem_word_req(lamlet: 'Oamlet', header: ReadMemWordHeader,
                                   scalar_addr: int):
    """Handle unordered READ_MEM_WORD_REQ: read from scalar memory and respond immediately."""
    wb = lamlet.params.word_bytes
    word_addr = scalar_addr - (scalar_addr % wb)
    lamlet.scalar.register_known_read(header.writeset_ident)
    data = int.from_bytes(await lamlet.scalar.get_memory(
        scalar_addr, wb, writeset_ident=header.writeset_ident, known=True), 'little')
    resp_header = TaggedHeader(
        target_x=header.source_x,
        target_y=header.source_y,
        source_x=lamlet.instr_x,
        source_y=lamlet.instr_y,
        message_type=MessageType.READ_MEM_WORD_RESP,
        send_type=SendType.SINGLE,
        length=1,
        tag=header.tag,
        ident=header.ident,
    )
    packet = [resp_header, data]
    jamlet = lamlet.kamlets[0].jamlets[0]
    transaction_span_id = lamlet.monitor.get_transaction_span_id(
        header.ident, header.tag, header.source_x, header.source_y,
        lamlet.instr_x, lamlet.instr_y)
    assert transaction_span_id is not None
    lamlet.monitor.add_event(
        transaction_span_id,
        f'scalar_read addr=0x{scalar_addr:x}, word_addr=0x{word_addr:x}, data=0x{data:x}')
    await lamlet.send_packet(packet, jamlet, Direction.N, port=0,
                             parent_span_id=transaction_span_id)
    logger.debug(
        f'{lamlet.clock.cycle}: lamlet: READ_MEM_WORD_REQ addr=0x{scalar_addr:x} '
        f'-> ({header.source_x},{header.source_y}) data=0x{data:x}')


async def handle_write_mem_word_req(lamlet: 'Oamlet', header: WriteMemWordHeader,
                                    scalar_addr: int, src_word: int):
    """Handle WRITE_MEM_WORD_REQ: write to scalar memory and send response."""
    wb = lamlet.params.word_bytes
    word_addr = scalar_addr - (scalar_addr % wb)
    # no_response means this was a known write (pre-registered at dispatch via StoreScalar).
    # With response means this is a scatter write (not pre-registered).
    known = header.no_response
    if header.bit_mode:
        # Bit-level write: read-modify-write a single byte
        byte_addr = word_addr + header.dst_byte_in_word
        existing = (await lamlet.scalar.get_memory(
            byte_addr, 1, writeset_ident=header.writeset_ident))[0]
        n_bits = header.n_bytes_or_bits
        bit_offset = header.dst_bit_in_byte
        src_byte = (src_word >> (header.dst_byte_in_word * 8)) & 0xFF
        mask = ((1 << n_bits) - 1) << bit_offset
        new_byte = (existing & ~mask) | (src_byte & mask)
        await lamlet.scalar.set_memory(
            byte_addr, bytes([new_byte]),
            writeset_ident=header.writeset_ident, known=known)
    else:
        src_start = header.tag
        dst_start = header.dst_byte_in_word
        n_bytes = header.n_bytes_or_bits
        src_bytes = src_word.to_bytes(wb, 'little')
        await lamlet.scalar.set_memory(
            word_addr + dst_start, src_bytes[src_start:src_start + n_bytes],
            writeset_ident=header.writeset_ident, known=known)
    if not header.no_response:
        resp_header = TaggedHeader(
            target_x=header.source_x,
            target_y=header.source_y,
            source_x=lamlet.instr_x,
            source_y=lamlet.instr_y,
            message_type=MessageType.WRITE_MEM_WORD_RESP,
            send_type=SendType.SINGLE,
            length=0,
            tag=header.tag,
            ident=header.ident,
        )
        packet = [resp_header]
        jamlet = lamlet.kamlets[0].jamlets[0]
        transaction_span_id = lamlet.monitor.get_transaction_span_id(
            header.ident, header.tag, header.source_x, header.source_y,
            lamlet.instr_x, lamlet.instr_y)
        assert transaction_span_id is not None
        await lamlet.send_packet(packet, jamlet, Direction.N, port=0,
                                 parent_span_id=transaction_span_id)
    if header.bit_mode:
        logger.debug(
            f'{lamlet.clock.cycle}: lamlet: WRITE_MEM_WORD_REQ bit_mode '
            f'addr=0x{scalar_addr:x} byte={header.dst_byte_in_word} '
            f'bit={header.dst_bit_in_byte} n_bits={header.n_bytes_or_bits} '
            f'-> ({header.source_x},{header.source_y})')
    else:
        logger.debug(
            f'{lamlet.clock.cycle}: lamlet: WRITE_MEM_WORD_REQ addr=0x{scalar_addr:x} '
            f'src_start={header.tag} dst_start={header.dst_byte_in_word} '
            f'n_bytes={header.n_bytes_or_bits} '
            f'-> ({header.source_x},{header.source_y})')
