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
from asyncio import Future

import decode
from addresses import PageInfo, CacheLineState, CacheState, SizeBytes, SizeBits, TLB, CacheTable
from addresses import AddressConverter
from params import LamletParams, Header, MessageType, Direction, SendType
from kamlet import Kamlet
import kinstructions
from addresses import GlobalAddress


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

    def set_memory(self, address: int, b):
        self.memory[address] = b

    def get_memory(self, address: int):
        return self.memory[address]

    def read_csr(self, csr_addr):
        return self.csr.get(csr_addr, 0)

    def write_csr(self, csr_addr, value):
        self.csr[csr_addr] = value




class Lamlet:

    def __init__(self, clock, params: LamletParams, left_x, top_y):
        self.clock = clock
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
        self.conv = AddressConverter(self.params, self.tlb, self.cache_table)

    def set_pc(self, pc):
        self.pc = pc

    def get_kamlet(self, x, y):
        kamlet_column = (x - self.left_x)//self.params.k_cols
        kamlet_row = (y - self.top_y)//self.params.k_rows
        return self.kamlets[kamlet_row*self.params.k_cols+kamlet_column]

    def get_jamlet(self, x, y):
        kamlet = self.get_kamlet(x, y)
        jamlet = kamlet.get_jamlet(x, y)
        return jamlet

    def allocate_memory(self, address: GlobalAddress, size: SizeBytes, is_vpu: bool, element_width: SizeBits):
        page_bytes_per_memory = self.params.page_bytes // self.params.k_in_l
        self.tlb.allocate_memory(address, size, is_vpu, element_width)
        if is_vpu:
            for index in range(size//self.params.page_bytes):
                logical_page_address = address.addr + index * self.params.page_bytes
                page_info = self.tlb.pages[logical_page_address]
                page_slot = page_info.local_address.addr//page_bytes_per_memory

    #def get_k_sram_address(self, address):
    #    page_address = self.get_page(address)
    #    page_info = self.tlb.get_page_info(page_address)
    #    assert page_info.is_vpu
    #    assert page_info.element_width >= 8
    #    assert page_info.element_width % 8 == 0
    #    page_offset = address - page_address
    #    vpu_address = page_info.local_address + page_offset

    #    cache_ident = self.cache_table.address_to_ident(vpu_address)
    #    cache_slot = self.cache_table.ident_to_cache_line_slot(cache_ident)

    #    element_index = (page_offset*8)//page_info.element_width
    #    j_index = element_index % self.params.j_in_l
    #    k_index, j_index_in_k = self.j_index_to_k_indices(j_index)

    #    elements_in_a_word = self.params.word_bytes//element_bytes
    #    vline_words = self.params.j_in_l * elements_in_a_word



    #    element_bytes = page_info.element_width//8
    #    elements_in_a_line = self.params.j_in_l * elements_in_a_word

    #    j_memory_word_address = element_index//elements_in_a_line


    #    l_cache_line_address = cache_slot * self.params.cache_line_bytes * self.params.k_in_l


    #    byte_in_word = (
    #            # Which element in that jamlet word
    #            ((element_index % elements_in_a_line)//self.params.j_in_l) * element_bytes +
    #            # Byte in element
    #            address % element_bytes
    #            )

    #    # Address in the combined lamlet sram
    #    l_sram_address = (
    #            # Local base address of the page
    #            local_address +
    #            # What 'line' in the page we are at.
    #            j_sram_word_address * self.params.j_in_l * self.params.word_bytes +
    #            # Which 'jamlet' we're in.
    #            j_index * self.params.word_bytes +
    #            byte_in_word
    #            )

    #    # Address in the kamlet sram
    #    k_sram_address = (
    #            # Local base address of the page
    #            local_address//self.params.k_in_l +
    #            # What 'line' in the page we are at
    #            j_sram_word_address * self.params.j_in_k * self.params.word_bytes +
    #            # Which 'jamlet' we're in
    #            j_index_in_k * self.params.word_bytes +
    #            byte_in_word
    #            )

    #    j_sram_address = (
    #            # Local base address of the page
    #            local_address//self.params.j_in_l +
    #            # What 'line' in the page we are at
    #            j_sram_word_address * self.params.word_bytes +
    #            byte_in_word
    #            )
    #    assert k_sram_address < self.params.j_in_k * self.params.jamlet_sram_bytes

    #    return k_index, k_sram_address

    def to_global_addr(self, addr):
        return self.conv.to_global_addr(addr)

    def to_scalar_addr(self, addr: GlobalAddress):
        return self.conv.to_scalar_addr(addr)

    def to_k_maddr(self, addr):
        return self.conv.to_k_maddr(addr)

    def to_j_saddr(self, addr):
        return self.conv.to_j_saddr(addr)

    def write_byte_instruction(self, address: GlobalAddress, value: int):
        j_saddr = self.to_j_saddr(address)
        kinstr = kinstructions.WriteImmByteToSRAM(
            j_saddr=j_saddr,
            imm=value,
            )
        return j_saddr.k_index, kinstr

    def read_byte_instruction(self, address: GlobalAddress):
        j_saddr = address.to_j_saddr(self.params, self.tlb, self.cache_table)
        kinstr = kinstructions.ReadByteFromSRAM(
            j_saddr=j_saddr,
            )
        return j_saddr.k_index, kinstr

    def send_write_byte_instruction(self, address, value):
        k_index, instruction = self.write_byte_instruction(address, value)
        self.send_instruction(instruction, k_index)

    async def read_byte(self, address):
        cache_line_address = self.get_cache_line_address(address)
        self.require_cache(cache_line_address)
        k_index, instruction = self.read_byte_instruction(address)
        self.send_instruction(instruction, k_index)
        value = await self.get_instruction_response(instruction, k_index)
        return value

    async def get_instruction_response(self, instruction, k_index=None):
        assert isinstance(instruction, kinstructions.ReadByteFromSRAM)
        assert k_index is not None
        future = Future()
        self.waiting[(MessageType.READ_BYTE_FROM_SRAM_RESP, k_index, instruction.k_sram_address)] = future
        response = await self.clock.wait_future(future)
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

    def router_connections(self):
        '''
        Move words between router buffers
        '''
        n_cols = self.params.j_cols * self.params.k_cols
        n_rows = self.params.j_rows * self.params.k_rows
        for x in range(self.left_x, self.left_x + n_cols):
            for y in range(self.top_y, self.top_y + n_rows):
                jamlet = self.get_jamlet(x, y)
                if y > self.top_y:
                    # Send to the north
                    north_buffer = jamlet.router.output_buffers[Direction.N]
                    if north_buffer:
                        north_jamlet = self.get_jamlet(x, y-1)
                        if north_jamlet.router.has_input_room(Direction.S):
                            north_jamlet.router.receive(Direction.S, north_buffer.popleft())
                            logger.debug('Moving word north')
                if y < self.top_y+n_rows-1:
                    # Send to the south
                    south_buffer = jamlet.router.output_buffers[Direction.S]
                    if south_buffer:
                        south_jamlet = self.get_jamlet(x, y+1)
                        if south_jamlet.router.has_input_room(Direction.N):
                            south_jamlet.router.receive(Direction.N, south_buffer.popleft())
                            logger.debug('Moving word south')
                if x < self.left_x + n_cols-1:
                    # Send to the east
                    east_buffer = jamlet.router.output_buffers[Direction.E]
                    if east_buffer:
                        east_jamlet = self.get_jamlet(x+1, y)
                        if east_jamlet.router.has_input_room(Direction.W):
                            east_jamlet.router.receive(Direction.W, east_buffer.popleft())
                            logger.debug('Moving word east')
                if x > self.left_x:
                    # Send to the west
                    west_buffer = jamlet.router.output_buffers[Direction.W]
                    if west_buffer:
                        west_jamlet = self.get_jamlet(x-1, y)
                        if west_jamlet.router.has_input_room(Direction.E):
                            west_jamlet.router.receive(Direction.E, west_buffer.popleft())
                            logger.debug('Moving word west')


    def monitor_replys(self):
        buffer = self.kamlets[0].jamlets[0].router.output_buffers[Direction.N]
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
            yield

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

    def set_memory(self, address: int, data):
        global_addr = GlobalAddress(bit_addr=address*8)
        # Check for HTIF tohost write (8-byte aligned)
        if global_addr.addr == self.params.tohost_addr and len(data) == 8:
            tohost_value = int.from_bytes(data, byteorder='little')
            if tohost_value != 0:
                self.handle_tohost(tohost_value)

        for index, b in enumerate(data):
            byt_address = GlobalAddress(bit_addr=global_addr.addr*8+index*8)
            if byt_address.is_vpu(self.params, self.tlb):
                self.send_write_byte_instruction(byt_address, b)
            else:
                scalar_address = self.to_scalar_addr(byt_address)
                self.scalar.set_memory(scalar_address, b)

    def get_scalar_memory(self, address: GlobalAddress, size: SizeBytes):
        bs = bytearray([])
        for index in range(size):
            local_address = self.to_scalar_addr(GlobalAddress(bit_addr=address.bit_addr+index*8))
            read_byte = self.scalar.get_memory(local_address)
            bs.append(read_byte)
        return bs


    async def get_memory(self, address: int, size):
        results = []
        for index in range(size):
            byte_addr = GlobalAddress(bit_addr=(address+index)*8)
            is_vpu = byte_addr.is_vpu(self.params, self.tlb)
            read_task = None
            read_byte = None
            if is_vpu:
                read_task = self.read_byte(byte_addr)
            else:
                local_address = byte_addr.to_scalar_addr(self.params, self.tlb)
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

    def is_cache_line_aligned(self, addr: GlobalAddress):
        cache_line_size = self.params.k_in_l * self.params.cache_line_bytes
        return addr % cache_line_size == 0

    def j_saddr_is_aligned(self, j_saddr):
        j_cache_line_bits == params.cache_line_bytes * 8 // params.j_in_k
        return (j_saddr.k_index == 0 and
                j_saddr.j_in_k_index == 0 and
                j_saddr.bit_addr % j_cache_line_bits)

    def flush_cache_address(self, address: GlobalAddress):
        k_maddr = address.to_k_maddr(params, self.tlb)
        j_saddr = address.to_j_saddr(params, self.tlb, self.cache_table)
        assert check_j_saddr_is_aligned(self, j_saddr)
        assert k_maddr.k_index == 0
        kinstr = kinstructions.WriteLine(
            k_maddr=k_maddr,
            k_saddr=k_saddr,
            n_cache_lines=1,
            )
        self.send_instruction(kinstr)

    def evict_cache_address(self, address: GlobalAddress):
        slot_state = self.cache_table.get_state(address)
        if slot_state.state == CacheState.M:
            self.flush_cache_slot(address)

    def slot_to_address(self, slot: int):
        j_cache_line_bits = self.params.cache_line_bytes * 8 // self.params.j_in_k
        bit_addr_in_j_sram = slot * j_cache_line_bits
        j_saddr = JSAddr(
            k_index=0,
            j_in_k_index=0,
            bit_addr=bit_addr_in_j_sram,
            )
        self.to_global_addr(j_saddr)

    def assign_cache_slot(self, address: GlobalAddress):
        k_maddr = address.to_k_maddr(params, self.tlb)
        j_saddr = address.to_j_saddr(params, self.tlb, self.cache_table)
        # Check that it is aligned to a cache slot
        assert check_j_saddr_is_aligned(self, j_saddr)
        assert k_maddr.k_index == 0
        slot = self.cache_table.get_free_slot()
        if slot is None:
            slot = self.cache_table.get_eviction_slot()
            self.slot_to_address(slot)
            self.evict_cache_slot(address)
        slot_state = self.cache_table.slot_states[slot]
        slot_state.ident = ident
        slot_state.state = CacheState.I
        return slot

#    def get_cache_line_address(self, address: GlobalAddress):
#        l_cache_line_bytes = self.params.cache_line_bytes * self.params.k_in_l
#        return (address//l_cache_line_bytes)*l_cache_line_bytes
#
    def require_cache(self, address: GlobalAddress):
        assert self.is_cache_line_aligned(address)
        vpu_address = address.to_vpu_address(params, self.tlb)
        slot = self.cache_table.vpu_address_to_cache_slot(vpu_address)
        if slot is None:
            # We don't have a slot allocated for this.
            slot = self.assign_cache_slot(address)
        slot_state = self.cache_table.get_state(vpu_address)
        if slot_state.state == CacheState.I:
            # We need to read data into this line.
            k_sram_address = slot * self.params.cache_line_bytes
            kinstr = kinstructions.ReadLine(
                k_memory_address=cache_line_address,
                k_sram_address=k_sram_address,
                n_cache_lines=1,
                )
            self.send_instruction(kinstr)

#    def get_cache_line_sram_address(self, cache_line_address):
#        assert self.cache_table.is_cached(cache_line_address)
#        cache_ident = self.cache
#
    def vload(self, vd: int, addr: GlobalAddress, element_width: SizeBits, n_elements: int, mask_reg: int):
        # Require all the cache lines that page to this
        l_cache_line_bytes = self.params.cache_line_bytes * self.params.k_in_l
        last_addr = None
        last_page = None
        page_infos = []
        for some_address in range(addr.addr, addr.addr+(element_width*n_elements)//8):
            cache_line_address = (addr.addr//l_cache_line_bytes) * l_cache_line_bytes
            page_address = (addr.addr//self.params.page_bytes) * self.params_page_bytes
            if cache_line_address != last_addr:
                global_addr = GlobalAddress(bit_addr=cache_line_address*8)
                self.require_cache(global_addr)
                last_addr = cache_line_address
            if page_address != last_page:
                page_info = self.tlb.get_page_info(page_address)
                assert page_info.element_width == element_width
                assert page_info.is_vpu
                page_infos.append(page_info)

        # TODO: Support load that spans pages. Split into multiple kinstructions.
        assert len(page_infos) == 1

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

    def step(self):
        for kamlet in self.kamlets:
            kamlet.step()
        self.monitor_replys()
        self.router_connections()

    async def run(self):
        while True:
            self.step()
            await self.clock.next_cycle()
    
    async def run_instructions(self, disasm_trace=None):
        while True:
            instruction_bytes = self.get_scalar_memory(GlobalAddress(bit_addr=self.pc*8), 4)
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

            await self.clock.next_cycle()
