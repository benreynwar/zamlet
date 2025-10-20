"""
Keep track of all the various address is a bit confusing.
Here we create some classes to try to keep track of and standardize the options.
"""

import logging
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple

from params import LamletParams


logger = logging.getLogger(__name__)

SizeBytes = int
SizeBits = int


class WordOrder(Enum):

    STANDARD = 0
    LOOP = 1


@dataclass
class Ordering:
    
    element_width: SizeBits
    word_order: List[Tuple[int, int]]

    def vw_index_to_k_indices(self, params: LamletParams, vw_index: int):
        """
        Convert the word index in a vector line into a jamlet index.
        """
        j_x, j_y = self.word_order[vw_index]
        k_x = j_x // params.j_cols
        k_y = j_y // params.j_rows
        k_index = k_y * params.k_cols + k_x
        j_in_k_x = j_x % params.j_cols
        j_in_k_y = j_y % params.j_rows
        j_in_k_index = j_in_k_y * params.j_cols + j_in_k_x
        return k_index, j_in_k_index

    def k_indices_to_vw_index(self, params: LamletParams, k_index: int, j_in_k_index: int):
        k_x = self.k_index % params.k_cols
        k_y = self.k_index // params.k_cols
        j_in_k_x = self.k_in_j_index % parms.j_cols
        j_in_k_y = self.k_in_j_index // parms.j_cols
        j_x = k_x * params.j_cols + j_in_k_x
        j_y = k_y * params.j_rows + j_in_k_y
        vw_index = word_order.index((j_x, j_y))
        return vw_index


class PageInfo:

    def __init__(self, global_address: 'GlobalAddress', local_address: 'LocalAddress', fresh: List[bool]):
        # Logical address
        self.global_address = global_address
        # Local address in the scalar or VPU memory
        # class stores information about reordering of the address space
        self.local_address = local_address
        # A list with an entry for each cache line size chunk.
        # Whether is has ever been read or written to.
        self.fresh = fresh


