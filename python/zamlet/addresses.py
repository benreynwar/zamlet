"""
Address Space Management for RISC-V VPU Simulator

This module manages the various address spaces and coordinate systems used in the VPU.

Address Translation Chain:
    GlobalAddress → VPUAddress → LogicalVLineAddress → PhysicalVLineAddress → KMAddr → JSAddr

Key Types:
    - GlobalAddress: CPU-visible memory address
    - VPUAddress: Address within VPU memory space
    - LogicalVLineAddress: Vector line address in logical (sequential) coordinates
    - PhysicalVLineAddress: Vector line address in physical (distributed) coordinates
    - KMAddr: Kamlet memory address
    - JSAddr: Jamlet SRAM address

Word Ordering (Ordering.word_order)
-----------------------------------
The `word_order` field in `Ordering` determines how jamlet coordinates (x, y) map
to the vector word index (vw_index). This controls which jamlet holds which word
of a vector line.

WordOrder.STANDARD:
    vw_index = j_y * (j_cols * k_cols) + j_x

    For a 2x1 grid of kamlets (k_cols=2, k_rows=1) with 1x1 jamlets each:
        jamlet (0, 0) → vw_index 0
        jamlet (1, 0) → vw_index 1

    Words are laid out row-major across the jamlet grid.

WordOrder.MOORE:
    Words are laid out following a Moore curve (closed space-filling curve)
    across the jamlet grid. Requires a square power-of-2 grid. Adjacent
    vw_indices map to spatially adjacent jamlets.

Logical vs Physical Element Coordinates
---------------------------------------
Instructions use **logical** element indices (0, 1, 2, 3...) which are sequential.
The hardware distributes elements across jamlets using **physical** coordinates.

Physical layout places one element per jamlet word, cycling through all jamlets
before moving to the next element position within a word. For a vline with
`j_in_l` jamlets and `elements_in_word` elements per 64-bit word:

    Logical element 0 → jamlet 0, element-in-word 0
    Logical element 1 → jamlet 1, element-in-word 0
    ...
    Logical element (j_in_l - 1) → jamlet (j_in_l - 1), element-in-word 0
    Logical element j_in_l → jamlet 0, element-in-word 1
    Logical element (j_in_l + 1) → jamlet 1, element-in-word 1
    ...

Once all positions in a vline are filled, continue to the next vline.

Conversion formulas:

    # Physical to logical
    elements_in_word = word_bytes * 8 // ew
    logical_element = element_in_word * j_in_l + jamlet_word_index

    # Logical to physical
    jamlet_word_index = logical_element % j_in_l
    element_in_word = logical_element // j_in_l

This matters when comparing MemMapping fields (src_ve/dst_ve are physical)
against instruction fields (start_index/n_elements are logical).
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict

from zamlet.moore import moore_d2xy, moore_xy2d
from zamlet.params import LamletParams


logger = logging.getLogger(__name__)

SizeBytes = int
SizeBits = int


class WordOrder(Enum):

    STANDARD = 0
    MOORE = 1


class MemoryType(Enum):
    """Type of memory region determining access behavior."""
    VPU = 'vpu'                          # VPU DRAM, always idempotent
    SCALAR_IDEMPOTENT = 'scalar_idem'    # Scalar memory, speculative access OK
    SCALAR_NON_IDEMPOTENT = 'scalar_non_idem'  # Scalar I/O, no speculative access, tracks accesses


def vw_index_to_j_coords(params: LamletParams, word_order: WordOrder,
                          vw_index: int):
    if word_order == WordOrder.STANDARD:
        j_x = vw_index % (params.j_cols * params.k_cols)
        j_y = vw_index // (params.j_cols * params.k_cols)
        return j_x, j_y
    elif word_order == WordOrder.MOORE:
        total_cols = params.j_cols * params.k_cols
        total_rows = params.j_rows * params.k_rows
        # Could extend to rectangles by appending square Moore curves.
        assert total_cols == total_rows, (
            f"MOORE requires square grid, got {total_cols}x{total_rows}"
        )
        assert total_cols & (total_cols - 1) == 0, (
            f"MOORE requires power-of-2 grid, got {total_cols}"
        )
        return moore_d2xy(total_cols, vw_index)
    else:
        raise NotImplementedError(f"Word order {word_order}")


def j_coords_to_vw_index(params: LamletParams, word_order: WordOrder,
                          j_x: int, j_y: int):
    if word_order == WordOrder.STANDARD:
        vw_index = j_y * (params.j_cols * params.k_cols) + j_x
        return vw_index
    elif word_order == WordOrder.MOORE:
        total_cols = params.j_cols * params.k_cols
        total_rows = params.j_rows * params.k_rows
        assert total_cols == total_rows, (
            f"MOORE requires square grid, got {total_cols}x{total_rows}"
        )
        assert total_cols & (total_cols - 1) == 0, (
            f"MOORE requires power-of-2 grid, got {total_cols}"
        )
        return moore_xy2d(total_cols, j_x, j_y)
    else:
        raise NotImplementedError(f"Word order {word_order}")


def vw_index_to_k_indices(params: LamletParams, word_order: WordOrder, vw_index: int):
    """
    Convert the word index in a vector line into a jamlet index.
    """
    j_x, j_y = vw_index_to_j_coords(params, word_order, vw_index)
    k_x = j_x // params.j_cols
    k_y = j_y // params.j_rows
    k_index = k_y * params.k_cols + k_x
    j_in_k_x = j_x % params.j_cols
    j_in_k_y = j_y % params.j_rows
    j_in_k_index = j_in_k_y * params.j_cols + j_in_k_x
    return k_index, j_in_k_index


def k_indices_to_j_coords(params: LamletParams, k_index: int, j_in_k_index: int):
    """Convert (k_index, j_in_k_index) to absolute jamlet coordinates (j_x, j_y)."""
    k_x = k_index % params.k_cols
    k_y = k_index // params.k_cols
    j_in_k_x = j_in_k_index % params.j_cols
    j_in_k_y = j_in_k_index // params.j_cols
    j_x = k_x * params.j_cols + j_in_k_x
    j_y = k_y * params.j_rows + j_in_k_y
    return j_x, j_y


def k_indices_to_vw_index(params: LamletParams, word_order, k_index: int, j_in_k_index: int):
    j_x, j_y = k_indices_to_j_coords(params, k_index, j_in_k_index)
    vw_index = j_coords_to_vw_index(params, word_order, j_x, j_y)
    return vw_index


@dataclass(frozen=True)
class Ordering:

    word_order: WordOrder
    ew: SizeBits


class TLBFaultType(Enum):
    NONE = 0
    PAGE_FAULT = 1
    READ_FAULT = 2
    WRITE_FAULT = 3
    NOT_WAITED = 4


@dataclass
class VectorOpResult:
    """Result of a vector operation - either success or fault."""
    fault_type: TLBFaultType = TLBFaultType.NONE
    element_index: int | None = None  # First element that faulted
    completion_sync_idents: List[int] | None = None
    last_fault_sync_ident: int | None = None

    @property
    def success(self) -> bool:
        return self.fault_type == TLBFaultType.NONE


class PageInfo:

    def __init__(self, global_address: 'GlobalAddress', local_address: 'LocalAddress',
                 fresh: List[bool], readable: bool = True, writable: bool = True):
        # Logical address
        self.global_address = global_address
        # Local address in the scalar or VPU memory
        # class stores information about reordering of the address space
        self.local_address = local_address
        # A list with an entry for each cache line size chunk.
        # Whether is has ever been read or written to.
        self.fresh = fresh
        # Permission flags
        self.readable = readable
        self.writable = writable

class TLB:

    def __init__(self, params: LamletParams):
        self.params = params
        # Maps global address to page infos
        self.pages: Dict[int, PageInfo] = {}
        # Maps vpu addresses to page infos
        self.vpu_pages: Dict[int, PageInfo] = {}
        self.vpu_freed_pages: List[int] = []
        self.vpu_lowest_never_used_page = 0
        # Scalar memory (single address space for both idempotent and non-idempotent)
        self.scalar_pages: Dict[int, PageInfo] = {}
        self.scalar_freed_pages: List[int] = []
        self.scalar_lowest_never_used_page = 0

    def get_lowest_free_page(self, memory_type: MemoryType):
        if memory_type == MemoryType.VPU:
            if self.vpu_freed_pages:
                page = self.vpu_freed_pages.pop(0)
            else:
                page = self.vpu_lowest_never_used_page
                next_page = self.vpu_lowest_never_used_page + self.params.page_bytes
                vpu_memory_bytes = self.params.k_in_l * self.params.kamlet_memory_bytes
                if next_page > vpu_memory_bytes:
                    raise MemoryError(
                        f'Out of VPU memory: requested page at {hex(page)}, '
                        f'but only {hex(vpu_memory_bytes)} bytes available'
                    )
                self.vpu_lowest_never_used_page = next_page
        else:
            # Both SCALAR_IDEMPOTENT and SCALAR_NON_IDEMPOTENT use the same address space
            if self.scalar_freed_pages:
                page = self.scalar_freed_pages.pop(0)
            else:
                page = self.scalar_lowest_never_used_page
                next_page = self.scalar_lowest_never_used_page + self.params.page_bytes
                if next_page > self.params.scalar_memory_bytes:
                    raise MemoryError(
                        f'Out of scalar memory: requested page at {hex(page)}, '
                        f'but only {hex(self.params.scalar_memory_bytes)} bytes available'
                    )
                self.scalar_lowest_never_used_page = next_page
        return page

    def allocate_memory(self, address: 'GlobalAddress', size: SizeBytes, memory_type: MemoryType,
                        ordering: Ordering | None, readable: bool = True, writable: bool = True):
        logger.info(f'Allocating memory to address {hex(address.addr)} type={memory_type.value}')
        assert size % self.params.page_bytes == 0
        for index in range(size//self.params.page_bytes):
            logical_page_address = address.addr + index * self.params.page_bytes
            global_address = GlobalAddress(bit_addr=logical_page_address*8, params=self.params)
            physical_page_address = self.get_lowest_free_page(memory_type)
            local_address = LocalAddress(
                memory_type=memory_type,
                ordering=ordering,
                bit_addr=physical_page_address*8,
                )
            assert logical_page_address not in self.pages
            n_cache_lines = self.params.page_bytes//self.params.cache_line_bytes//self.params.k_in_l
            info = PageInfo(
                global_address=global_address,
                local_address=local_address,
                fresh=[True]*n_cache_lines,
                readable=readable,
                writable=writable,
                )
            if memory_type == MemoryType.VPU:
                self.vpu_pages[physical_page_address] = info
            else:
                self.scalar_pages[physical_page_address] = info
            self.pages[logical_page_address] = info

            global_end = logical_page_address + self.params.page_bytes - 1
            l_cache_line_bytes = self.params.cache_line_bytes * self.params.k_in_l
            memory_loc_start = physical_page_address // l_cache_line_bytes
            memory_loc_end = (physical_page_address + self.params.page_bytes - 1) // l_cache_line_bytes
            logger.debug(
                f'PAGE_ALLOC: global=0x{logical_page_address:x}-0x{global_end:x} -> '
                f'physical=0x{physical_page_address:x} memory_loc=0x{memory_loc_start:x}-0x{memory_loc_end:x} '
                f'type={memory_type.value}'
            )

    def release_memory(self, address: 'GlobalAddress', size: SizeBytes):
        assert size % self.params.page_bytes == 0
        for index in range(size//self.params.page_bytes):
            logical_page_address = address.addr + index * self.params.page_bytes
            info = self.pages.pop(logical_page_address)
            memory_type = info.local_address.memory_type
            if memory_type == MemoryType.VPU:
                self.vpu_freed_pages.append(info.local_address.addr)
                self.vpu_pages.pop(info.local_address.addr)
            else:
                self.scalar_freed_pages.append(info.local_address.addr)
                self.scalar_pages.pop(info.local_address.addr)

    def get_page_info(self, address: 'GlobalAddress') -> PageInfo:
        assert address.addr % self.params.page_bytes == 0
        if address.addr not in self.pages:
            raise ValueError(f'{hex(address.addr)} not in page table')
        return self.pages[address.addr]

    def check_access(self, address: 'GlobalAddress', is_write: bool) -> TLBFaultType:
        """Check if access to address is allowed. Returns fault type or NONE."""
        page_addr = (address.addr // self.params.page_bytes) * self.params.page_bytes
        if page_addr not in self.pages:
            return TLBFaultType.PAGE_FAULT
        page_info = self.pages[page_addr]
        if is_write and not page_info.writable:
            return TLBFaultType.WRITE_FAULT
        if not is_write and not page_info.readable:
            return TLBFaultType.READ_FAULT
        return TLBFaultType.NONE

    def get_is_fresh(self, address: 'GlobalAddress') -> bool:
        page_addr = address.get_page()
        page_info = self.get_page_info(page_addr)
        page_offset = address.addr - page_addr.addr
        cache_line_index = page_offset // self.params.cache_line_bytes // self.params.k_in_l
        cache_lines_in_page = (
                self.params.page_bytes // self.params.cache_line_bytes // self.params.k_in_l)
        assert cache_line_index < cache_lines_in_page
        return page_info.fresh[cache_line_index]

    def set_not_fresh(self, address: 'GlobalAddress'):
        page_address = address.get_page()
        page_info = self.get_page_info(page_address)
        page_offset = address.addr - page_info.global_address.addr
        cache_line_index = page_offset // self.params.cache_line_bytes // self.params.k_in_l
        is_fresh = page_info.fresh[cache_line_index]
        assert is_fresh
        page_info.fresh[cache_line_index] = False

    def get_page_info_from_vpu_addr(self, address: 'VPUAddress') -> PageInfo:
        assert address.addr % self.params.page_bytes == 0
        if address.addr not in self.vpu_pages:
            raise ValueError(f'{address} not in page table')
        return self.vpu_pages[address.addr]


@dataclass(frozen=True)
class GlobalAddress:
    """
    An address in the overall CPU-visible address space.

    This is the starting point for address translation. Use TLB methods to
    convert to VPU or scalar addresses.
    """
    bit_addr: int
    params: LamletParams

    @property
    def addr(self):
        return self.bit_addr//8

    def bit_offset(self, n_bits):
        return GlobalAddress(bit_addr=self.bit_addr+n_bits, params=self.params)

    def offset_bytes(self, offset):
        return GlobalAddress(self.bit_addr + offset*8, self.params)

    def get_page(self):
        return GlobalAddress(bit_addr=(self.addr//self.params.page_bytes)*self.params.page_bytes*8, params=self.params)

    def get_cache_line(self):
        l_cache_bytes = self.params.cache_line_bytes * self.params.k_in_l
        return GlobalAddress(bit_addr=(self.addr//l_cache_bytes) * l_cache_bytes * 8, params=self.params)

    def is_vpu(self, tlb):
        page_address = self.get_page()
        page_info = tlb.get_page_info(page_address)
        return page_info.local_address.is_vpu

    def to_vpu_addr(self, tlb):
        page_address = self.get_page()
        page_info = tlb.get_page_info(page_address)
        assert page_info.local_address.is_vpu
        page_bit_offset = self.bit_addr - page_address.bit_addr
        return VPUAddress(bit_addr=page_info.local_address.addr*8 + page_bit_offset,
                          ordering=page_info.local_address.ordering, params=self.params)

    def to_scalar_addr(self, tlb):
        page_address = self.get_page()
        page_info = tlb.get_page_info(page_address)
        assert not page_info.local_address.is_vpu
        page_bit_offset = self.bit_addr - page_address.bit_addr
        assert page_bit_offset % 8 == 0
        scalar_addr = page_info.local_address.addr + page_bit_offset//8
        return scalar_addr

    def to_logical_vline_addr(self, tlb):
        vpu_addr = self.to_vpu_addr(tlb)
        return vpu_addr.to_logical_vline_addr()

    def to_physical_vline_addr(self, tlb):
        logical_vline_addr = self.to_logical_vline_addr(tlb)
        return logical_vline_addr.to_physical_vline_addr()

    def to_k_maddr(self, tlb):
        physical_vline_addr = self.to_physical_vline_addr(tlb)
        return physical_vline_addr.to_k_maddr()

    def to_j_saddr(self, tlb, cache_table):
        k_maddr = self.to_k_maddr(tlb)
        return k_maddr.to_j_saddr(cache_table)


@dataclass(frozen=True)
class LocalAddress:
    memory_type: MemoryType
    bit_addr: int
    ordering: Ordering|None

    @property
    def addr(self):
        return self.bit_addr//8

    @property
    def is_vpu(self):
        return self.memory_type == MemoryType.VPU


@dataclass(frozen=True)
class VPUAddress:
    """
    An address in the VPU address space (post TLB translation).

    The bit_addr is a linear address into VPU memory. Convert to LogicalVLineAddress
    to work with vline-based operations.
    """
    bit_addr: int
    ordering: Ordering
    params: LamletParams

    @property
    def addr(self):
        return self.bit_addr//8

    def to_logical_vline_addr(self):
        vline_bytes = self.params.word_bytes * self.params.j_in_l
        vline_index = self.addr//vline_bytes
        bit_addr_in_vline = self.bit_addr % (vline_bytes * 8)
        return LogicalVLineAddress(
            index=vline_index,
            bit_addr=bit_addr_in_vline,
            ordering=self.ordering,
            params=self.params,
            )

    #def to_j_saddr(self, params, cache_table):
    #    logical_vline_addr = self.to_logical_vline_addr(params)
    #    return logical_vline_addr.to_j_saddr(params, cache_table)

    def to_global_addr(self, tlb: TLB) -> GlobalAddress:
        vpu_page_address = (self.bit_addr // self.params.page_bytes // 8) * self.params.page_bytes
        page_offset_bits = self.bit_addr - vpu_page_address * 8
        base_vpu_address = VPUAddress(bit_addr=vpu_page_address*8, ordering=self.ordering,
                                      params=self.params)
        info = tlb.get_page_info_from_vpu_addr(base_vpu_address)
        return GlobalAddress(
            bit_addr = info.global_address.bit_addr + page_offset_bits, params=self.params
            )

    def offset_bits(self, n_bits):
        return VPUAddress(
            self.bit_addr+n_bits,
            ordering=self.ordering,
            params=self.params,
            )


@dataclass(frozen=True)
class LogicalVLineAddress:
    """
    A bit address in a vline using logical (sequential) element ordering.

    In logical coordinates, elements are numbered sequentially: 0, 1, 2, 3...
    This matches how instructions specify start_index and n_elements.

    The bit_addr is the offset within the vline in logical coordinates, where
    consecutive elements are adjacent in the address space.

    Convert to PhysicalVLineAddress to get the actual hardware layout where
    elements are distributed across jamlets.
    """
    # Which vline in the VPU memory this is.
    index: int
    # It's useful to pass this with the address so we don't have to use the TLB again
    ordering: Ordering
    # The bit address within the vline (logical coordinates).
    bit_addr: int
    params: LamletParams

    @property
    def addr(self):
        return self.bit_addr//8

    def offset_bits(self, n_bits):
        new_bit_addr = self.bit_addr + n_bits
        new_index = self.index + new_bit_addr//(self.params.vline_bytes*8)
        new_bit_addr = new_bit_addr % (self.params.vline_bytes*8)
        return LogicalVLineAddress(index=new_index, ordering=self.ordering,
                                   bit_addr=new_bit_addr, params=self.params)

    def to_physical_vline_addr(self):
        '''
        Converts a bit address in a logical vline to a bit address in a
        physical vline.
        Does element reordering in the vector line.
        Doesn't worry about the word reordering due to jamlet order of vector.
        '''
        element_index = self.bit_addr//self.ordering.ew
        bit_in_element = self.bit_addr % self.ordering.ew
        # Get an intermed address.
        # This is after we've moved elements around but before we've reorganized the
        # jamlet order.
        physical_vline_bit_addr = (
                (element_index % self.params.j_in_l) * self.params.word_bytes*8 +
                (element_index // self.params.j_in_l) * self.ordering.ew +
                bit_in_element
                )
        return PhysicalVLineAddress(
            index=self.index,
            ordering=self.ordering,
            bit_addr=physical_vline_bit_addr,
            params=self.params,
            )

    #def to_j_saddr(self, params, cache_table):
    #    physical_vline_addr = self.to_physical_vline_addr(params)
    #    return physical_vline_addr.to_j_saddr(params, cache_table)

    def to_vpu_addr(self):
        vline_bits = self.params.j_in_l * self.params.word_bytes * 8
        vpu_bit_addr = (
            self.index * vline_bits +
            self.bit_addr
            )
        return VPUAddress(
            ordering=self.ordering,
            bit_addr=vpu_bit_addr,
            params=self.params,
            )

    def to_k_maddr(self):
        physical_addr = self.to_physical_vline_addr()
        return physical_addr.to_k_maddr()

    def to_global_addr(self, tlb: TLB):
        vpu_addr = self.to_vpu_addr()
        return vpu_addr.to_global_addr(tlb)



@dataclass(frozen=True)
class PhysicalVLineAddress:
    """
    A bit address in a vline using physical (distributed) element ordering.

    In physical coordinates, elements are distributed across jamlets:
        - Element 0 → jamlet 0, element-in-word 0
        - Element 1 → jamlet 1, element-in-word 0
        - ...
        - Element j_in_l → jamlet 0, element-in-word 1

    The bit_addr here reflects where data actually lives in hardware. Each jamlet
    holds one word of the vline, and elements cycle through jamlets before moving
    to the next position within a word.

    Use to_k_maddr() to convert to a specific kamlet's memory address.
    """
    # Which vline in the VPU memory this is.
    index: int
    # It's useful to pass this with the address so we don't have to use the TLB again
    # (I think it's just used for assertions)
    ordering: Ordering
    # The bit address within the vline (physical coordinates).
    bit_addr: int
    params: LamletParams

    @property
    def addr(self):
        return self.bit_addr//8

    def offset_bits(self, n_bits: int):
        incremented = self.bit_addr + n_bits
        return PhysicalVLineAddress(
            index=self.index + incremented//(self.params.vline_bytes*8),
            ordering=self.ordering,
            bit_addr=incremented % (self.params.vline_bytes * 8),
            params=self.params,
            )

    def to_k_maddr(self):
        vw_index = self.addr//self.params.word_bytes

        # This is the step that considers which vector word is mapped to which jamlet.
        # This mapping changes if we change the word order.
        k_index, j_in_k_index = vw_index_to_k_indices(self.params, self.ordering.word_order, vw_index)

        k_vline_bits = self.params.word_bytes * 8 * self.params.j_in_k
        k_memory_bit_addr = (
            # Base address of this vline in the k memory.
            self.index * k_vline_bits +
            # Offset for this jamlet
            j_in_k_index * self.params.word_bytes * 8 +
            # Offset within that word
            self.bit_addr % (self.params.word_bytes * 8)
            )
        k_maddr = KMAddr(
            k_index=k_index,
            ordering=self.ordering,
            bit_addr=k_memory_bit_addr,
            params=self.params,
            )
        return k_maddr

    #def to_j_saddr(self, params, cache_table):
    #    k_maddr = self.to_k_maddr(params)
    #    return k_maddr.to_j_saddr(params, cache_table)

    def to_logical_vline_addr(self):
        vw_index = self.bit_addr // (self.params.word_bytes * 8)
        assert self.params.word_bytes * 8 >= self.ordering.ew
        assert (self.params.word_bytes * 8) % self.ordering.ew == 0
        elements_in_word = (self.params.word_bytes * 8)//self.ordering.ew
        element_in_word_index = (self.bit_addr // self.ordering.ew) % elements_in_word
        element_index = vw_index + element_in_word_index * self.params.j_in_l
        logical_bit_addr = (
                element_index * self.ordering.ew +
                (self.bit_addr % self.ordering.ew)
            )
        return LogicalVLineAddress(
            index=self.index,
            ordering=self.ordering,
            bit_addr=logical_bit_addr,
            params=self.params,
            )

    def to_global_addr(self, tlb: TLB):
        logical_vline_addr = self.to_logical_vline_addr()
        return logical_vline_addr.to_global_addr(tlb)


@dataclass(frozen=True)
class KMAddr:
    """
    An address in a kamlet's memory space.

    Each kamlet has its own memory address space. The k_index identifies which
    kamlet, and bit_addr is the address within that kamlet's memory.

    The bit_addr encodes both which jamlet within the kamlet (j_in_k_index) and
    the offset within that jamlet's word. Use j_in_k_index property to extract
    the jamlet index.

    Use to_j_saddr() to convert to a specific jamlet's SRAM address (requires
    cache_table to determine cache slot).
    """
    k_index: int
    ordering: Ordering
    bit_addr: int
    params: LamletParams

    @property
    def addr(self):
        return self.bit_addr//8

    def bit_offset(self, n_bits):
        new_bit_addr=self.bit_addr+n_bits
        assert new_bit_addr >= 0
        return KMAddr(k_index=self.k_index, ordering=self.ordering,
                      bit_addr=new_bit_addr, params=self.params)

    def to_cache_slot(self, cache_table):
        cache_slot = cache_table.addr_to_slot(self)
        return cache_slot

    @property
    def j_in_k_index(self):
        j_in_k_index = (self.bit_addr // (self.params.word_bytes * 8)) % self.params.j_in_k
        return j_in_k_index

    def to_j_saddr(self, cache_table):
        wb = self.params.word_bytes
        # We're assuming for know that cache_line is bigger or equal to vline
        # We put one word from the cache params, line in each jamlet.
        # Then repeat that until we've distributed the cache line.
        cache_slot = self.to_cache_slot(cache_table)
        assert cache_slot is not None
        cache_line_offset = self.bit_addr % (self.params.cache_line_bytes * 8)
        cache_line_bytes_per_jamlet = self.params.cache_line_bytes//self.params.j_in_k
        assert cache_line_bytes_per_jamlet % wb == 0
        assert cache_line_bytes_per_jamlet >= wb
        k_vline_bits = wb * self.params.j_in_k * 8
        vline_index_in_cache_line = cache_line_offset // k_vline_bits
        offset_in_word = self.bit_addr % (wb * 8)
        address_in_sram = (
                # Base address of the cache line in the sram
                (cache_slot * cache_line_bytes_per_jamlet * 8) +
                # Offset of the vline in the sram
                vline_index_in_cache_line * wb * 8 +
                offset_in_word
                )
        return JSAddr(
            k_index=self.k_index,
            j_in_k_index=self.j_in_k_index,
            ordering=self.ordering,
            bit_addr=address_in_sram,
            params=self.params,
            )

    def to_physical_vline_addr(self) -> PhysicalVLineAddress:
        wb = self.params.word_bytes
        k_vline_bits = self.params.j_in_k * wb * 8
        index = self.bit_addr // k_vline_bits
        # We need to rearrange the words in a vline so that they match the order in a vector.
        j_in_k_index = (self.bit_addr // (wb * 8)) % self.params.j_in_k
        vw_index = k_indices_to_vw_index(self.params, self.ordering.word_order, self.k_index, j_in_k_index)
        bit_addr_in_physical_vline = (
            vw_index * wb * 8 +
            self.bit_addr % (wb * 8)
            )
        return PhysicalVLineAddress(
            index=index,
            bit_addr=bit_addr_in_physical_vline,
            ordering=self.ordering,
            params=self.params,
            )

    def to_logical_vline_addr(self) -> LogicalVLineAddress:
        physical_vline_addr = self.to_physical_vline_addr()
        logical_vline_addr = physical_vline_addr.to_logical_vline_addr()
        return logical_vline_addr

    def to_global_addr(self, tlb: TLB) -> GlobalAddress:
        physical_vline_addr = self.to_physical_vline_addr()
        return physical_vline_addr.to_global_addr(tlb)


@dataclass(frozen=True)
class JSAddr:
    """
    An address in a jamlet's SRAM (cache).

    This is the lowest level address - it specifies exactly where data lives
    in a specific jamlet's local SRAM. The (k_index, j_in_k_index) pair identifies
    the jamlet, and bit_addr is the offset within that jamlet's SRAM.

    The SRAM is organized by cache slots. Each slot holds a portion of a cache line
    (cache_line_bytes / j_in_k bytes per jamlet).
    """
    k_index: int
    # The jamlet in kamlet order is always the same.
    # We don't use j_index since the jamlets may be ordered in a different way.
    # j_index is mapped to match the index inside a vector which may change.
    # Jamlets can be specified by coords in (k_index, j_in_k_index) if we want
    # it to be constant.
    j_in_k_index: int
    ordering: Ordering
    bit_addr: int
    params: LamletParams

    @property
    def addr(self):
        return self.bit_addr//8

    def to_k_maddr(self, cache_table: 'cache_table.CacheTable'):
        # First we need to check the cache state
        j_cache_line_bits = self.params.cache_line_bytes * 8 // self.params.j_in_k
        cache_slot = self.bit_addr//j_cache_line_bits
        slot_info = cache_table.slot_states[cache_slot]
        vlines_in_cache_line = self.params.cache_line_bytes // (self.params.word_bytes * self.params.j_in_k)

        k_cache_line_bits = self.params.cache_line_bytes * 8
        k_memory_bit_addr = (
            # Base address of the cache line in the k memory
            slot_info.ident * k_cache_line_bits +
            # Address of the j word
            self.j_in_k_index * self.params.word_bytes * vlines_in_cache_line * 8 +
            self.bit_addr % (self.params.word_bytes * 8)
            )

        return KMAddr(
            k_index=self.k_index,
            ordering=self.ordering,
            bit_addr=k_memory_bit_addr,
            params=self.params,
            )

    def to_global_addr(self, tlb: TLB, cache_table: 'cache_table.CacheTable'):
        km_addr = self.to_k_maddr(cache_table)
        return km_addr.to_global_addr(tlb)


@dataclass(frozen=True)
class RegAddr:
    """
    A byte address in a vector register.

    Addresses a specific byte within a vector register. The addr field is a
    logical byte offset (sequential), not physical. Use element_index property
    to get which element this byte belongs to.
    """
    # The register number
    reg: int
    # The logical byte offset in that register
    addr: int
    ordering: Ordering
    params: LamletParams

    def valid(self):
        valid = 0 <= self.addr < self.params.vline_bytes
        valid &= 0 <= self.reg < self.params.n_vregs
        valid &= self.ordering.ew % 8 == 0
        return valid

    @property
    def eb(self):
        return self.ordering.ew // 8

    @property
    def element_index(self):
        assert self.valid()
        element_index = self.addr // self.eb
        return element_index

    @property
    def offset_in_element(self):
        assert self.valid()
        offset = self.addr % self.eb
        return offset

    @property
    def vw_index(self):
        e_index = self.element_index
        vw_index = e_index % self.params.j_in_l
        return vw_index

    @property
    def k_index(self):
        assert self.valid()
        k_index, _ = vw_index_to_k_indices(self.params, self.ordering.word_order, self.vw_index)
        return k_index

    @property
    def j_in_k_index(self):
        assert self.valid()
        _, j_in_k_index = vw_index_to_k_indices(self.params, self.ordering.word_order, self.vw_index)
        return j_in_k_index

    @property
    def offset_in_word(self):
        assert self.valid()
        # which element in the jamlet
        in_j_index = self.element_index//self.params.j_in_l
        # which byte in that element
        in_e_index = self.addr % self.eb
        offset = in_j_index * self.eb + in_e_index
        return offset

    def offset_bytes(self, n_bytes):
        new_addr = self.addr + n_bytes
        return RegAddr(
            reg=self.reg+new_addr//self.params.vline_bytes,
            addr=new_addr%(self.params.vline_bytes),
            ordering=self.ordering,
            params=self.params,
            )


class AddressConverter:

    def __init__(self, params: LamletParams, tlb: TLB):
        self.params = params
        self.tlb = tlb
        #self.cache_table = cache_table

    def to_global_addr(self, addr):
        if isinstance(addr, KMAddr):
            return addr.to_global_addr(self.tlb)
        if isinstance(addr, LogicalVLineAddress):
            return addr.to_global_addr(self.tlb)
        raise NotImplementedError

    def to_scalar_addr(self, addr: GlobalAddress):
        assert isinstance(addr, GlobalAddress)
        return addr.to_scalar_addr(self.tlb)

    def to_vpu_addr(self, addr):
        if isinstance(addr, GlobalAddress):
            return addr.to_vpu_addr(self.tlb)
        raise NotImplementedError

    def to_k_maddr(self, addr):
        if isinstance(addr, GlobalAddress):
            return addr.to_k_maddr(self.tlb)
        raise NotImplementedError
