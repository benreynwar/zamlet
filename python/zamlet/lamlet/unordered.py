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
from zamlet.transactions.load_stride import LoadStride
from zamlet.transactions.store_stride import StoreStride
from zamlet.transactions.load_indexed_unordered import LoadIndexedUnordered
from zamlet.transactions.store_indexed_unordered import StoreIndexedUnordered
from zamlet import utils
from zamlet.lamlet import ident_query
from zamlet.message import MessageType, SendType, Direction, TaggedHeader, WriteMemWordHeader

if TYPE_CHECKING:
    from zamlet.lamlet.lamlet import Lamlet

logger = logging.getLogger(__name__)


async def wait_for_fault_sync(lamlet: 'Lamlet', fault_sync_ident: int) -> int | None:
    """Wait for fault sync to complete.

    Returns the global minimum fault element, or None if no fault.
    """
    while not lamlet.synchronizer.is_complete(fault_sync_ident):
        await lamlet.clock.next_cycle
    global_min_fault = lamlet.synchronizer.get_min_value(fault_sync_ident)
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


def check_pages_for_access(lamlet: 'Lamlet', start_addr: int, n_elements: int,
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
            # Calculate which element this fault corresponds to
            element_index = (current_addr - start_addr) // element_bytes
            return VectorOpResult(fault_type=fault_type, element_index=element_index)
        # Move to next page
        current_addr = ((current_addr // page_bytes) + 1) * page_bytes

    return VectorOpResult()


def check_page_range(lamlet: 'Lamlet', start_addr: int, end_addr: int,
                     is_write: bool) -> VectorOpResult:
    """Check TLB for all pages in [start_addr, end_addr).

    Returns VectorOpResult with fault info if any page is inaccessible.
    element_index is set to 0 since we can't identify the specific element.
    """
    page_bytes = lamlet.params.page_bytes
    current_addr = start_addr
    while current_addr < end_addr:
        g_addr = GlobalAddress(bit_addr=current_addr * 8, params=lamlet.params)
        fault_type = lamlet.tlb.check_access(g_addr, is_write)
        if fault_type != TLBFaultType.NONE:
            return VectorOpResult(fault_type=fault_type, element_index=0)
        current_addr = ((current_addr // page_bytes) + 1) * page_bytes
    return VectorOpResult()


def get_memory_split(lamlet: 'Lamlet', g_addr: GlobalAddress, element_width: int,
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

        lumps.append((page_info.local_address.is_vpu, start_index, start_addr, end_addr))
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
        logger.info(f'  Section {i}: is_vpu={section.is_vpu}, partial={section.is_a_partial_element}, '
                   f'idx={section.start_index}, start=0x{section.start_address:x}, '
                   f'end=0x{section.end_address:x}')
    return sections


async def vload(lamlet: 'Lamlet', vd: int, addr: int, ordering: addresses.Ordering,
                n_elements: int, mask_reg: int | None, start_index: int,
                parent_span_id: int,
                reg_ordering: addresses.Ordering | None = None,
                stride_bytes: int | None = None) -> VectorOpResult:
    element_bytes = ordering.ew // 8
    if stride_bytes is not None and stride_bytes != element_bytes:
        return await vloadstorestride(lamlet, vd, addr, ordering, n_elements, mask_reg,
                                      start_index, is_store=False,
                                      parent_span_id=parent_span_id,
                                      reg_ordering=reg_ordering,
                                      stride_bytes=stride_bytes)
    else:
        return await vloadstore(lamlet, vd, addr, ordering, n_elements, mask_reg, start_index,
                                is_store=False, parent_span_id=parent_span_id,
                                reg_ordering=reg_ordering)


async def vstore(lamlet: 'Lamlet', vs: int, addr: int, ordering: addresses.Ordering,
                 n_elements: int, mask_reg: int | None, start_index: int,
                 parent_span_id: int,
                 stride_bytes: int | None = None) -> VectorOpResult:
    element_bytes = ordering.ew // 8
    if stride_bytes is not None and stride_bytes != element_bytes:
        return await vloadstorestride(lamlet, vs, addr, ordering, n_elements, mask_reg,
                                      start_index, is_store=True,
                                      parent_span_id=parent_span_id,
                                      stride_bytes=stride_bytes)
    else:
        return await vloadstore(lamlet, vs, addr, ordering, n_elements, mask_reg, start_index,
                                is_store=True, parent_span_id=parent_span_id)


async def vloadstore(lamlet: 'Lamlet', reg_base: int, addr: int, ordering: addresses.Ordering,
                     n_elements: int, mask_reg: int | None, start_index: int, is_store: bool,
                     parent_span_id: int,
                     reg_ordering: addresses.Ordering | None = None,
                     stride_bytes: int | None = None) -> VectorOpResult:
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
    mem_ew = ordering.ew

    # For loads, reg_ordering specifies the register element width (defaults to memory ew)
    # For stores, register ordering comes from the register file state
    # We need to determine this BEFORE page checking since n_elements is in reg_ew units
    if is_store:
        # For stores, caller should not specify reg_ordering - we get it from register file
        assert reg_ordering is None, "reg_ordering should not be specified for stores"
        reg_ordering = lamlet.vrf_ordering[reg_base]
        assert reg_ordering is not None, f"Register v{reg_base} has no ordering set"
    elif reg_ordering is None:
        # For loads without explicit reg_ordering, use memory ordering
        reg_ordering = ordering
    reg_ew = reg_ordering.ew

    # Check all pages for access before dispatching
    # n_elements is count of register elements, so use reg_ew for byte size
    element_bytes = reg_ew // 8
    result = check_pages_for_access(lamlet, addr, n_elements, element_bytes, is_store)
    if not result.success:
        # Reduce n_elements to only process up to the faulting element
        n_elements = result.element_index

    if n_elements == 0:
        return result

    size = (n_elements * reg_ew) // 8
    wb = lamlet.params.word_bytes

    # This is an identifier that groups a number of writes to a vector register together.
    # These writes are guanteed to work on separate bytes so that the write order does not matter.
    writeset_ident = ident_query.get_writeset_ident(lamlet)

    vline_bits = lamlet.params.maxvl_bytes * 8
    n_vlines = (reg_ew * n_elements + vline_bits - 1) // vline_bits
    for vline_reg in range(reg_base, reg_base+n_vlines):
        lamlet.vrf_ordering[vline_reg] = Ordering(word_order=ordering.word_order, ew=reg_ew)

    base_reg_addr = addresses.RegAddr(
        reg=reg_base, addr=0, params=lamlet.params, ordering=reg_ordering)

    # reg_ew determines the size of elements we're moving (not mem_ew which is just memory ordering)
    for section in get_memory_split(lamlet, g_addr, reg_ew, n_elements, start_index):
        if section.is_a_partial_element:
            reg_addr = base_reg_addr.offset_bytes(section.start_address - g_addr.addr)
            # The partial is either the start of an element or the end of an element.
            # Either the starting_addr or the ending_addr must be a cache line boundary
            start_is_cacheline_boundary = section.start_address % lamlet.params.cache_line_bytes == 0
            end_is_cacheline_boundary = section.end_address % lamlet.params.cache_line_bytes == 0
            if not (start_is_cacheline_boundary or end_is_cacheline_boundary):
                logger.error(f'Partial element not at cache line boundary: '
                             f'start=0x{section.start_address:x}, end=0x{section.end_address:x}, '
                             f'cache_line_bytes={lamlet.params.cache_line_bytes}, '
                             f'start_idx={section.start_index}')
            assert start_is_cacheline_boundary or end_is_cacheline_boundary
            assert not (start_is_cacheline_boundary and end_is_cacheline_boundary)
            starting_g_addr = GlobalAddress(bit_addr=section.start_address*8, params=lamlet.params)
            k_maddr = lamlet.to_k_maddr(starting_g_addr)
            assert reg_ew % 8 == 0
            mask_index = section.start_index // lamlet.params.j_in_l
            size = section.end_address - section.start_address
            if section.is_vpu:
                dst = reg_base + (section.start_index * reg_ew)//(lamlet.params.vline_bytes * 8)
                kinstr: kinstructions.KInstr
                if size <= 1:
                    dst_offset = ((section.start_index * reg_ew) % (lamlet.params.vline_bytes * 8))//8
                    bit_mask = (1 << 8) - 1
                    if is_store:
                        kinstr = kinstructions.StoreByte(
                            src=reg_addr,
                            dst=k_maddr,
                            bit_mask=bit_mask,
                            writeset_ident=writeset_ident,
                            mask_reg=mask_reg,
                            mask_index=mask_index,
                            ident=writeset_ident,
                        )
                    else:
                        kinstr = kinstructions.LoadByte(
                            dst=reg_addr,
                            src=k_maddr,
                            bit_mask=bit_mask,
                            writeset_ident=writeset_ident,
                            mask_reg=mask_reg,
                            mask_index=mask_index,
                            ident=writeset_ident,
                        )
                else:
                    instr_ident = await ident_query.get_instr_ident(lamlet, 2)
                    if is_store:
                        byte_mask = [0] * wb
                        start_word_byte = k_maddr.addr % wb
                        for byte_index in range(start_word_byte, start_word_byte + size):
                            byte_mask[byte_index] = 1
                        byte_mask_as_int = utils.list_of_uints_to_uint(byte_mask, width=1)
                        kinstr = kinstructions.StoreWord(
                            src=reg_addr,
                            dst=k_maddr,
                            byte_mask=byte_mask_as_int,
                            writeset_ident=writeset_ident,
                            mask_reg=mask_reg,
                            mask_index=mask_index,
                            instr_ident=instr_ident,
                        )
                    else:
                        byte_mask = [0] * wb
                        start_word_byte = reg_addr.offset_in_word % wb
                        for byte_index in range(start_word_byte, start_word_byte + size):
                            byte_mask[byte_index] = 1
                        byte_mask_as_int = utils.list_of_uints_to_uint(byte_mask, width=1)
                        kinstr = kinstructions.LoadWord(
                            dst=reg_addr,
                            src=k_maddr,
                            byte_mask=byte_mask_as_int,
                            writeset_ident=writeset_ident,
                            mask_reg=mask_reg,
                            mask_index=mask_index,
                            instr_ident=instr_ident,
                        )
                await lamlet.add_to_instruction_buffer(kinstr, parent_span_id)
            else:
                element_offset = starting_g_addr.bit_addr % (lamlet.params.word_bytes * 8)
                assert element_offset % 8 == 0
                assert reg_ew % 8 == 0
                start_is_page_boundary = section.start_address % lamlet.params.page_bytes == 0
                if start_is_page_boundary:
                    # We're the second segment of the element
                    start_byte_in_element = (reg_ew - element_offset)//8
                else:
                    # We're the first segment of the element
                    start_byte_in_element = (element_offset)//8
                if is_store:
                    await vstore_scalar_partial(
                        lamlet, vd=reg_base, addr=section.start_address, size=size,
                        src_ordering=ordering, mask_reg=mask_reg, mask_index=mask_index,
                        element_index=section.start_index, writeset_ident=writeset_ident,
                        start_byte=start_byte_in_element)
                else:
                    await vload_scalar_partial(
                        lamlet, vd=reg_base, addr=section.start_address, size=size,
                        dst_ordering=ordering, mask_reg=mask_reg, mask_index=mask_index,
                        element_index=section.start_index, writeset_ident=writeset_ident,
                        start_byte=start_byte_in_element, parent_span_id=parent_span_id)
        else:
            if section.is_vpu:
                section_elements = ((section.end_address - section.start_address) * 8)//reg_ew
                starting_g_addr = GlobalAddress(bit_addr=section.start_address*8, params=lamlet.params)
                lamlet.check_element_width(starting_g_addr, section.end_address - section.start_address, mem_ew)
                k_maddr = lamlet.to_k_maddr(starting_g_addr)

                l_cache_line_bytes = lamlet.params.cache_line_bytes * lamlet.params.k_in_l
                assert section.start_address//l_cache_line_bytes == (section.end_address-1)//l_cache_line_bytes

                if is_store:
                    instr_ident = await ident_query.get_instr_ident(lamlet)
                    kinstr = kinstructions.Store(
                        src=reg_base,
                        k_maddr=k_maddr,
                        start_index=section.start_index,
                        n_elements=section_elements,
                        src_ordering=reg_ordering,
                        mask_reg=mask_reg,
                        writeset_ident=writeset_ident,
                        instr_ident=instr_ident,
                    )
                else:
                    instr_ident = await ident_query.get_instr_ident(lamlet)
                    kinstr = kinstructions.Load(
                        dst=reg_base,
                        k_maddr=k_maddr,
                        start_index=section.start_index,
                        n_elements=section_elements,
                        dst_ordering=reg_ordering,
                        mask_reg=mask_reg,
                        writeset_ident=writeset_ident,
                        instr_ident=instr_ident,
                    )
                await lamlet.add_to_instruction_buffer(kinstr, parent_span_id)
            else:
                section_elements = ((section.end_address - section.start_address) * 8)//reg_ew
                await vloadstore_scalar(lamlet, reg_base, section.start_address, ordering,
                                        section_elements, mask_reg, section.start_index,
                                        writeset_ident, is_store, parent_span_id)
    return result


async def vloadstorestride(lamlet: 'Lamlet', reg_base: int, addr: int,
                           ordering: addresses.Ordering, n_elements: int,
                           mask_reg: int | None, start_index: int,
                           is_store: bool, parent_span_id: int, stride_bytes: int,
                           reg_ordering: addresses.Ordering | None = None) -> VectorOpResult:
    """
    Handle strided vector loads/stores using LoadStride/StoreStride instructions.

    Strided access means elements are at addr, addr+stride, addr+2*stride, etc.
    Elements are placed contiguously in the register file.

    LoadStride/StoreStride is limited to j_in_l elements per instruction,
    so we process in chunks.
    """
    g_addr = GlobalAddress(bit_addr=addr * 8, params=lamlet.params)
    mem_ew = ordering.ew

    if reg_ordering is None:
        reg_ordering = ordering
    reg_ew = reg_ordering.ew

    writeset_ident = ident_query.get_writeset_ident(lamlet)

    # Set up register file ordering for registers
    vline_bits = lamlet.params.maxvl_bytes * 8
    n_vlines = (reg_ew * n_elements + vline_bits - 1) // vline_bits
    for vline_reg in range(reg_base, reg_base + n_vlines):
        lamlet.vrf_ordering[vline_reg] = Ordering(word_order=ordering.word_order, ew=reg_ew)

    # Process in chunks of j_in_l elements
    # Active elements are [start_index, n_elements), so n_active = n_elements - start_index
    j_in_l = lamlet.params.j_in_l
    n_active = n_elements - start_index
    completion_sync_idents = []
    for chunk_offset in range(0, n_active, j_in_l):
        chunk_n = min(j_in_l, n_active - chunk_offset)
        # g_addr is the base address (element 0's location)
        chunk_addr = addr
        chunk_g_addr = GlobalAddress(bit_addr=chunk_addr * 8, params=lamlet.params)
        instr_ident = await ident_query.get_instr_ident(
            lamlet, n_idents=lamlet.params.word_bytes + 1)

        if is_store:
            kinstr = StoreStride(
                src=reg_base,
                g_addr=chunk_g_addr,
                start_index=start_index + chunk_offset,
                n_elements=chunk_n,
                src_ordering=reg_ordering,
                mask_reg=mask_reg,
                writeset_ident=writeset_ident,
                instr_ident=instr_ident,
                stride_bytes=stride_bytes,
            )
        else:
            kinstr = LoadStride(
                dst=reg_base,
                g_addr=chunk_g_addr,
                start_index=start_index + chunk_offset,
                n_elements=chunk_n,
                dst_ordering=reg_ordering,
                mask_reg=mask_reg,
                writeset_ident=writeset_ident,
                instr_ident=instr_ident,
                stride_bytes=stride_bytes,
            )
        await lamlet.add_to_instruction_buffer(kinstr, parent_span_id)
        kinstr_span_id = lamlet.monitor.get_kinstr_span_id(instr_ident)

        # Use instr_ident for fault sync, instr_ident + 1 for completion sync
        fault_sync_ident = instr_ident
        completion_sync_ident = (instr_ident + 1) % lamlet.params.max_response_tags

        # Participate in both syncs so kamlets can coordinate internally
        lamlet.monitor.create_sync_local_span(fault_sync_ident, 0, -1, kinstr_span_id)
        lamlet.synchronizer.local_event(fault_sync_ident, value=None)
        lamlet.monitor.create_sync_local_span(completion_sync_ident, 0, -1, kinstr_span_id)
        lamlet.synchronizer.local_event(completion_sync_ident)
        completion_sync_idents.append(completion_sync_ident)

        # Wait for fault sync to check for TLB faults
        global_min_fault = await wait_for_fault_sync(lamlet, fault_sync_ident)
        if global_min_fault is not None:
            fault_type = TLBFaultType.WRITE_FAULT if is_store else TLBFaultType.READ_FAULT
            return VectorOpResult(
                fault_type=fault_type, element_index=global_min_fault,
                completion_sync_idents=completion_sync_idents)

    return VectorOpResult(
        completion_sync_idents=completion_sync_idents)


async def vload_indexed_unordered(lamlet: 'Lamlet', vd: int, base_addr: int, index_reg: int,
                                  index_ew: int, data_ew: int, n_elements: int,
                                  mask_reg: int | None, start_index: int,
                                  parent_span_id: int) -> VectorOpResult:
    """Handle unordered indexed vector loads (vluxei).

    Indexed (gather) load: element i is loaded from address (base_addr + index_reg[i]).
    """
    return await _vloadstore_indexed_unordered(
        lamlet, reg=vd, base_addr=base_addr, index_reg=index_reg,
        index_ew=index_ew, data_ew=data_ew, n_elements=n_elements,
        mask_reg=mask_reg, start_index=start_index,
        parent_span_id=parent_span_id, is_store=False)


async def vstore_indexed_unordered(lamlet: 'Lamlet', vs: int, base_addr: int, index_reg: int,
                                   index_ew: int, data_ew: int, n_elements: int,
                                   mask_reg: int | None, start_index: int,
                                   parent_span_id: int) -> VectorOpResult:
    """Handle unordered indexed vector stores (vsuxei).

    Indexed (scatter) store: element i is stored to address (base_addr + index_reg[i]).
    """
    return await _vloadstore_indexed_unordered(
        lamlet, reg=vs, base_addr=base_addr, index_reg=index_reg,
        index_ew=index_ew, data_ew=data_ew, n_elements=n_elements,
        mask_reg=mask_reg, start_index=start_index,
        parent_span_id=parent_span_id, is_store=True)


async def _vloadstore_indexed_unordered(
        lamlet: 'Lamlet', reg: int, base_addr: int, index_reg: int,
        index_ew: int, data_ew: int, n_elements: int,
        mask_reg: int | None, start_index: int,
        parent_span_id: int, is_store: bool) -> VectorOpResult:
    """Shared implementation for unordered indexed vector loads and stores.

    The index register contains byte offsets with element width index_ew.
    The data element width comes from SEW (data_ew).
    """
    g_addr = GlobalAddress(bit_addr=base_addr * 8, params=lamlet.params)
    data_ordering = Ordering(word_order=lamlet.word_order, ew=data_ew)
    index_ordering = Ordering(word_order=lamlet.word_order, ew=index_ew)

    writeset_ident = ident_query.get_writeset_ident(lamlet)

    if not is_store:
        # Set up register file ordering for destination registers
        vline_bits = lamlet.params.maxvl_bytes * 8
        n_vlines = (data_ew * n_elements + vline_bits - 1) // vline_bits
        for vline_reg in range(reg, reg + n_vlines):
            lamlet.vrf_ordering[vline_reg] = data_ordering

    # If index bound active and all pages in the bounded range are accessible,
    # skip per-element fault detection. Otherwise fall back to normal fault sync
    # since only the kamlets can identify which element faulted.
    skip_fault_wait = False
    if lamlet.index_bound_bits > 0:
        end_addr = base_addr + (1 << lamlet.index_bound_bits)
        if check_page_range(lamlet, base_addr, end_addr, is_write=is_store).success:
            skip_fault_wait = True

    # Process in chunks of elements_in_vline elements (max one vline per kinstr)
    # Active elements are [start_index, n_elements), so n_active = n_elements - start_index
    elements_in_vline = lamlet.params.vline_bytes * 8 // data_ew
    n_active = n_elements - start_index

    fault_sync_idents = []
    completion_sync_idents = []

    for chunk_idx, chunk_offset in enumerate(range(0, n_active, elements_in_vline)):
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
            )
        await lamlet.add_to_instruction_buffer(kinstr, parent_span_id)
        kinstr_span_id = lamlet.monitor.get_kinstr_span_id(instr_ident)

        # Use instr_ident for fault sync, instr_ident + 1 for completion sync
        fault_sync_ident = instr_ident
        completion_sync_ident = (
            (instr_ident + 1) % lamlet.params.max_response_tags)

        # Completion sync: participate immediately for all chunks
        lamlet.monitor.create_sync_local_span(
            completion_sync_ident, 0, -1, kinstr_span_id)
        lamlet.synchronizer.local_event(completion_sync_ident)
        completion_sync_idents.append(completion_sync_ident)

        # Fault sync: create span for all chunks, but only chunk 0
        # fires immediately. Later chunks are chained so the
        # synchronizer fires them when the previous chunk resolves.
        lamlet.monitor.create_sync_local_span(
            fault_sync_ident, 0, -1, kinstr_span_id)
        if skip_fault_wait:
            lamlet.synchronizer.local_event(fault_sync_ident, value=None)
        elif chunk_idx == 0:
            lamlet.synchronizer.local_event(fault_sync_ident, value=None)
            fault_sync_idents.append(fault_sync_ident)
        else:
            lamlet.synchronizer.chain_fault_sync(
                fault_sync_idents[-1], fault_sync_ident)
            fault_sync_idents.append(fault_sync_ident)

    # Wait for the fault sync cascade to complete. Awaiting the last
    # one is sufficient since the chain is sequential.
    if fault_sync_idents:
        last_fsid = fault_sync_idents[-1]
        global_min_fault = await wait_for_fault_sync(lamlet, last_fsid)
        if global_min_fault is not None:
            # The first non-None min_value in the chain is the actual
            # faulting element. Later chunks got 0 injected by the chain.
            for fsid in fault_sync_idents:
                min_val = lamlet.synchronizer.get_min_value(fsid)
                if min_val is not None:
                    global_min_fault = min_val
                    break
            fault_type = (TLBFaultType.WRITE_FAULT if is_store
                          else TLBFaultType.READ_FAULT)
            return VectorOpResult(
                fault_type=fault_type, element_index=global_min_fault,
                completion_sync_idents=completion_sync_idents)

    return VectorOpResult(
        completion_sync_idents=completion_sync_idents)


async def vloadstore_scalar(
        lamlet: 'Lamlet', vd: int, addr: int, ordering: Ordering, n_elements: int,
        mask_reg: int, start_index: int, writeset_ident: int, is_store: bool,
        parent_span_id: int):
    """
    Reads elements from the scalar memory and sends them to the appropriate kamlets where they
    will update the vector register.

    FIXME: This function is untested. Add tests for vector loads/stores to scalar memory.
    """
    for element_index in range(start_index, start_index+n_elements):
        start_addr_bits = addr * 8 + (element_index - start_index) * ordering.ew
        g_addr = GlobalAddress(bit_addr=start_addr_bits, params=lamlet.params)
        scalar_addr = g_addr.to_scalar_addr(lamlet.tlb)
        vw_index = element_index % lamlet.params.j_in_l
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
            lamlet.params, ordering.word_order, vw_index)
        wb = lamlet.params.word_bytes
        mask_index = element_index // lamlet.params.j_in_l
        if ordering.ew in (1, 8):
            # We're just sending a byte
            if ordering.ew == 1:
                bit_mask = 1 << (addr.bit_addr % 8)
            else:
                bit_mask = (1 << 8) - 1
            if is_store:
                kinstr = kinstructions.StoreByte(
                    src=vd,
                    bit_mask=bit_mask,
                    mask_reg=mask_reg,
                    mask_index=mask_index,
                    writeset_ident=writeset_ident,
                )
            else:
                byte_imm = lamlet.scalar.get_memory(scalar_addr, 1)[0]
                instr_ident = await ident_query.get_instr_ident(lamlet)
                kinstr = kinstructions.LoadImmByte(
                    dst=vd,
                    imm=byte_imm,
                    bit_mask=bit_mask,
                    mask_reg=mask_reg,
                    mask_index=mask_index,
                    writeset_ident=writeset_ident,
                    instr_ident=instr_ident,
                )
        else:
            # We're sending a word
            word_addr = (scalar_addr//wb) * wb
            byte_mask = [0] * wb
            start_byte = element_index//lamlet.params.j_in_l * ordering.ew//8
            if ordering.ew == 1:
                end_byte = start_byte
            else:
                end_byte = start_byte + ordering.ew//8 - 1
            for byte_index in range(start_byte, end_byte+1):
                byte_mask[byte_index] = 1
            byte_mask_as_int = utils.list_of_uints_to_uint(byte_mask, width=1)
            if is_store:
                raise NotImplementedError("StoreWord for scalar memory not yet implemented")
            else:
                word_imm = lamlet.scalar.get_memory(word_addr, wb)
                instr_ident = await ident_query.get_instr_ident(lamlet)
                kinstr = kinstructions.LoadImmWord(
                    dst=vd,
                    imm=word_imm,
                    byte_mask=byte_mask_as_int,
                    mask_reg=mask_reg,
                    mask_index=mask_index,
                    writeset_ident=writeset_ident,
                    instr_ident=instr_ident,
                )
        await lamlet.add_to_instruction_buffer(kinstr, parent_span_id, k_index=k_index)


async def vload_scalar_partial(lamlet: 'Lamlet', vd: int, addr: int, size: int,
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
    assert start_byte + size < lamlet.params.word_bytes
    g_addr = GlobalAddress(bit_addr=addr*8, params=lamlet.params)
    scalar_addr = g_addr.to_scalar_addr(lamlet.tlb)
    vw_index = element_index % lamlet.params.j_in_l
    k_index, j_in_k_index = addresses.vw_index_to_k_indices(
        lamlet.params, dst_ordering.word_order, vw_index)
    kinstr: kinstructions.KInstr
    instr_ident = await ident_query.get_instr_ident(lamlet)
    if size == 1:
        bit_mask = (1 << 8) - 1
        byte_imm = lamlet.scalar.get_memory(scalar_addr.addr, 1)[0]
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
        word_addr = scalar_addr - start_byte
        word_imm = lamlet.scalar.get_memory(word_addr, lamlet.params.word_bytes)
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


async def vstore_scalar_partial(lamlet: 'Lamlet', vd: int, addr: int, size: int,
                                src_ordering: Ordering, mask_reg: int, mask_index: int,
                                element_index: int, writeset_ident: int, start_byte: int):
    """FIXME: This function is untested. Add tests for vector loads/stores to scalar memory."""
    raise NotImplementedError("vstore_scalar_partial not yet implemented")


async def handle_read_mem_word_req(lamlet: 'Lamlet', header, scalar_addr: int):
    """Handle unordered READ_MEM_WORD_REQ: read from scalar memory and respond immediately."""
    wb = lamlet.params.word_bytes
    word_addr = scalar_addr - (scalar_addr % wb)
    data = lamlet.scalar.get_memory(scalar_addr, wb)
    resp_header = TaggedHeader(
        target_x=header.source_x,
        target_y=header.source_y,
        source_x=lamlet.instr_x,
        source_y=lamlet.instr_y,
        message_type=MessageType.READ_MEM_WORD_RESP,
        send_type=SendType.SINGLE,
        length=2,
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
        f'scalar_read addr=0x{scalar_addr:x}, word_addr=0x{word_addr:x}, data={data.hex()}')
    await lamlet.send_packet(packet, jamlet, Direction.N, port=0,
                             parent_span_id=transaction_span_id)
    logger.debug(
        f'{lamlet.clock.cycle}: lamlet: READ_MEM_WORD_REQ addr=0x{scalar_addr:x} '
        f'-> ({header.source_x},{header.source_y}) data={data.hex()}')


async def handle_write_mem_word_req(lamlet: 'Lamlet', header: WriteMemWordHeader,
                                    scalar_addr: int, src_word: bytes):
    """Handle WRITE_MEM_WORD_REQ: write to scalar memory and send response."""
    wb = lamlet.params.word_bytes
    word_addr = scalar_addr - (scalar_addr % wb)
    src_start = header.tag
    dst_start = header.dst_byte_in_word
    n_bytes = header.n_bytes
    lamlet.scalar.set_memory(word_addr + dst_start, src_word[src_start:src_start + n_bytes])
    resp_header = TaggedHeader(
        target_x=header.source_x,
        target_y=header.source_y,
        source_x=lamlet.instr_x,
        source_y=lamlet.instr_y,
        message_type=MessageType.WRITE_MEM_WORD_RESP,
        send_type=SendType.SINGLE,
        length=1,
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
    logger.debug(
        f'{lamlet.clock.cycle}: lamlet: WRITE_MEM_WORD_REQ addr=0x{scalar_addr:x} '
        f'src_start={src_start} dst_start={dst_start} n_bytes={n_bytes} '
        f'-> ({header.source_x},{header.source_y})')
