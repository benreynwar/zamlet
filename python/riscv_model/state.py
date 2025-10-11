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

    def __init__(self, maxvl_words, word_width_bytes, scalar_memory_bytes, vpu_memory_bytes, sram_bytes, n_lanes, page_size, tohost_addr=0x80001000, fromhost_addr=0x80001040):
        self.maxvl_words = maxvl_words
        self.word_width_bytes = word_width_bytes
        self.scalar_memory_bytes = scalar_memory_bytes
        self.vpu_memory_bytes = vpu_memory_bytes
        self.sram_bytes = sram_bytes
        self.n_lanes = n_lanes
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
        #logger.debug(f'Writing to vpu address {address}')
        local_address = info.local_address + address - self.params.page_size*(address//self.params.page_size)
        self.memory[local_address] = b

    def get_memory(self, address, info):
        local_address = info.local_address + address - self.params.page_size*(address//self.params.page_size)
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


class VPUPhysicalState:

    def __init__(self, params: Params):
        self.params = params
        self.sram = bytearray([0]*params.sram_bytes)
        self.memory = bytearray([0]*params.sram_bytes)
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
        self.page_mapping = {}


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

    def __init__(self, params):
        self.params = params
        self.pc = None
        self.scalar = ScalarState(params)
        self.vpu_logical = VPULogicalState(params)
        self.vpu_physical = VPUPhysicalState(params)
        self.tlb = TLB(params)
        self.vl = 0
        self.vtype = 0
        self.exit_code = None

    def set_pc(self, pc):
        self.pc = pc

    def allocate_memory(self, address, size, is_vpu, element_width):
        self.tlb.allocate_memory(address, size, is_vpu, element_width)

    def set_memory(self, address, data):
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
                #logger.debug(f'Try to write address {address+index}={hex(address+index)}')
                self.set_vpu_memory(address+index, b, info)
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
                bs.append(self.get_vpu_memory(address+index, info))
            else:
                local_address = info.local_address + offset_in_page
                bs.append(self.scalar.get_memory(local_address))
        return bs

    def set_vpu_memory(self, address, b, info):
        self.vpu_logical.set_memory(address, b, info)
        #self.vpu_physical.set_memory(address, b, info)

    def get_vpu_memory(self, address, info):
        return self.vpu_logical.get_memory(address, info)

    def handle_tohost(self, tohost_value):
        """Handle HTIF syscall via tohost write."""
        # Check if this is an exit code (LSB = 1)
        if tohost_value & 1:
            self.exit_code = tohost_value >> 1
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


if __name__ == '__main__':
    params = Params(
            maxvl_words=16,
            word_width_bytes=8,
            vpu_memory_bytes=1<<20,
            scalar_memory_bytes=1<<20,
            sram_bytes=1<<16,
            n_lanes=4,
            page_size=1<<10,
            )
    logical_state = VPULogicalState(params)
    physical_state = VPUPhysicalState(params)
