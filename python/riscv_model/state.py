'''
Represents the state of the VPU.

1) A mapping of pages to the physical DRAM
   Each page has a (element width, n_lanes)

2) How each logical vector register is mapped to the SRAM.
    In has an (address, element_width, n_lanes)

3) The contents of the memory

4) The contents of the SRAM

We want to check that when we apply a vector instruction to the state the
result is the same as applying the micro-ops to the state.
'''

import enum
import logging
import sys
import struct

import decode


logger = logging.getLogger(__name__)


def element_width_valid(element_width):
    return element_width == 1 or (element_width >= 8 and is_power_of_two(element_width))

def element_width_valid_and_not_1(element_width):
    return (element_width >= 8 and is_power_of_two(element_width))

def is_power_of_two(value):
    return (value == 2) or ((value > 1) and (value % 2 == 0) and (is_power_of_two(value//2)))


def log2ceil(value):
    assert value >= 0
    n_bits = 0
    while value > 0:
        n_bits += 1
        value = value >> 1
    return n_bits


def extract_bit(byt, index):
    assert byt < 1 << 8
    assert 0 <= index < 8
    return (byt >> index) % 2


def replace_bit(byt, index, bit):
    assert byt < 1 << 8
    assert 0 <= index < 8
    mask = 1 << index
    assert bit in (0, 1)
    removed = byt & (~mask)
    updated = removed | (bit << index)
    return updated


def bytes_to_float(byts):
    assert len(byts) == 4
    float_val = struct.unpack('f', byts)[0]
    return float_val


def float_to_bytes(fl):
    byts = struct.pack('f', fl)
    assert len(byts) == 4
    return byts


class Params:

    def __init__(self, maxvl_words, word_width_bytes, scalar_memory_bytes, vpu_memory_bytes, sram_bytes, n_lanes, n_vpu_memories,
                 page_size, tohost_addr=0x80001000, fromhost_addr=0x80001040):
        self.maxvl_words = maxvl_words
        self.word_width_bytes = word_width_bytes
        self.scalar_memory_bytes = scalar_memory_bytes
        self.vpu_memory_bytes = vpu_memory_bytes
        self.sram_bytes = sram_bytes
        self.n_lanes = n_lanes
        self.n_vpu_memories = n_vpu_memories
        self.page_size = page_size
        assert page_size >= maxvl_words * word_width_bytes
        self.tohost_addr = tohost_addr
        self.fromhost_addr = fromhost_addr
        self.cache_line_size = maxvl_words * word_width_bytes


class ScalarState:

    def __init__(self, params: Params):
        self.params = params
        self.rf = [0 for i in range(32)]
        self.frf = [0 for i in range(32)]
        self.memory = {}
        self.csr = {}

    def read_reg(self, reg_num):
        """Read integer register, always returns 0 for x0."""
        if reg_num == 0:
            return 0
        value = self.rf[reg_num]
        return value & 0xffffffffffffffff

    def write_reg(self, reg_num, value):
        """Write integer register, masking to 64 bits. Writes to x0 are ignored."""
        if reg_num == 0:
            return
        value = value & 0xffffffffffffffff
        logger.debug(f'write_reg: x{reg_num} = 0x{value:016x} (signed: {value if value < 0x8000000000000000 else value - 0x10000000000000000})')
        self.rf[reg_num] = value

    def read_freg(self, reg_num):
        """Read floating-point register."""
        return self.frf[reg_num]

    def write_freg(self, reg_num, value):
        """Write floating-point register."""
        logger.debug(f'write_freg: f{reg_num} = 0x{value:016x}')
        self.frf[reg_num] = value

    def set_memory(self, address, b):
        self.memory[address] = b

    def get_memory(self, address):
        return self.memory[address]

    def read_csr(self, csr_addr):
        return self.csr.get(csr_addr, 0)

    def write_csr(self, csr_addr, value):
        self.csr[csr_addr] = value


class VPULogicalState:

    def __init__(self, params: Params):
        self.params = params
        self.vrf = [bytearray([0]*params.maxvl_words*params.word_width_bytes) for i in range(32)]
        self.memory = {}

    def set_memory(self, address, b, info):
        local_address = info.local_address + address - self.params.page_size*(address//self.params.page_size)
        #logger.debug(f'VPU write: logical={hex(address)} local={hex(local_address)} value={hex(b)}')
        self.memory[local_address] = b

    def get_memory(self, address, info):
        local_address = info.local_address + address - self.params.page_size*(address//self.params.page_size)
        #logger.debug(f'VPU read: logical={hex(address)} local={hex(local_address)}')
        if local_address not in self.memory:
            logger.error(f'VPU read from uninitialized memory: logical={hex(address)} local={hex(local_address)}')
            raise KeyError(f'Uninitialized VPU memory at logical address {hex(address)}, local address {hex(local_address)}')
        return self.memory[local_address]


class VRFMapping:

    def __init__(self, address, element_width, n_lanes):
        self.address = address
        self.element_width = element_width
        self.n_lanes = n_lanes


class CacheState(enum.Enum):
    M = 0 # Modified
    S = 1 # Shared
    I = 2 # Invalid


class SlotInfo:

    def __init__(self, address, element_width, cache_state):
        self.address = address
        self.element_width = element_width
        self.cache_state = cache_state


class PageMapping:

    def __init__(self, address, element_width):
        self.address = address
        self.element_width = element_width


class VPULaneState:

    def __init__(self, index, params: Params):
        self.index = index
        self.params = params
        self.sram = bytearray([0]*(params.sram_bytes//params.n_lanes))

    def get_sram_partial(self, bit_address, bit_width):
        assert bit_address % bit_width
        assert bit_width < 8
        byt = self.sram[bit_address//8]
        return (byt >> (bit_address % 8)) % (1 << bit_width)


class VPUMemoryState:

    def __init__(self, index, params: Params):
        self.index = index
        self.params = params
        self.memory = bytearray([0]*(params.vpu_memory_bytes//params.n_vpu_memories))

    def set_memory(self, address, b):
        self.memory[address] = b

    def get_memory(self, address):
        return self.memory[address]

    def set_memory_partial(self, bit_address, bit_width, value):
        assert bit_address % bit_width == 0
        assert bit_width < 8
        assert value < (1 << bit_width)
        old_value = self.memory[bit_address//8]
        mask = ((1 << bit_width)-1) << (bit_address % 8)
        new_value = (old_value & (~mask)) + (value << bit_address % 8)
        self.memory[bit_address//8] = new_value

    def get_memory_partial(self, bit_address, bit_width):
        byte_value = self.memory[bit_address//8]
        value = (byte_value >> (bit_address % 8)) % (1 << bit_width)
        return value


class InternalState:

    def __init__(self, params: Params):
        '''
        The raw state that doesn't know anything about registers or cache.

        It does know what element width is stored in different places.

        All addresses are given as local address in the invidivual sram or memory.

        '''
        self.n_lanes = params.n_lanes
        self.n_memories = params.n_vpu_memories
        self.word_width_bytes = params.word_width_bytes

        self.vector_size_bytes = params.maxvl_words * self.word_width_bytes

        self.vector_bytes_per_lane = self.vector_size_bytes//self.n_lanes
        self.page_bytes_per_memory = params.page_size//self.n_memories

        self.lanes = [VPULaneState(index, params) for index in range(params.n_lanes)]
        self.memories = [VPUMemoryState(index, params) for index in range(params.n_vpu_memories)]

        assert params.n_lanes % params.n_vpu_memories == 0
        self.lanes_per_memory = self.n_lanes//self.n_memories

        # Maps sram slots in sram to element width
        self.sram_ew = {}
        # Maps page slots in memory to element width
        self.memory_ew = {}

    def set_page_element_width(self, page_slot, element_width):
        self.memory_ew[page_slot] = element_width

    def _get_mask(self, mask_sram_slot, n_elements, mask_offset):
        assert mask_offset * self.n_lanes + n_elements < self.vector_size_bytes*8
        mask_sram_address = mask_sram_slot * self.vector_byte_per_lane
        assert self.sram_ew[mask_sram_slot] == 1
        mask = []
        for element_index in range(n_elements):
            mask_index = element_index + mask_offset * self.n_lanes
            lane_index = mask_index % self.n_lanes
            sram_bit_address = mask_sram_address*8 + (mask_index//self.n_lanes)
            byt = self.lanes[lane_index].sram[sram_bit_address//8]
            bit = byt >> (sram_bit_address % 8) % 2
            mask.append(bit)
        return mask

    def set_memory(self, memory_index, address_in_memory, b):
        self.memories[memory_index].memory[address_in_memory] = b

    def read_sram(self, sram_slot, element_index):
        element_width = self.sram_ew[sram_slot]
        assert element_width >= 8
        lane_index = element_index % self.n_lanes
        n_bytes = element_width//8
        offset_in_lane = element_index//self.n_lanes*element_width//8
        sram_address = sram_slot * self.vector_bytes_per_lane
        byts = self.lanes[lane_index].sram[sram_address+offset_in_lane: sram_address+offset_in_lane+n_bytes]
        return byts

    def copy_from_memory_to_sram_ew1(self, memory_address, sram_slot, n_elements):
        sram_address = sram_slot * self.vector_bytes_per_lane
        page_slot = memory_address//self.page_bytes_per_memory
        element_width = self.memory_ew[page_slot]
        assert element_width == 1
        max_n_elements = self.vector_size_bytes*8//element_width
        assert n_elements <= max_n_elements
        self.sram_ew[sram_slot] = element_width
        for element_index in range(n_elements):
            lane_index = element_index % self.n_lanes
            memory_index = lane_index//self.lanes_per_memory

            bit_offset_in_memory = lanes_per_memory*element_index//self.n_lanes + (element_index % lanes_per_memory)
            bit_offset_in_lane = element_index//self.n_lanes

            byt = self.memories[memory_index][memory_address+bit_offset_in_memory//8]
            bit = extract_bit(byt, bit_offset_in_memory % 8)
            sram_byte_address = sram_address + bit_offset_in_lane//8
            self.lanes[lane_index][sram_byte_address] = replace_bit(self.lanes[lane_index][sram_byte_address], bit_offset_in_lane % 8, bit)


    def copy_memory_to_sram(self, memory_address, sram_slot, n_elements=None, use_mask=False, mask_slot=None, reverse=False):
        page_slot = memory_address//self.page_bytes_per_memory
        sram_address = sram_slot * self.vector_bytes_per_lane
        if not reverse:
            element_width = self.memory_ew[page_slot]
        else:
            element_width = self.sram_ew[sram_slot]
        if n_elements is None:
            n_elements = self.vector_size_bytes*8//element_width
        assert element_width >= 8 and element_width <= self.word_width_bytes*8 and is_power_of_two(element_width)
        max_n_elements = self.vector_size_bytes*8//element_width
        assert n_elements <= max_n_elements
        if use_mask:
            mask = self._get_mask(mask_slot, n_elements)
        else:
            mask = [1] * n_elements
        if not reverse:
            self.sram_ew[sram_slot] = element_width
        else:
            assert self.memory_ew[page_slot] == element_width
        for element_index in range(max_n_elements):
            active = (element_index < len(mask)) and mask[element_index]
            if active:
                lane_index = element_index % self.n_lanes
                memory_index = lane_index//self.lanes_per_memory
                for byte_index in range(element_width//8):
                    offset_in_memory = self.lanes_per_memory*element_index//self.n_lanes*element_width//8 + (element_index % self.lanes_per_memory)*element_width//8 + byte_index
                    offset_in_lane = element_index//self.n_lanes*element_width//8 + byte_index
                    if not reverse:
                        byt = self.memories[memory_index].memory[memory_address+offset_in_memory]
                        self.lanes[lane_index].sram[sram_address+offset_in_lane] = byt
                    else:
                        byt = self.lanes[lane_index].sram[sram_address+offset_in_lane]
                        self.memories[memory_index].memory[memory_address+offset_in_memory] = byt

        
    def copy_sram_to_memory(self, memory_address, sram_slot, n_elements=None, use_mask=False, mask_slot=None):
        copy_memory_to_sram(memory_address, sram_address, n_elements, use_mask, mask_slot, reverse=True)

    def copy_sram_to_sram(self, from_slot, to_slot, n_elements=None, use_mask=False, mask_slot=None, mask_offset=0):
        def copy_value(a, b):
            return a
        self.lane_operation(dst_slot=to_slot, src1_slot=from_slot, src2_slot=None, func=copy_value, n_elements=n_elements,
                            use_make=use_make, mask_slot=mask_slot, mask_offset=mask_offset)
        #from_address = from_slot * self.vector_bytes_per_lane
        #to_address = to_slot * self.vector_bytes_per_lane
        #element_width = self.sram_ew[from_slot]
        #if n_elements is None:
        #    n_elements = self.vector_size_bytes*8//element_width
        #assert element_width >= 8 and element_width <= self.word_width_bytes*8 and is_power_of_two(element_width)
        #max_n_elements = self.vector_size_bytes*8//element_width
        #assert n_elements <= max_n_elements
        #if use_mask:
        #    mask = self._get_mask(mask_slot, n_elements, mask_offset)
        #else:
        #    mask = [1] * n_elements
        #self.sram_ew[to_slot] = element_width
        #for element_index in range(max_n_elements):
        #    active = (element_index < len(mask)) and mask[element_index]
        #    if active:
        #        lane_index = element_index % self.n_lanes
        #        for byte_index in range(element_width//8):
        #            offset_in_lane = element_index//self.n_lanes*element_width//8 + byte_index
        #            byt = self.lanes[lane_index].sram[from_address+offset_in_lane]
        #            self.lanes[lane_index].sram[to_address+offset_in_lane] = byt

    def lane_operation(self, dst_slot, src1_slot, src2_slot, func, n_elements=None, use_mask=False, mask_slot=None, mask_offset=0):
        src1_address = src1_slot * self.vector_bytes_per_lane
        src1_ew = self.sram_ew[src1_slot]
        assert element_width_valid_and_not_1(src1_ew)
        dst_address = dst_slot * self.vector_bytes_per_lane
        dst_ew = self.sram_ew[dst_slot]
        assert element_width_valid_and_not_1(dst_ew)
        max_ew = max(src1_ew, dst_ew)
        if src2_slot is not None:
            src2_address = src2_slot * self.vector_bytes_per_lane
            src2_ew = self.sram_ew[src2_slot]
            assert element_width_valid_and_not_1(src2_ew)
            max_ew = max(max_ew, src2_ew)

        if n_elements is None:
            if dst_ew == src1_ew and (src2_slot is None or src1_ew == src2_ew):
                # All the element widths match
                n_elements = self.vector_size_bytes*8//dst_ew
            else:
                raise Exception('Cannot determine n_elements if element widths do not match')

        max_n_elements = self.vector_size_bytes*8//max_ew
        assert n_elements <= max_n_elements
        if use_mask:
            mask = self._get_mask(mask_slot, n_elements, mask_offset)
        else:
            mask = [1] * n_elements
        for element_index in range(max_n_elements):
            active = (element_index < len(mask)) and mask[element_index]
            if active:
                lane_index = element_index % self.n_lanes
                offset1_in_lane = element_index//self.n_lanes*src1_ew//8
                element1 = self.lanes[lane_index].sram[src1_address+offset1_in_lane: src1_address+offset1_in_lane+src1_ew//8]
                dst_offset_in_lane = element_index//self.n_lanes*dst_ew//8
                if src2_slot is not None:
                    offset2_in_lane = element_index//self.n_lanes*src2_ew//8
                    element2 = self.lanes[lane_index].sram[src2_address+offset2_in_lane: src2_address+offset2_in_lane+src2_ew//8]
                    result = func(element1, element2)
                else:
                    result = func(element1)
                assert len(result) == dst_ew//8
                self.lanes[lane_index].sram[dst_address+dst_offset_in_lane: dst_address+dst_offset_in_lane+dst_ew//8] = result

    def set_sram_ew(self, slot, ew):
        self.sram_ew[slot] = ew
        


class VPUPhysicalState:

    def __init__(self, params: Params, tlb: 'TLB'):
        self.params = params
        self.tlb = tlb
        self.internal = InternalState(params)

        n_slots = params.sram_bytes//params.maxvl_words//params.word_width_bytes
        assert n_slots > 32

        # This tracks what we have in all the different vectors stored in the SRAM.
        # Each slot can be a cache line, a vector register, or both
        self.slot_infos = [SlotInfo(
            address=None,
            element_width=64,
            cache_state=CacheState.I,
            ) for index in range(n_slots)]

        # This maps an address in the memory space (must be aligned to cache line size)
        # to an sram slot.
        self.cache_line_to_slot = {}
        self.reg_to_slot = {index: index for index in range(32)}

        # We use this to choose which sram block to use next.
        self.unused_slots = [(32+index)
                                   for index in range(n_slots-32)]
        # This orders from least recently used to most recently used.
        self.cache_slots = []

    def slot_is_register(self, slot):
        return slot in self.reg_to_slot.values()

    def switch_register_slot(self, reg, new_slot):
        old_slot = self.reg_to_slot[reg]
        slot_info = self.slot_infos[old_slot]
        if slot_info.cache_state == CacheState.I:
            self.unused_slots.append(old_slot)
        self.reg_to_slot[reg] = new_slot
        new_slot_info = self.slot_infos[new_slot]

    def touch_cache_line(self, slot):
        '''
        This just moves a cache line to the end of the list so it won't 
        be evicted soon.
        '''
        self.cache_slots.remove(slot)
        self.cache_slots.append(slot)
        assert len(set(self.cache_slots)) == len(self.cache_slots)

    def update_cache_line(self, slot):
        '''
        This refeshes the contents of a cache-slot from the memory
        '''
        slot_info = self.slot_infos[slot]
        page_address = self.get_page(slot.address)
        page_info = self.get_page_info(page_address)
        
        assert slot_info.cache_state != CacheState.M

        # The element_width of the slot gets updated if it has changed.
        if slot_info.element_width != page_info.element_width:
            slot_info.element_width = page_info.element_width

        if slot_info.element_width == 1:
            self.internal.copy_memory_to_sram_ew1(slot.address//self.n_memories, slot)
        else:
            self.internal.copy_memory_to_sram(slot.address//self.n_memories, slot)

    def evict_cache_line(self, slot):
        slot_info = self.slot_infos[slot]
        if slot_info.cache_state == CacheState.M:
            # We need to copy this cache line to memory.
            page_address = (slot_info.address//self.page_size_bytes) * self.page_size_bytes
            page_info = self.get_page_info(page_address)
            assert page_info.element_width == slot_info.element_width
            if slot_info.element_width == 1:
                self.internal.copy_sram_to_memory_ew1(page_address//self.n_memories, slot)
            else:
                self.internal.copy_sram_to_memory(page_address//self.n_memories, slot)
        assert slot in self.cache_slots
        assert slot not in self.unused_slots
        self.cache_slots.remove(slot)
        self.unused_slots.append(slot)

    def get_free_slot(self):
        logger.info('get_free_slot: start')
        if not self.unused_slots:
            logger.info(f'get_free_slot: evicting cache slot {self.cache_slots[0]}')
            self.evict_cache_line(self.cache_slots[0])
        slot = self.unused_slots.pop(0)
        logger.info(f'get_free_slot: Using unused slot {slot}')
        self.slot_infos[slot].cache_state = CacheState.I
        self.slot_infos[slot].address = None
        self.slot_infos[slot].element_width = None
        return slot

    #def get_cache_info(self, address):
    #    assert address % self.params.cache_line_size == 0
    #    if address in self.cache_line_to_sram:
    #        sram_address = self.cache_line_to_sram[address]
    #        return self.sram_mapping[sram_address]
    #    return None

    def is_cached(self, cache_line_address):
        if cache_line_address in self.cache_line_to_slot:
            slot = self.cache_line_to_slot[cache_line_address]
            return self.slot_infos[slot].cache_state != CacheState.I
        return False

    def global_address_to_sram_address(self, address):
        page_address = self.get_page(address)
        page_offset = address - page_address
        info = self.tlb.get_page_info(page_address)
        assert info.element_width >= 8

        vpu_page_address = info.local_address
        vpu_address = info.local_address + page_offset
        cache_line_address = self.get_cache_line_address(vpu_address)
        cache_line_bytes = self.params.maxvl_words * self.params.word_width_bytes
        cache_line_offset = page_offset % cache_line_bytes

        vector_bytes_per_lane = cache_line_bytes // self.params.n_lanes

        element_index = cache_line_offset//(info.element_width//8)
        byte_index = cache_line_offset % (info.element_width//8)
        lane_index = element_index % self.params.n_lanes
        sram_offset = element_index//self.n_lanes + byte_index

        if not self.is_cached(cache_line_address):
            return (None, None)
        else:
            slot = self.cache_line_to_slot(cache_line_address)
            slot_base_sram = slot * vector_bytes_per_lane
            sram_address = slot_base_sram + sram_offset
            return (lane_index, sram_address)

    def get_cache_line_address(self, address):
        cache_line_bytes = self.params.maxvl_words * self.params.word_width_bytes
        return cache_line_bytes * (address // cache_line_bytes)

    def address_to_physical_address(self, address):
        '''
        We get a global address, and we convert it to first a vpu address and then
        an address in a specific memory
        '''

        page_address = self.get_page(address)
        info = self.tlb.get_page_info(page_address)

        assert info.element_width != 1
        ew_bytes = info.element_width // 8
        word_bytes = self.params.word_width_bytes
        ew_in_word = word_bytes // ew_bytes
        lanes_per_memory = self.params.n_lanes // self.params.n_vpu_memories

        offset = address % self.params.page_size
        element = offset // ew_bytes
        byte_in_element = offset % ew_bytes

        # Determine which lane this element belongs to
        lane = element % self.params.n_lanes
        element_in_lane = element // self.params.n_lanes

        # Determine which memory this lane's data goes to
        memory_index = lane // lanes_per_memory

        # Determine position of this lane's word within its memory
        # Each memory holds lanes_per_memory consecutive lane words
        word_index_in_memory = lane % lanes_per_memory
        word_in_lane = element_in_lane // ew_in_word
        element_in_word = element_in_lane % ew_in_word

        # Calculate offset within the page for this memory
        page_offset_in_memory = (word_in_lane * lanes_per_memory + word_index_in_memory) * word_bytes
        page_offset_in_memory += element_in_word * ew_bytes + byte_in_element

        # Convert local_address (in combined VPU space) to physical address in single memory
        # local_address is the base of this page in the combined VPU memory space
        # We need to map it to the physical memory
        page_base_in_memory = info.local_address // self.params.n_vpu_memories
        physical_address = page_base_in_memory + page_offset_in_memory

        sram_size_per_memory = self.params.sram_bytes // self.params.n_vpu_memories
        if physical_address >= sram_size_per_memory:
            raise ValueError(
                f'Physical address {hex(physical_address)} exceeds SRAM size '
                f'{hex(sram_size_per_memory)} for memory {memory_index}. '
                f'Logical address: {hex(address)}, page_base: {hex(page_base_in_memory)}, '
                f'page_offset: {hex(page_offset_in_memory)}'
            )

        return memory_index, physical_address

    def get_page(self, address):
        return self.params.page_size * (address//self.params.page_size)

    def get_page_info(self, page_address):
        return self.tlb.get_page_info(page_address)

    def get_cache_line(self, address):
        return self.params.cache_line_size * (address//self.params.cache_line_size)

    def set_memory(self, address, b):
        '''
        Set a single byte in memory
        '''
        page_address = self.get_page(address)
        page_info = self.tlb.get_page_info(page_address)
        assert page_info.is_vpu
        cache_line_address = self.get_cache_line(address)
        if self.is_cached(cache_line_address):
            self.evict_cache_line(cache_line_address)
        memory_index, address_in_memory = self.address_to_physical_address(address)
        self.internal.set_memory(memory_index, address_in_memory, b)

    def get_memory(self, address):
        '''
        Get a single byte from memory
        '''
        logger.warning('Getting a byte from the VPU memory')
        page_address = self.get_page(address)
        page_offset = address - page_address
        page_info = self.tlb.get_page_info(page_address)
        vpu_address = page_info.local_address + page_offset
        assert page_info.is_vpu
        global_cache_line_address = self.get_cache_line(address)
        vpu_cache_line_address = self.get_cache_line(vpu_address)
        if not self.is_cached(global_cache_line_address):
            self.read_cache_line(global_cache_line_address)
        cache_line_offset = address - global_cache_line_address
        element_index = cache_line_offset*8//page_info.element_width

        cache_slot = self.cache_line_to_slot[vpu_cache_line_address]
        byts = self.internal.read_sram(cache_slot, element_index)
        byt = byts[address % (page_info.element_width//8)]
        return byt

    #def get_elements(self, sram_address):
    #    sram_info = self.get_cache_info(sram_address)
    #    elements = []
    #    for element_index in range(8*self.params.sram_bytes//sram_info.element_width):
    #        lane_index = element_index % self.params.n_lanes
    #        bit_address_in_lane = (element_index//self.params.n_lanes) * sram_info.element_width
    #        if sram_info.element_width < 8:
    #            element_value = self.lanes[lane_index].get_sram_partial(bit_address_in_lane, sram_info.element_width)
    #        else:
    #            element_value = self.lanes[lane_index].get_sram(bit_address_in_lane//8, sram_info.element_width//8)
    #        elements.append(element_value)
    #    return elements

    #def get_mask(self, mask_reg, n_elements):
    #    if mask_reg is None:
    #        mask = [1 for i in range(n_elements)]
    #    else:
    #        sram_address = self.reg_to_sram(mask_reg)
    #        sram_info = self.get_cache_info(sram_address)
    #        assert sram_info.element_width == 1
    #        elements = self.get_elements(sram_address)
    #        mask = elements[:n_elements]
    #        assert all(e in (0, 1) for e in mask)
    #    return mask

    #def copy_element_sram_to_sram(self, from_cache_line_address, to_cache_line_address, element_index, element_width):
    #    raise NotImplemented()

    def load(self, vd, address, element_width, n_elements, use_mask=False):

        vector_size_bytes = self.params.maxvl_words * self.params.word_width_bytes
        elements_per_slot = vector_size_bytes * 8 // element_width
        assert address % vector_size_bytes == 0
        n_slots = (n_elements * element_width + vector_size_bytes*8-1)// (vector_size_bytes * 8)

        if n_slots > 1:
            slot_group_size = pow(2, log2ceil(n_slots))
            assert vd % slot_group_size == 0

        remaining_elements = n_elements
        mask_offset = 0
        for slot_index in range(n_slots):
            n_slot_elements = min(remaining_elements, elements_per_slot)
            remaining_elements -= n_slot_elements
            self.load_slot(vd+slot_index, address+slot_index*vector_size_bytes, element_width, n_slot_elements, use_mask=use_mask, mask_offset=mask_offset)
            mask_offset += n_slot_elements

    def VfMaccVf(self, vd, scalar_val, vs2, n_elements, use_mask):
        element_width = 32
        vector_size_bytes = self.params.maxvl_words * self.params.word_width_bytes
        elements_per_slot = vector_size_bytes * 8 // element_width
        n_slots = (n_elements * element_width + vector_size_bytes*8-1)// (vector_size_bytes * 8)

        if n_slots > 1:
            slot_group_size = pow(2, log2ceil(n_slots))
            assert vd % slot_group_size == 0

        remaining_elements = n_elements
        mask_offset = 0
        for slot_index in range(n_slots):
            n_slot_elements = min(remaining_elements, elements_per_slot)
            remaining_elements -= n_slot_elements
            self.VfMaccVf_slot(vd+slot_index, scalar_val, vs2+slot_index, n_slot_elements, use_mask=use_mask, mask_offset=mask_offset)
            mask_offset += n_slot_elements

    def read_cache_line(self, address, slot=None):
        '''
        address: Global address
        '''
        page_address = self.get_page(address)
        page_offset = address - page_address
        page_info = self.get_page_info(page_address)
        physical_address = page_info.local_address + page_offset

        if slot is None:
            slot = self.get_free_slot()
        if page_info.element_width == 1:
            self.internal.copy_memory_to_sram_ew1(physical_address//self.params.n_vpu_memories, slot)
        else:
            self.internal.copy_memory_to_sram(physical_address//self.params.n_vpu_memories, slot)
        assert not self.slot_is_register(slot)
        self.cache_line_to_slot[physical_address] = slot
        slot_info = self.slot_infos[slot]
        slot_info.address = address
        slot_info.cache_state = CacheState.S
        slot_info.element_width = page_info.element_width
        return slot

    def VfMaccVf_slot(self, vd, scalar_element, vs2, n_elements, use_mask, mask_offset):
        element_width = 32
        vector_size_bytes = self.params.maxvl_words * self.params.word_width_bytes
        assert n_elements * element_width <= vector_size_bytes * 8

        # Assign some fresh sram for the intermediate
        intermed_slot = self.get_free_slot()
        intermed_info = self.slot_infos[intermed_slot]
        intermed_info.element_width = element_width

        # Do the vector-scalar mult

        def mult_func(vector_element):
            scalar_float = bytes_to_float(scalar_element)
            vector_float = bytes_to_float(vector_element)
            result = scalar_float * vector_float
            return float_to_bytes(result)

        vd_slot = self.reg_to_slot[vd]
        vs2_slot = self.reg_to_slot[vs2]

        self.internal.set_sram_ew(intermed_slot, element_width)
        self.internal.lane_operation(
                dst_slot=intermed_slot, src1_slot=vs2_slot, src2_slot=None,
                func=mult_func, n_elements=n_elements, use_mask=use_mask, mask_offset=mask_offset)

        # Do the accumulation

        def add_func(e1, e2):
            f1 = bytes_to_float(e1)
            f2 = bytes_to_float(e2)
            result = f1 + f2
            return float_to_bytes(result)

        # Assign some fresh sram for the new vd
        new_vd_slot = self.get_free_slot()
        self.slot_infos[new_vd_slot].element_width = element_width
        self.reg_to_slot[vd] = new_vd_slot

        self.internal.set_sram_ew(new_vd_slot, element_width)
        self.internal.lane_operation(
                dst_slot=new_vd_slot, src1_slot=vd_slot, src2_slot=intermed_slot,
                func=add_func, n_elements=n_elements, use_mask=use_mask, mask_offset=mask_offset)


    def load_slot(self, vd, address, element_width, n_elements, use_mask=False, mask_offset=0):

        logger.info(f'Loading address {address} into vd={vd}')

        page_address = self.get_page(address)
        page_offset = address - page_address
        page_info = self.get_page_info(page_address)

        assert element_width == page_info.element_width

        vector_size_bytes = self.params.maxvl_words * self.params.word_width_bytes
        assert address % vector_size_bytes == 0
        assert n_elements * element_width <= vector_size_bytes * 8
        
        physical_address = page_info.local_address + page_offset

        # 1) Load the cache if it is not up-to-date.
        load_cache = True
        cache_slot = None
        if physical_address in self.cache_line_to_slot:
            cache_slot = self.cache_line_to_slot[physical_address]
            cache_info = self.slot_infos[cache_slot]
            if cache_info.cache_state == CacheState.I:
                if self.slot_is_register():
                    # Refresh the cache to elsewhere
                    cache_slot = None
            else:
                load_cache = False
        if load_cache:
            cache_slot = self.read_cache_line(address, cache_slot)

        # 2) If we are loading a full vector then just point the register
        # FIXME: We should also look at tail-agnostic stuff
        old_vd_slot = self.reg_to_slot[vd]
        max_n_elements = vector_size_bytes*8//element_width
        if (n_elements == max_n_elements) and not use_mask:
            self.reg_to_slot[vd] = cache_slot
            logger.info(f'Pointing vd={vd} at cache_slot={cache_slot}')
        else:
            logger.info(f'There is masking going on so doing other s tuff')
            if self.slot_infos[old_vd_slot].cache_state != CacheState.I:
                # 3) If the old vd register is also a cache line then lets
                #    make a new location for the register and copy the old
                #    values over.
                new_vd_slot = self.get_free_slot()
                self.reg_to_slot[vd] = new_vd_slot
                self.slot_infos[new_vd_slot].element_width = element_width
                self.internal.copy_sram_to_sram(old_vd_slot, new_vd_slot)
            else:
                new_vd_slot = old_vd_slot
            # 4) Copy values from the cache line
            if use_mask:
                mask_slot = self.reg_to_slot[0]
            else:
                mask_slot = None
            self.internal.copy_sram_to_sram(cache_slot, new_vd_slot, n_elements, use_mask, mask_slot, mask_offset//self.n_lanes)


def regions_overlap(start_a, size_a, start_b, size_b):
    return (
      ((start_a >= start_b) and (start_a <= start_b + size_b)) or
      ((start_a + size_a >= start_b) and (start_a + size_a <= start_b + size_b)) or
      ((start_b >= start_a) and (start_b <= start_a + size_a)) or
      ((start_b + size_b >= start_a) and (start_b + size_b <= start_a + size_a))
    )


class PageInfo:

    def __init__(self, address, is_vpu, local_address, element_width):
        # Logical address
        self.address = address
        self.is_vpu = is_vpu
        # Local address in the scalar or VPU memory
        self.local_address = local_address
        self.element_width = element_width

    def __str__(self):
        mem_type = "VPU" if self.is_vpu else "Scalar"
        ew = f"ew={self.element_width}" if self.element_width else "ew=None"
        return (f"PageInfo({mem_type}, logical={hex(self.address)}, "
                f"local={hex(self.local_address)}, {ew})")


class TLB:

    def __init__(self, params: Params):
        self.params = params
        self.pages = {}

        self.scalar_freed_pages = []
        self.scalar_lowest_never_used_page = 0

        self.vpu_freed_pages = []
        self.vpu_lowest_never_used_page = 0

    def get_lowest_free_page(self, is_vpu):
        if not is_vpu:
            if self.scalar_freed_pages:
                page = self.scalar_freed_pages.pop(0)
            else:
                page = self.scalar_lowest_never_used_page
                next_page = self.scalar_lowest_never_used_page + self.params.page_size
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
                next_page = self.vpu_lowest_never_used_page + self.params.page_size
                if next_page > self.params.vpu_memory_bytes:
                    raise MemoryError(
                        f'Out of VPU memory: requested page at {hex(page)}, '
                        f'but only {hex(self.params.vpu_memory_bytes)} bytes available'
                    )
                self.vpu_lowest_never_used_page = next_page
        return page

    def allocate_memory(self, address, size, is_vpu, element_width):
        assert size % self.params.page_size == 0
        for index in range(size//self.params.page_size):
            logical_page_address = address + index * self.params.page_size
            physical_page_address = self.get_lowest_free_page(is_vpu)
            assert logical_page_address not in self.pages
            self.pages[logical_page_address] = PageInfo(
                address=logical_page_address,
                is_vpu=is_vpu,
                local_address=physical_page_address,
                element_width=element_width
                )

    def release_memory(self, address, size):
        assert size % self.params.page_size == 0
        for index in range(size//self.params.page_size):
            logical_page_address = address + index * self.params.page_size
            info = self.pages.pop(logical_page_address)
            if info.is_vpu:
                self.vpu_free_pages.append(info.local_address)
            else:
                self.scalar_free_pages.append(info.local_address)

    def get_page_info(self, address):
        assert address % self.params.page_size == 0
        return self.pages[address]


class State:

    def __init__(self, params, use_physical=False):
        self.params = params
        self.pc = None
        self.scalar = ScalarState(params)
        self.tlb = TLB(params)
        if use_physical:
            self.vpu_physical = VPUPhysicalState(params, self.tlb)
        else:
            self.vpu_logical = VPULogicalState(params)
        self.vl = 0
        self.vtype = 0
        self.exit_code = None
        self.use_physical = use_physical

    def set_pc(self, pc):
        self.pc = pc

    def allocate_memory(self, address, size, is_vpu, element_width):
        page_bytes_per_memory = self.params.page_size // self.params.n_vpu_memories
        self.tlb.allocate_memory(address, size, is_vpu, element_width)
        if self.use_physical and is_vpu:
            for index in range(size//self.params.page_size):
                logical_page_address = address + index * self.params.page_size
                page_info = self.tlb.pages[logical_page_address]
                page_slot = page_info.local_address//page_bytes_per_memory
                self.vpu_physical.internal.memory_ew[page_slot] = element_width

    def set_memory(self, address, data, force_vpu=False):
        # Check for HTIF tohost write (8-byte aligned)
        if address == self.params.tohost_addr and len(data) == 8:
            tohost_value = int.from_bytes(data, byteorder='little')
            if tohost_value != 0:
                self.handle_tohost(tohost_value)

        for index, b in enumerate(data):
            page = (address+index)//self.params.page_size
            offset_in_page = address + index - page * self.params.page_size
            info = self.tlb.get_page_info(page * self.params.page_size)
            if info.is_vpu:
                if self.use_physical and not force_vpu:
                    raise Exception('Can not set_memory in vpu memory in physical mode')
                #logger.debug(f'Try to write address {address+index}={hex(address+index)}')
                self.set_vpu_memory(address+index, b, force=force_vpu)
            else:
                #logger.debug(f'Try to write address {address+index}={hex(address+index)}')
                local_address = info.local_address + offset_in_page
                self.scalar.set_memory(local_address, b)

    def get_memory(self, address, size):
        bs = bytearray([])
        for index in range(size):
            page = (address+index)//self.params.page_size
            offset_in_page = address + index - page * self.params.page_size
            info = self.tlb.get_page_info(page * self.params.page_size)
            #logger.debug(f'Try to get address {address+index}={hex(address+index)}')
            if info.is_vpu:
                bs.append(self.get_vpu_memory(address+index))
            else:
                local_address = info.local_address + offset_in_page
                bs.append(self.scalar.get_memory(local_address))
        return bs

    def set_vpu_memory(self, address, b, force=False):
        if self.use_physical and force:
            self.vpu_physical.set_memory(address, b)
        else:
            self.vpu_logical.set_memory(address, b)

    def get_vpu_memory(self, address):
        if self.use_physical:
            return self.vpu_physical.get_memory(address)
        else:
            return self.vpu_logical.get_memory(address)

    def handle_tohost(self, tohost_value):
        """Handle HTIF syscall via tohost write."""
        # Check if this is an exit code (LSB = 1)
        if tohost_value & 1:
            self.exit_code = tohost_value >> 1
            if self.exit_code == 1:
                logger.error(f'Program exit: VPU allocation error - invalid element width')
            elif self.exit_code == 2:
                logger.error(f'Program exit: VPU allocation error - out of memory')
            elif self.exit_code == 0:
                logger.info(f'Program exit: code={self.exit_code} (success)')
            else:
                logger.info(f'Program exit: code={self.exit_code}')
            return

        # Otherwise it's a pointer to magic_mem
        magic_mem_addr = tohost_value

        # Read magic_mem[0:4] = [syscall_num, arg0, arg1, arg2]
        syscall_num = int.from_bytes(self.get_memory(magic_mem_addr, 8), byteorder='little')
        arg0 = int.from_bytes(self.get_memory(magic_mem_addr + 8, 8), byteorder='little')
        arg1 = int.from_bytes(self.get_memory(magic_mem_addr + 16, 8), byteorder='little')
        arg2 = int.from_bytes(self.get_memory(magic_mem_addr + 24, 8), byteorder='little')

        logger.debug(f'HTIF syscall: num={syscall_num}, args=({arg0}, {arg1}, {arg2})')

        ret_value = 0
        if syscall_num == 64:  # SYS_write
            fd = arg0
            buf_addr = arg1
            length = arg2

            # Read the buffer
            buf = self.get_memory(buf_addr, length)
            msg = buf.decode('utf-8', errors='replace')

            if fd == 1:  # stdout
                logger.info(f'EMULATED STDOUT: {msg}')
                ret_value = length
            elif fd == 2:  # stderr
                logger.info(f'EMULATED STDERR: {msg}')
                ret_value = length
            else:
                logger.warning(f'Unsupported file descriptor: {fd}')
                ret_value = -1
        else:
            logger.warning(f'Unsupported syscall: {syscall_num}')
            ret_value = -1

        # Write return value to magic_mem[0]
        self.set_memory(magic_mem_addr, ret_value.to_bytes(8, byteorder='little', signed=True))

        # Signal completion by writing to fromhost
        self.set_memory(self.params.fromhost_addr, (1).to_bytes(8, byteorder='little'))

    def step(self, disasm_trace=None):
        instruction_bytes = self.get_memory(self.pc, 4)
        is_compressed = decode.is_compressed(instruction_bytes)

        if is_compressed:
            inst_hex = int.from_bytes(instruction_bytes[0:2], byteorder='little')
            num_bytes = 2
        else:
            inst_hex = int.from_bytes(instruction_bytes[0:4], byteorder='little')
            num_bytes = 4

        instruction = decode.decode(instruction_bytes)

        # Use disasm(pc) method if available, otherwise use str()
        if hasattr(instruction, 'disasm'):
            inst_str = instruction.disasm(self.pc)
        else:
            inst_str = str(instruction)

        logger.debug(f'pc={hex(self.pc)} bytes={hex(inst_hex)} instruction={inst_str}')

        if disasm_trace is not None:
            import disasm_trace as dt
            error = dt.check_instruction(disasm_trace, self.pc, inst_hex, inst_str)
            if error:
                logger.error(error)
                raise ValueError(error)

        if self.use_physical:
            if hasattr(instruction, 'update_state_physical'):
                instruction.update_state_physical(self)
            else:
                instruction.update_state(self)