class TLB:

    def __init__(self, params: LamletParams):
        self.params = params
        # Maps global address to page infos
        self.pages = {}
        # Maps vpu addresses to page infos
        self.vpu_pages = {}
        # maps scalar addresses to page infos
        self.scalar_pages = {}

        self.scalar_freed_pages = []
        self.scalar_lowest_never_used_page = 0

        self.vpu_freed_pages = []
        self.vpu_lowest_never_used_page = -1

    def get_lowest_free_page(self, is_vpu):
        if not is_vpu:
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
        else:
            if self.vpu_freed_pages:
                page = self.vpu_freed_pages.pop(0)
            else:
                page = self.vpu_lowest_never_used_page
                next_page = self.vpu_lowest_never_used_page + self.params.page_bytes
                vpu_memory_bytes = self.params.k_in_l * self.params.kamlet_memory_bytes
                #logger.info(f'vpu memory bytes is {vpu_memory_bytes}={self.params.k_in_l}*{self.params.kamlet_memory_bytes}')
                if next_page > vpu_memory_bytes:
                    raise MemoryError(
                        f'Out of VPU memory: requested page at {hex(page)}, '
                        f'but only {hex(vpu_memory_bytes)} bytes available'
                    )
                self.vpu_lowest_never_used_page = next_page
        return page

    def allocate_memory(self, address: 'GlobalAddress', size: SizeBytes, is_vpu: bool, ordering: Ordering):
        logger.info(f'Allocating memory to address {hex(address.addr)}')
        assert size % self.params.page_bytes == 0
        for index in range(size//self.params.page_bytes):
            logical_page_address = address.addr + index * self.params.page_bytes
            physical_page_address = self.get_lowest_free_page(is_vpu)
            local_address = LocalAddress(
                is_vpu=is_vpu,
                ordering=ordering,
                addr=physical_page_address,
                )
            assert logical_page_address not in self.pages
            n_cache_lines = self.params.page_bytes//self.params.cache_line_bytes//self.params.k_in_l
            info = PageInfo(
                global_address=logical_page_address,
                local_address=local_address,
                fresh=[True]*n_cache_lines,
                )
            if is_vpu:
                self.vpu_pages[physical_page_address] = info
            else:
                self.scalar_pages[physical_page_address] = info
            self.pages[logical_page_address] = info

    def release_memory(self, address: 'GlobalAddress', size: SizeBytes):
        assert size % self.params.page_bytes == 0
        for index in range(size//self.params.page_bytes):
            logical_page_address = address.addr + index * self.params.page_bytes
            info = self.pages.pop(logical_page_address)
            if info.is_vpu:
                self.vpu_free_pages.append(info.local_address.addr)
                self.vpu_pages.pop(info.local_address.addr)
            else:
                self.scalar_free_pages.append(info.local_address.addr)
                self.scalar_pages.pop(info.local_address.addr)

    def get_page_info(self, address: 'GlobalAddress') -> PageInfo:
        assert address.addr % self.params.page_bytes == 0
        if address.addr not in self.pages:
            raise ValueError(f'{hex(address.addr)} not in page table')
        return self.pages[address.addr]

    def get_page_info_from_vpu_addr(self, address: 'VPUAddress') -> PageInfo:
        assert address.addr % self.params.page_bytes == 0
        if address.addr not in self.vpu_pages:
            raise ValueError(f'{address} not in page table')
        return self.vpu_pages[address.addr]



class CacheLineState:

    def __init__(self):
        self.state = CacheState.I
        self.ident = None


class CacheState(Enum):
    I = 0  # Invalid
    S = 1  # Shared
    M = 2  # Modified


class CacheTable:

    def __init__(self, params: LamletParams):
        self.params = params
        self.n_slots = params.jamlet_sram_bytes * params.j_in_k // params.cache_line_bytes
        self.k_cache_line_bytes = params.cache_line_bytes
        self.l_cache_line_bytes = params.cache_line_bytes * params.k_in_l
        # For now assume that we're using all of the SRAM for global cache.
        self.slot_states = [CacheLineState() for index in range(self.n_slots)]
        self.free_slots = deque(list(range(self.n_slots)))
        self.used_slots = []

    def get_state(self, address: 'VPUAddress'):
        j_saddr = address.to_j_saddr(address, self.params, self)
        slot = j_saddr.addr//(self.params.cache_line_bytes//self.params.j_in_k)
        return self.slot_states[slot]

    def get_free_slot(self):
        if self.free_slots:
            return self.free_slots.popleft()
        else:
            return None

    def get_eviction_slot(self):
        assert self.used_slots
        return self.used_slots.pop(0)

    def touch_slot(self, slot):
        assert slot in self.used_slots
        # Move it to the end.
        # We want to keep the used slots in reverse last used order
        self.used_slots.remove(slot)
        self.used_slots.append(slot)

    def ident_to_cache_slot(self, ident):
        matching_slots = []
        for slot, slot_state in enumerate(self.slot_states):
            if slot_state.ident == ident:
                matching_slots.append(slot)
        assert len(matching_slots) <= 1
        if matching_slots:
            return matching_slots[0]
        else:
            return None

    def vpu_address_to_ident(self, vpu_address: 'VPUAddress'):
        ident = vpu_address.addr // self.l_cache_line_bytes
        return ident

    def vpu_address_to_cache_slot(self, vpu_address: 'VPUAddress'):
        ident = self.vpu_address_to_ident(vpu_address.addr)
        slot = self.ident_to_chache_line_slot(ident)
        return slot

    #def ident_to_slot_state(self, ident):
    #    slot = self.ident_to_cache_line_slot(ident)
    #    return self.slot_states[slot]

    #def cache_line_address_to_sram_address(self, cache_line_address):
    #    '''
    #    Takes a cache_line_address in the global (post tlb) address space.
    #    Returns a kamlet sram address.
    #    '''
    #    assert self.is_cached(cache_line_address)
    #    ident = self.address_to_ident(cache_line_address)
    #    slot = self.ident_to_cache_line_slot(ident)
    #    k_sram_address = slot * self.k_cache_line_bytes
    #    return k_sram_address

    def is_cached(self, address: 'VPUAddress'):
        slot = vpu_address_to_cache_slot(address)
        return slot is not None


@dataclass
class GlobalAddress:
    """
    An address in the overal address space
    """
    bit_addr: int

    @property
    def addr(self):
        return self.bit_addr//8

    def get_page(self, params: LamletParams):
        return GlobalAddress(bit_addr=(self.addr//params.page_bytes)*params.page_bytes*8)

    def is_vpu(self, params, tlb):
        page_address = self.get_page(params)
        page_info = tlb.get_page_info(page_address)
        return page_info.local_address.is_vpu

    def to_vpu_addr(self, params, tlb):
        page_address = self.get_page(params)
        page_info = tlb.get_page_info(page_address)
        assert page_info.local_address.is_vpu
        page_bit_offset = self.bit_addr*8 - page_address
        return VPUAddr(bit_addr=page_info.local_address.addr*8 + page_bit_offset,
                       ordering=page_info.local_address.ordering)

    def to_scalar_addr(self, params, tlb):
        page_address = self.get_page(params)
        page_info = tlb.get_page_info(page_address)
        assert not page_info.local_address.is_vpu
        page_bit_offset = self.bit_addr*8 - page_address.bit_addr
        assert page_bit_offset % 8 == 0
        return page_info.local_address.addr + page_bit_offset//8

    def to_logical_vline_addr(self, params, tlb):
        vpu_addr = self.to_vpu_addr(params, tlb)
        return vpu_addr.to_logical_vline_addr(params)

    def to_physical_vline_addr(self, params, tlb):
        logical_vline_addr = self.to_logical_vline_addr(params, tlb)
        return logical_vline_addr.to_physical_vline_addr(params)

    def to_k_maddr(self, params, tlb):
        physical_vline_addr = self.to_physical_vline_addr(params, tlb)
        return physical_vline_addr.to_k_maddr(params)

    def to_j_saddr(self, params, tlb, cache_table):
        k_maddr = self.to_k_maddr(params, tlb)
        return k_maddr.to_j_saddr(params, cache_table)


@dataclass
class LocalAddress:
    is_vpu: bool
    addr: int
    ordering: Ordering


@dataclass
class VPUAddress:
    """
    An address in the VPU address space (post TLB)
    """
    bit_addr: int
    ordering: Ordering

    @property
    def addr(self):
        return self.bit_addr//8

    def to_logical_vline_addr(self, params):
        vline_bytes = params.word_bytes * params.n_jamlets
        vline_index = self.addr//vline_bytes
        bit_addr_in_vline = self.bit_addr % (vline_bytes * 8)
        return LogicalVLineAddress(
            index=vline_index,
            bit_addr=bit_addr_in_vline,
            ordering=self.ordering
            )

    def to_global_addr(self, params, tlb):
        vpu_page_address = (self.bit_addr // params.page_bytes // 8) * params.page_bytes
        page_offset_bits = self.bit_addr - vpu_page_address * 8
        info = get_page_info_from_vpu_addr(vpu_page_address)
        return GlobalAddress(
            bit_addr = info.global_address*8 + page_offset_bits
            )


#def j_index_to_l_coords(params, jamlet_index):
#    # Assumes a grid ordering of jamlets.
#    # Hopefully this is the only place we need to change is we change the arrangement.
#    x = jamlet_index % (params.j_cols * params.k_cols)
#    y = jamlet_index // (params.j_cols * params.k_cols)
#    return (x, y)
#
#
#def j_index_to_k_indices(params, jamlet_index):
#    '''
#    Given the index of a jamlet (in a vector)
#    return the index of the kamlet, and the the location of the jamlet in the kamlet
#    '''
#    x, y = j_index_to_l_coords(params, jamlet_index)
#    k_x = x//params.j_cols
#    k_y = y//params.j_rows
#    k_index = k_y * params.k_cols + k_x
#    j_x = x % params.j_cols
#    j_y = y % params.j_rows
#    j_index_in_k = j_y * params.j_cols + j_x
#    return k_index, j_index_in_k


@dataclass
class LogicalVLineAddress:
    """
    A bit address in a vline of the global address space before reordering
    """
    # Which vline in the VPU memory this is.
    index: int
    # It's useful to pass this with the address so we don't have to use the TLB again
    ordering: Ordering
    # The bit address with the Vline.
    bit_addr: int

    @property
    def addr(self):
        return self.bit_addr//8

    def to_physical_vline_addr(self, params):
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
                (element_index % params.n_jamlets) * params.word_bytes*8 +
                (element_index // params.n_jamlets) * self.ordering.ew +
                bit_in_element
                )
        ## Reorder the jamlets from the logical order into the layout that they are
        ## connect to the kamlet memories.
        #vw_index = self.addr//self.word_bytes
        #k_index, j_in_k_index = self.ordering.vw_index_to_k_indices(params, vw_index)
        #physical_j_index = k_index * params.j_in_k + j_in_k_index
        #bit_address_in_jamlet = intermed_vline_bit_addr % (params.word_bytes*8)
        #physical_vline_bit_addr = (
        #        bit_address_in_jamlet +
        #        physical_j_index * params.word_bytes*8
        #        )
        return PhysicalVLineAddress(
            index=self.index,
            ordering=self.ordering,
            bit_addr=physical_vline_bit_addr)

    def to_vpu_address(self, params):
        vline_bits = params.n_jamlets * params.word_bytes * 8
        vpu_bit_addr = (
            self.index * vline_bits +
            self.bit_addr
            )
        return VPUAddress(
            ordering=self.ordering,
            bit_addr=vpu_bit_addr,
            )

    def to_global_addr(self, params: LamletParams, tlb: TLB):
        vpu_addr = self.to_vpu_addr(params)
        return vpu_addr.to_global_addr(params, tlb)




@dataclass
class PhysicalVLineAddress:
    """
    A bit address in a vline after rearranging elements order and jamlet order in a vline
    """
    # Which vline in the VPU memory this is.
    index: int
    # It's useful to pass this with the address so we don't have to use the TLB again
    # (I think it's just used for assertions)
    ordering: Ordering
    # The bit address with the Vline.
    bit_addr: int

    @property
    def addr(self):
        return self.bit_addr//8

    def to_k_maddr(self, params):
        vw_index = self.addr//self.word_bytes

        # This is the step that considers which vector word is mapped to which jamlet.
        # This mapping changes if we change the word order.
        k_index, j_in_k_index = self.ordering.vw_index_to_k_indices(params, vw_index)

        k_vline_bits = params.word_bytes * 8 * self.j_in_k
        k_memory_bit_address = (
            # Base address of this vline in the k memory.
            self.index * k_vline_bits +
            # Offset for this jamlet
            j_in_k_index * params.word_bytes * 8 +
            # Offset within that word
            self.bit_addr % (params.word_bytes * 8)
            )
        k_maddr = KMAddr(
            k_index=k_index,
            ordering=self.ordering,
            bit_addr=k_memory_bit_addr,
            )
        return k_maddr

    def to_logical_vline_addr(self, params):

        vw_index = self.bit_addr // (self.params.word_bytes * 8)
        assert self.params.word_bytes * 8 > self.ordering.ew
        assert (self.params.word_bytes * 8) % self.ordering.ew == 0
        elements_in_word = (self.params.word_bytes * 8)//self.ordering.ew
        element_in_word_index = (bit_addr // self.ordering.ew) % elements_in_word
        element_index = vw_index*elements_in_word + element_in_word_index
        logical_bit_addr = (
                element_index * self.ordering.ew +
                (self.bit_addr % self.ordering.ew)
            )
        return LogicalVLineAddress(
            index=self.index,
            ordering=self.ordering,
            bit_address=logical_bit_addr,
            )

    def to_global_addr(self, params: LamletParams, tlb: TLB):
        logical_vline_addr = self.to_logical_vline_addr(params)
        return logical_vline_addr.to_global_addr(params, tlb)


@dataclass
class KMAddr:
    """
    An address in a kamlet memory.
    """
    k_index: int 
    ordering: Ordering
    bit_addr: int

    @property
    def addr(self):
        return self.bit_addr//8

    def to_cache_slot(self, params, cache_table):
        cache_ident = self.addr % params.cache_line_bytes
        cache_slot = cache_table.ident_to_cache_line_slot(cache_ident)
        return cache_slot

    def to_j_saddr(self, params, cache_table):
        # We're assuming for know that cache_line is bigger or equal to vline
        # We put one word from the cache line in each jamlet.
        # Then repeat that until we've distributed the cache line.
        cache_slot = self.to_cache_slot(params, cache_table)
        j_in_k_index = (self.bit_addr // (params.word_bytes * 8)) % params.j_in_k
        cache_line_offset = self.bit_addr % (params.cache_line_bytes * 8)
        cache_line_bytes_per_jamlet = params.cache_line_bytes//params.j_in_k
        assert cache_line_bytes_per_jamlet % params.word_bytes == 0
        assert cache_line_bytes_per_jamlet >= params.word_bytes
        k_vline_bytes = params.word_bytes * params.j_in_k
        vline_index_in_cache_line = cache_line_offset // k_vline_bytes
        offset_in_word = self.bit_addr % (params.word_bytes * 8)
        address_in_sram = (
                # Base address of the cache line in the sram
                (cache_slot * cache_line_bytes_per_jamlet * 8) +
                vline_index_in_cache_line * params.word_bytes +
                offset_in_word
                )
        return JSAddr(
            k_index=self.k_index,
            j_in_k_index=j_in_k_index,
            ordering=self.ordering,
            bit_addr=self.address_in_sram,
            )

    def to_physical_vline_addr(self, params):
        k_vline_bits = params.n_jamlets * params.word_bytes * 8 // params.k_in_l
        index = self.bit_addr // k_vline_bits
        # We need to rearrange the words in a vline so that they match the order in a vector.
        j_in_k_index = (self.bit_addr // (params.word_bytes * 8)) % params.j_in_k
        vw_index = self.ordering.word_order.k_indices_to_vw_index(self.k_index, j_in_k_index)
        bit_addr_in_physical_vline = (
            vw_index * params.word_bytes * 8 +
            self.bit_addr % (params.word_bytes * 8)
            )
        return PhysicalVLineAddress(
            index=vline_index,
            bit_addr=bit_addr_in_physical_vline,
            ordering=self.ordering,
            )

    def to_global_addr(self, params: LamletParams, tlb: TLB):
        physical_vline_addr = self.to_physical_vline_addr(params)
        return physical_vline_addr.to_global_addr(params, tlb)


@dataclass
class JSAddr:
    """
    An adress in a jamlet SRAM.
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

    @property
    def addr(self):
        return self.bit_addr//8

    def to_k_maddr(self, params: LamletParams, tlb: TLB, cache_table: CacheTable):
        # First we need to check the cache state
        j_cache_line_bits = params.cache_line_bytes * 8 // params.j_in_k
        cache_slot = self.bit_addr//j_cache_line_bits
        slot_info = cache_table.cache_slots[cache_slot]

        k_cache_line_bits = params.cache_line_bytes * 8
        k_memory_bit_addr = (
            # Base address of the cache line in the k memory
            slot_info.ident * k_cache_line_bits +
            # Address of the j word
            self.j_in_k_index * params.word_bytes * 8 +
            self.bit_addr % (params.word_bytes * 8)
            )

        return KMAddr(
            k_index=self.k_index,
            ordering=self.ordering,
            bit_addr=k_memory_bit_addr,
            )


    def to_global_addr(self, params: LamletParams, tlb: TLB, cache_table: CacheTable):
        km_addr = self.to_k_maddr(params, tlb, cache_table)
        return km_addr.to_global_addr(params, tlb)


class AddressConverter:

    def __init__(self, params: LamletParams, tlb: TLB, cache_table: CacheTable):
        self.params = params
        self.tlb = tlb
        self.cache_table = cache_table

    def to_global_addr(self, addr):
        if isinstance(addr, JSAddress):
            return addr.to_global_addr(self.params, self.tlb, self.cache_table)
        else:
            raise NotImplemented()

    def to_scalar_addr(self, addr: GlobalAddress):
        return addr.to_scalar_addr(self.params, self.tlb)

    def to_vpu_addr(self, addr):
        if isinstance(addr, GlobalAddress):
            return addr.to_vpu_addr(self.params, self.tlb)
        else:
            raise NotImplemented()

    def to_k_maddr(self, addr):
        if isinstance(addr, GlobalAddress):
            return addr.to_k_maddr(self.params, self.tlb)
        else:
            raise NotImplemented()

    def to_j_saddr(self, addr):
        if isinstance(addr, GlobalAddress):
            return addr.to_j_saddr(self.params, self.tlb, self.cache_table)
        else:
            raise NotImplemented()

