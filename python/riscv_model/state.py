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

import decode


logger = logging.getLogger(__name__)



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
        self.tohost_addr = tohost_addr
        self.fromhost_addr = fromhost_addr


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

    def __init__(self, address, element_width_bits, n_lanes):
        self.address = address
        self.element_width_bits = element_width_bits
        self.n_lanes = n_lanes


class CacheState(enum.Enum):
    M = 0 # Modified
    O = 1 # Owned
    S = 2 # Shared
    I = 3 # Invalid
    R = 4 # Register (Not cache)


class SRAMMapping:

    def __init__(self, address, element_width_bits, n_lanes, cache_state, register_index):
        self.address = address
        self.element_width_bits = element_width_bits
        self.n_lanes = n_lanes
        self.cache_state = cache_state
        self.register_index = register_index


class PageMapping:

    def __init__(self, address, element_width_bits, n_lanes):
        self.address = address
        self.element_width_bits = element_width_bits
        self.n_lanes = n_lanes


class VPULaneState:

    def __init__(self, index, params: Params):
        self.index = index
        self.params = params
        self.sram = bytearray([0]*(params.sram_bytes//params.n_lanes))


class VPUMemoryState:

    def __init__(self, index, params: Params):
        self.index = index
        self.params = params
        self.memory = bytearray([0]*(params.vpu_memory_bytes//params.n_vpu_memories))

    def set_memory(self, address, b):
        self.memory[address] = b

    def get_memory(self, address):
        return self.memory[address]


class VPUPhysicalState:

    def __init__(self, params: Params):
        self.params = params
        self.lanes = [VPULaneState(index, params) for index in range(params.n_lanes)]
        self.memories = [VPUMemoryState(index, params) for index in range(params.n_vpu_memories)]
        self.vrf_mapping = [VRFMapping(
            address=index*params.maxvl_words*params.word_width_bytes,
            element_width_bits=64,
            n_lanes=params.n_lanes,
            ) for index in range(32)]
        n_sram_vectors = params.sram_bytes//params.maxvl_words//params.word_width_bytes
        assert n_sram_vectors > 32
        self.sram_mapping = [SRAMMapping(
            address=index*params.maxvl_words*params.word_width_bytes,
            element_width_bits=64,
            n_lanes=params.n_lanes,
            cache_state=CacheState.R if index < 32 else CacheState.I,
            register_index=index if index < 32 else None,
            ) for index in range(params.sram_bytes//params.page_size)]

    def address_to_physical_address(self, address, info):
        '''
        We get a global address, and we convert it to first a vpu address and then
        an address in a specific memory
        '''
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

        return memory_index, physical_address

    def set_memory(self, address, b, info):
        assert info.is_vpu
        memory_index, address_in_memory = self.address_to_physical_address(address, info)
        self.memories[memory_index].set_memory(address_in_memory, b)


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
                self.scalar_lowest_never_used_page += self.params.page_size
        else:
            if self.vpu_freed_pages:
                page = self.vpu_freed_pages.pop(0)
            else:
                page = self.vpu_lowest_never_used_page
                self.vpu_lowest_never_used_page += self.params.page_size
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
        if use_physical:
            self.vpu_physical = VPUPhysicalState(params)
        else:
            self.vpu_logical = VPULogicalState(params)
        self.tlb = TLB(params)
        self.vl = 0
        self.vtype = 0
        self.exit_code = None
        self.use_physical = use_physical

    def set_pc(self, pc):
        self.pc = pc

    def allocate_memory(self, address, size, is_vpu, element_width):
        self.tlb.allocate_memory(address, size, is_vpu, element_width)

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
                self.set_vpu_memory(address+index, b, info, force=force_vpu)
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
                if self.use_physical:
                    raise Exception('Can not get_memory in vpu memory in physical mode')
                bs.append(self.get_vpu_memory(address+index, info))
            else:
                local_address = info.local_address + offset_in_page
                bs.append(self.scalar.get_memory(local_address))
        return bs

    def set_vpu_memory(self, address, b, info, force=False):
        if self.use_physical and force:
            self.vpu_physical.set_memory(address, b, info)
        else:
            self.vpu_logical.set_memory(address, b, info)

    def get_vpu_memory(self, address, info):
        return self.vpu_logical.get_memory(address, info)

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

        instruction.update_state(self)
