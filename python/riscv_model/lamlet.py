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
from collections import deque

import decode
from params import LamletParams, PageInfo, CacheLineState, Header, MessageType, Direction, CacheState, SendType
from kamlet import Kamlet
import kinstructions


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


class ScalarState:

    def __init__(self, params: LamletParams):
        self.params = params
        self.rf = [0 for i in range(32)]
        self.frf = [0 for i in range(32)]

        self.rf_updating = [False for i in range(32)]
        self.frf_updating = [False for i in range(32)]

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


class TLB:

    def __init__(self, params: LamletParams):
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
                logger.info(f'vpu memory bytes is {vpu_memory_bytes}={self.params.k_in_l}*{self.params.kamlet_memory_bytes}')
                if next_page > vpu_memory_bytes:
                    raise MemoryError(
                        f'Out of VPU memory: requested page at {hex(page)}, '
                        f'but only {hex(vpu_memory_bytes)} bytes available'
                    )
                self.vpu_lowest_never_used_page = next_page
        return page

    def allocate_memory(self, address, size, is_vpu, element_width):
        assert size % self.params.page_bytes == 0
        for index in range(size//self.params.page_bytes):
            logical_page_address = address + index * self.params.page_bytes
            physical_page_address = self.get_lowest_free_page(is_vpu)
            assert logical_page_address not in self.pages
            self.pages[logical_page_address] = PageInfo(
                global_address=logical_page_address,
                is_vpu=is_vpu,
                local_address=physical_page_address,
                element_width=element_width
                )

    def release_memory(self, address, size):
        assert size % self.params.page_bytes == 0
        for index in range(size//self.params.page_bytes):
            logical_page_address = address + index * self.params.page_bytes
            info = self.pages.pop(logical_page_address)
            if info.is_vpu:
                self.vpu_free_pages.append(info.local_address)
            else:
                self.scalar_free_pages.append(info.local_address)

    def get_page_info(self, address):
        assert address % self.params.page_bytes == 0
        if address not in self.pages:
            import pdb
            pdb.set_trace()
            raise ValueError(f'{address} not in page table')
        return self.pages[address]


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

    def ident_to_cache_line_slot(self, cache_line_ident):
        matching_slots = []
        for slot, slot_state in enumerate(self.slot_states):
            if slot_state.ident == cache_line_ident:
                matching_slots.append(slot)
        assert len(matching_slots) <= 1
        if matching_slots:
            return matching_slots[0]
        else:
            return None

    def address_to_ident(self, address):
        cache_line_ident = address // self.l_cache_line_bytes
        return cache_line_ident

    def ident_to_slot_state(self, ident):
        slot = self.ident_to_cache_line_slot(ident)
        return self.slot_states[slot]

    def cache_line_address_to_sram_address(self, cache_line_address):
        '''
        Takes a cache_line_address in the global (post tlb) address space.
        Returns a kamlet sram address.
        '''
        assert self.is_cached(cache_line_address)
        ident = self.address_to_ident(cache_line_address)
        slot = self.ident_to_cache_line_slot(ident)
        k_sram_address = slot * self.k_cache_line_bytes
        return k_sram_address

    def is_cached(self, address):
        '''
        address: An address in the VPU memory (post TLB)
        '''
        return ident_to_cache_line_slot(address) is not None



class Lamlet:

    def __init__(self, params: LamletParams, left_x, top_y):
        self.params = params
        self.pc = None
        self.scalar = ScalarState(params)
        self.tlb = TLB(params)
        self.vl = 0
        self.vtype = 0
        self.exit_code = None
        self.left_x = left_x
        self.top_y = top_y
        # Send instructions from left/top
        self.instr_x = self.left_x
        self.instr_y = self.top_y - 1
        self.kamlets = [Kamlet(
                    params,
                    left_x+params.j_cols*(kamlet_index%params.k_cols),
                    top_y+params.j_rows*(kamlet_index//params.k_cols),
                    ) for kamlet_index in range(params.k_in_l)]
        self.cache_table = CacheTable(params)
        # A dictionary that maps labels to futures
        # Used for handling responses back from the kamlet grid.
        self.waiting = {}

    def run(self):
        for kamlet in self.kamlets:
            spawn(kamlet.run())

    def set_pc(self, pc):
        self.pc = pc

    def get_kamlet(self, column, row):
        return self.kamlets[row*self.params.n_kamlet_columns+column]

    def get_jamlet(self, x, y):
        kamlet_column = x//self.params.n_kamlet_columns
        kamlet_row = y//self.params.n_kamlet_rows
        kamlet = self.get_kamlet(kamlet_columns, kamlet_row)
        jamlet = kamlet.get_jamlet(x % self.params.n_kamlet_columns, y % self.params.n_kamlet_rows)
        return jamlet

    def allocate_memory(self, address, size, is_vpu, element_width):
        page_bytes_per_memory = self.params.page_bytes // self.params.k_in_l
        self.tlb.allocate_memory(address, size, is_vpu, element_width)
        if is_vpu:
            for index in range(size//self.params.page_bytes):
                logical_page_address = address + index * self.params.page_bytes
                page_info = self.tlb.pages[logical_page_address]
                page_slot = page_info.local_address//page_bytes_per_memory

    def j_index_to_l_coords(self, jamlet_index):
        # Assumes a grid ordering of jamlets.
        # Hopefully this is the only place we need to change is we change the arrangement.
        x = jamlet_index % (self.params.j_cols * self.params.k_cols)
        y = jamlet_index // (self.params.j_cols * self.params.k_cols)
        return (x, y)

    def j_index_to_k_indices(self, jamlet_index):
        '''
        Given the index of a jamlet (in a vector)
        return the index of the kamlet, and the the location of the jamlet in the kamlet
        '''
        x, y = self.j_index_to_l_coords(jamlet_index)
        k_x = x//self.params.j_cols
        k_y = y//self.params.j_rows
        k_index = k_y * self.params.k_cols + k_x
        j_x = x % self.params.j_cols
        j_y = y % self.params.j_rows
        j_index_in_k = j_y * self.params.j_cols + j_x
        return k_index, j_index_in_k

    def get_page(self, address):
        return (address//self.params.page_bytes)*self.params.page_bytes

    def get_k_sram_address(self, address):
        page_address = self.get_page(address)
        page_info = self.tlb.get_page_info(page_address)
        assert page_info.is_vpu
        assert page_info.element_width >= 8
        assert page_info.element_width % 8 == 0
        page_offset = address - page_address
        local_address = page_info.local_address + page_offset
        element_index = (page_offset*8)//page_info.element_width
        j_index = element_index % self.params.j_in_l
        k_index, j_index_in_k = self.j_index_to_k_indices(j_index)

        element_bytes = page_info.element_width//8
        elements_in_a_word = self.params.word_bytes//element_bytes
        elements_in_a_line = self.params.j_in_l * elements_in_a_word

        j_sram_word_address = element_index//elements_in_a_line

        byte_in_word = (
                # Which element in that jamlet word
                ((element_index % elements_in_a_line)//self.params.j_in_l) * element_bytes +
                # Byte in element
                address % element_bytes
                )

        # Address in the combined lamlet sram
        l_sram_address = (
                # Local base address of the page
                local_address +
                # What 'line' in the page we are at.
                j_sram_word_address * self.params.j_in_l * self.params.word_bytes +
                # Which 'jamlet' we're in.
                j_index * self.params.word_bytes +
                byte_in_word
                )

        # Address in the kamlet sram
        k_sram_address = (
                # Local base address of the page
                local_address//self.params.k_in_l +
                # What 'line' in the page we are at
                j_sram_word_address * self.params.j_in_k * self.params.word_bytes +
                # Which 'jamlet' we're in
                j_index_in_k * self.params.word_bytes +
                byte_in_word
                )

        j_sram_address = (
                # Local base address of the page
                local_address//self.params.j_in_l +
                # What 'line' in the page we are at
                j_sram_word_address * self.params.word_bytes +
                byte_in_word
                )

        return k_index, k_sram_address


    def write_byte_instruction(self, address, value):
        k_index, k_sram_address = self.get_k_sram_address(address)
        kinstr = kinstructions.WriteImmByteToSRAM(
            k_sram_address=k_sram_address,
            imm=value,
            )
        return k_index, kinstr

    def read_byte_instruction(self, address, value):
        k_index, k_sram_address = self.get_k_sram_address(address)
        kinstr = kinstructions.ReadByteFromSRAM(
            k_sram_address=k_sram_address,
            imm=value,
            )
        return k_index, kinstr

    def send_write_byte_instruction(self, address, value):
        k_index, instruction = self.write_byte_instruction(address, value)
        self.send_instruction(instruction, k_index)

    async def read_byte(self, address):
        cache_line_address = self.get_cache_line_address(address)
        self.require_cache(self, cache_line_address)
        k_index, instruction = self.read_byte_instruction(address, value)
        self.send_instruction(instruction, k_index)
        value = await self.get_instruction_response(instruction, k_index)
        return value

    async def get_instruction_response(instruction, k_index=None):
        assert isinstance(instruction, ReadByteFromSRAM)
        assert k_index is not None
        future = Future()
        self.waiting[(READ_BYTE_FROM_SRAM_RESP, k_index, k_sram_address)] = future
        response = await future
        return result


    def get_header_source_k_index(self, header):
        x_offset = header.source_x - self.left_x
        y_offset = header.source_y - self.top_y
        k_x = x_offset // self.params.j_cols
        k_y = y_offset // self.params.j_rows
        k_index = k_y * self.params.k_cols  + k_x
        return k_index


    def process_packet(self, packet):
        header = packet[0]
        # Currently we only expect messages of type
        assert header.message_type == MessageType.READ_BYTE_FROM_SRAM_RESP
        k_index = self.get_header_source_k_index(header)
        assert len(packet) == 1
        label = (header.message_type, k_index, header.address)
        future = self.waiting[label]
        future.set_result(header.value)


    async def monitor_replys(self, clock):
        buffer = self.kamlets[0].router.output_buffers[Direction.N]
        header = None
        packet = []
        while True:
            if buffer:
                word = buffer.popleft()
                if header is None:
                    assert isinstance(word, Header)
                    header = word
                else:
                    assert not isinstance(word, Header)
                packet.append(word)
                header.length = header.length - 1
                if header.length == 0:
                    self.process_packet(packet)
                self.header = None
                self.packet = []
            await clock.next_cycle()

    def send_instruction(self, instruction, k_index=None):
        '''
        Send an instruction.
        If k_index=None then we broadcast to all the kamlets in this
        lamlet.
        '''
        if k_index is None:
            send_type = SendType.BROADCAST
            k_index = self.params.k_in_l-1
        else:
            send_type = SendType.SINGLE
        k_x = k_index//self.params.k_cols
        k_y = k_index % self.params.k_cols
        x = self.left_x + k_x * self.params.j_cols
        y = self.top_y + k_y * self.params.j_rows
        header = Header(
            target_x=x,
            target_y=y,
            source_x=self.instr_x,
            source_y=self.instr_y,
            length=2,
            message_type=MessageType.INSTRUCTIONS,
            send_type=SendType.BROADCAST,
            )
        packet = [header, instruction]
        jamlet = self.kamlets[0].jamlets[0]
        self.send_packet(packet, jamlet, Direction.N, port=0)

    def send_packet(self, packet, jamlet, direction, port):
        assert port == 0
        for word in packet:
            jamlet.router.input_buffers[direction].append(word)

    def set_memory(self, address, data, force_vpu=False):
        # Check for HTIF tohost write (8-byte aligned)
        if address == self.params.tohost_addr and len(data) == 8:
            tohost_value = int.from_bytes(data, byteorder='little')
            if tohost_value != 0:
                self.handle_tohost(tohost_value)

        for index, b in enumerate(data):
            page = (address+index)//self.params.page_bytes
            offset_in_page = address + index - page * self.params.page_bytes
            info = self.tlb.get_page_info(page * self.params.page_bytes)
            if info.is_vpu:
                if not force_vpu:
                    import pdb
                    pdb.set_trace()
                assert force_vpu
                self.send_write_byte_instruction(address, b)
            else:
                #logger.debug(f'Try to write address {address+index}={hex(address+index)}')
                local_address = info.local_address + offset_in_page
                self.scalar.set_memory(local_address, b)


    def get_scalar_memory(self, address, size):
        bs = bytearray([])
        for index in range(size):
            page = (address+index)//self.params.page_bytes
            offset_in_page = address + index - page * self.params.page_bytes
            info = self.tlb.get_page_info(page * self.params.page_bytes)
            assert not info.is_vpu
            local_address = info.local_address + offset_in_page
            read_byte = self.scalar.get_memory(local_address)
            bs.append(read_byte)
        return bs


    async def get_memory(self, address, size):
        results = []
        for index in range(size):
            page = (address+index)//self.params.page_bytes
            offset_in_page = address + index - page * self.params.page_bytes
            info = self.tlb.get_page_info(page * self.params.page_bytes)
            #logger.debug(f'Try to get address {address+index}={hex(address+index)}')
            read_task = None
            read_byte = None
            if info.is_vpu:
                read_task = self.read_byte(address, b)
            else:
                local_address = info.local_address + offset_in_page
                read_byte = self.scalar.get_memory(local_address)
            results.append((read_byte, read_task))
        bs = bytearray([])
        for byt, task in results:
            if byt is None:
                byt = await task
            bs.append(byt)
        return bs

    async def handle_tohost(self, tohost_value):
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
        syscall_num = int.from_bytes(await self.get_memory(magic_mem_addr, 8), byteorder='little')
        arg0 = int.from_bytes(await self.get_memory(magic_mem_addr + 8, 8), byteorder='little')
        arg1 = int.from_bytes(await self.get_memory(magic_mem_addr + 16, 8), byteorder='little')
        arg2 = int.from_bytes(await self.get_memory(magic_mem_addr + 24, 8), byteorder='little')

        logger.debug(f'HTIF syscall: num={syscall_num}, args=({arg0}, {arg1}, {arg2})')

        ret_value = 0
        if syscall_num == 64:  # SYS_write
            fd = arg0
            buf_addr = arg1
            length = arg2

            # Read the buffer
            buf = await self.get_memory(buf_addr, length)
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

    def is_cache_line_aligned(self, addr):
        cache_line_size = self.params.k_in_l * self.params.cache_line_bytes
        return addr % cache_line_size == 0

    def flush_cache_slot(self, slot):
        slot_state = self.cache_table.slot_states[slot]
        k_cache_line_address = slot_state.ident * self.params.cache_line_bytes
        k_sram_address = slot * self.params.cache_line_bytes
        kinstr = kinstructions.WriteLine(
            k_memory_address=k_cache_line_address,
            k_sram_address=k_sram_address,
            n_cache_lines=1,
            )
        self.send_instruction(kinstr)

    def evict_cache_slot(self, slot):
        slot_state = self.cache_table.line_slots[slot]
        if slot_state.state == CacheState.M:
            self.flush_cache_slot(slot)

    def assign_cache_slot(self, ident):
        slot = self.cache_table.get_free_slot()
        if slot is None:
            slot = self.cache_table.get_eviction_slot()
            self.evict_cache_slot(self, slot)
        slot_state = self.cache_table.slot_states[slot]
        slot_state.ident = ident
        slot_state.state = CacheState.I
        return slot

    def get_cache_line_address(self, address):
        l_cache_line_bytes = self.params.cache_line_bytes * self.params.k_in_l
        return (address//l_cache_line_bytes)*l_cache_line_bytes

    def require_cache(self, cache_line_address):
        if not self.is_cache_line_aligned(cache_line_address):
            import pdb
            pdb.set_trace()
        assert self.is_cache_line_aligned(cache_line_address)
        ident = self.cache_table.address_to_ident(cache_line_address)
        slot = self.cache_table.ident_to_cache_line_slot(ident)
        if slot is None:
            # We don't have a slot allocated for this.
            slot = self.assign_cache_slot(ident)
        slot_state = self.cache_table.ident_to_slot_state(ident)
        if slot_state.state == CacheState.I:
            # We need to read data into this line.
            k_sram_address = slot * self.params.cache_line_bytes
            kinstr = kinstructions.ReadLine(
                k_memory_address=cache_line_address,
                k_sram_address=k_sram_address,
                n_cache_lines=1,
                )
            self.send_instruction(kinstr)

    def get_cache_line_sram_address(self, cache_line_address):
        assert self.cache_table.is_cached(cache_line_address)
        cache_ident = self.cache

    def vload(self, vd, addr, element_width, n_elements, mask_reg):
        # Work out what page addr is one
        page = self.get_page(addr)
        page_info = self.tlb.get_page_info(page)
        page_offset = addr - page
        assert page_info.is_vpu

        # Require all the cache lines that page to this
        l_cache_line_bytes = self.params.cache_line_bytes * self.params.k_in_l
        for some_address in range(addr, addr+(element_width*n_elements+7)//8, l_cache_line_bytes):
            cache_line_address = (addr//l_cache_line_bytes) * l_cache_line_bytes
            self.require_cache(cache_line_address)

        assert page_info.element_width == element_width
        n_vlines = n_elements * (element_width//8) // (self.params.vline_bytes)
        assert n_elements % (self.params.vline_bytes // (element_width//8)) == 0

        local_address = addr - page
        assert local_address % self.params.vline_bytes == 0
        j_address_in_sram = local_address//self.params.vline_bytes

        kinstr = kinstructions.Load(
            dst=vd,
            j_sram_address=j_address_in_sram,
            n_vlines=n_vlines,
            )

        self.send_instruction(kinstr)

    async def step(self, disasm_trace=None):
        instruction_bytes = self.get_scalar_memory(self.pc, 4)
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

        if hasattr(instruction, 'update_state_lamlet'):
            await instruction.update_state_lamlet(self)
        else:
            instruction.update_state(self)
