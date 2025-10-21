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

import logging
from asyncio import Future

import decode
from addresses import CacheState, SizeBytes, SizeBits, TLB, CacheTable
from addresses import AddressConverter, Ordering, GlobalAddress, JSAddr
from params import LamletParams
from message import Header, MessageType, Direction, SendType
from kamlet import Kamlet
import kinstructions


logger = logging.getLogger(__name__)


#def element_width_valid(element_width):
#    return element_width == 1 or (element_width >= 8 and is_power_of_two(element_width))


#def element_width_valid_and_not_1(element_width):
#    return (element_width >= 8 and is_power_of_two(element_width))





#def extract_bit(byt, index):
#    assert byt < 1 << 8
#    assert 0 <= index < 8
#    return (byt >> index) % 2
#
#
#def replace_bit(byt, index, bit):
#    assert byt < 1 << 8
#    assert 0 <= index < 8
#    mask = 1 << index
#    assert bit in (0, 1)
#    removed = byt & (~mask)
#    updated = removed | (bit << index)
#    return updated




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
        signed = value if value < 0x8000000000000000 else value - 0x10000000000000000
        logger.debug(f'write_reg: x{reg_num} = 0x{value:016x} (signed: {signed})')
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
        self.reply_monitor = self.monitor_replys()
        self.finished = False

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

    def allocate_memory(self, address: GlobalAddress, size: SizeBytes, is_vpu: bool, ordering: Ordering):
        page_bytes_per_memory = self.params.page_bytes // self.params.k_in_l
        self.tlb.allocate_memory(address, size, is_vpu, ordering)

    def to_global_addr(self, addr):
        return self.conv.to_global_addr(addr)

    def to_scalar_addr(self, addr: GlobalAddress):
        return self.conv.to_scalar_addr(addr)

    def to_k_maddr(self, addr):
        return self.conv.to_k_maddr(addr)

    def to_j_saddr(self, addr):
        return self.conv.to_j_saddr(addr)

    def to_vpu_addr(self, addr):
        return self.conv.to_vpu_addr(addr)

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
            target_x=self.instr_x,
            target_y=self.instr_y,
            )
        return j_saddr.k_index, kinstr

    def send_write_byte_instruction(self, address: GlobalAddress, value: int):
        k_index, instruction = self.write_byte_instruction(address, value)
        self.send_instruction(instruction, k_index)
        vpu_address = self.to_vpu_addr(address)
        slot_state = self.cache_table.get_state(vpu_address)
        slot_state.state = CacheState.M

    async def read_byte(self, address: GlobalAddress):
        self.require_cache(address)
        k_index, instruction = self.read_byte_instruction(address)
        self.send_instruction(instruction, k_index)
        value = await self.get_instruction_response(instruction, k_index)
        return value

    def write_byte(self, address: GlobalAddress, value: int):
        self.require_cache(address)
        self.send_write_byte_instruction(address, value)

    async def get_instruction_response(self, instruction, k_index=None):
        assert isinstance(instruction, kinstructions.ReadByteFromSRAM)
        assert k_index is not None
        future = Future()
        tag = (MessageType.READ_BYTE_FROM_SRAM_RESP, k_index, instruction.j_saddr)
        self.waiting[tag] = future
        response = await self.clock.wait_future(future)
        return response

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
                            word = north_buffer.popleft()
                            north_jamlet.router.receive(Direction.S, word)
                            #logger.debug(f'Moving word north ({x}, {y}) -> ({x}, {y-1}) {word}')
                if y < self.top_y+n_rows-1:
                    # Send to the south
                    south_buffer = jamlet.router.output_buffers[Direction.S]
                    if south_buffer:
                        south_jamlet = self.get_jamlet(x, y+1)
                        if south_jamlet.router.has_input_room(Direction.N):
                            word = south_buffer.popleft()
                            south_jamlet.router.receive(Direction.N, word)
                            #logger.debug(f'Moving word south, ({x}, {y} -> ({x}, {y+1}) {word}')
                if x < self.left_x + n_cols-1:
                    # Send to the east
                    east_buffer = jamlet.router.output_buffers[Direction.E]
                    if east_buffer:
                        east_jamlet = self.get_jamlet(x+1, y)
                        if east_jamlet.router.has_input_room(Direction.W):
                            word = east_buffer.popleft()
                            east_jamlet.router.receive(Direction.W, word)
                            #logger.debug(f'Moving word east, ({x}, {y} -> ({x+1}, {y}) {word}')
                if x > self.left_x:
                    # Send to the west
                    west_buffer = jamlet.router.output_buffers[Direction.W]
                    if west_buffer:
                        west_jamlet = self.get_jamlet(x-1, y)
                        if west_jamlet.router.has_input_room(Direction.E):
                            word = west_buffer.popleft()
                            west_jamlet.router.receive(Direction.E, word)
                            #logger.debug(f'Moving word west, ({x}, {y} -> ({x-1}, {y}) {word}')


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
                header = None
                packet = []
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
            send_type=send_type,
            )
        packet = [header, instruction]
        jamlet = self.kamlets[0].jamlets[0]
        self.send_packet(packet, jamlet, Direction.N, port=0)

    def send_packet(self, packet, jamlet, direction, port):
        assert port == 0
        for word in packet:
            jamlet.router.input_buffers[direction].append(word)

    async def set_memory(self, address: int, data: bytes):
        global_addr = GlobalAddress(bit_addr=address*8)
        # Check for HTIF tohost write (8-byte aligned)
        if global_addr.addr == self.params.tohost_addr and len(data) == 8:
            tohost_value = int.from_bytes(data, byteorder='little')
            if tohost_value != 0:
                await self.handle_tohost(tohost_value)

        for index, b in enumerate(data):
            byt_address = GlobalAddress(bit_addr=global_addr.addr*8+index*8)
            # If this cache line is fresh then we need to set it to all 0.
            # If the cache line is not loaded then we need to load it.
            if byt_address.is_vpu(self.params, self.tlb):
                self.write_byte(byt_address, b)
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
            self.finished = True
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
        await self.set_memory(magic_mem_addr, ret_value.to_bytes(8, byteorder='little', signed=True))

        # Signal completion by writing to fromhost
        await self.set_memory(self.params.fromhost_addr, (1).to_bytes(8, byteorder='little'))

    def is_cache_line_aligned(self, address: GlobalAddress):
        cache_line_size = self.params.k_in_l * self.params.cache_line_bytes
        return address.bit_addr % (cache_line_size*8) == 0

    def j_saddr_is_aligned(self, j_saddr):
        j_cache_line_bits = self.params.cache_line_bytes * 8 // self.params.j_in_k
        return (j_saddr.k_index == 0 and
                j_saddr.j_in_k_index == 0 and
                j_saddr.bit_addr % j_cache_line_bits)

    def k_maddr_is_aligned(self, k_maddr):
        k_cache_line_bits = self.params.cache_line_bytes * 8
        return (k_maddr.k_index == 0 and
                k_maddr.bit_addr % k_cache_line_bits == 0)

    def flush_cache_address(self, address: GlobalAddress):
        k_maddr = self.to_k_maddr(address)
        j_saddr = self.to_j_saddr(address)
        assert self.j_saddr_is_aligned(j_saddr)
        assert k_maddr.k_index == 0
        kinstr = kinstructions.WriteLine(
            k_maddr=k_maddr,
            j_saddr=j_saddr,
            n_cache_lines=1,
            )
        self.send_instruction(kinstr)

    def evict_cache_address(self, address: GlobalAddress):
        vpu_address = self.to_vpu_addr(address)
        slot_state = self.cache_table.get_state(vpu_address)
        if slot_state.state == CacheState.M:
            self.flush_cache_address(address)

    def slot_to_address(self, slot: int):
        j_cache_line_bits = self.params.cache_line_bytes * 8 // self.params.j_in_k
        l_cache_line_bits = self.params.cache_line_bytes * 8 * self.params.k_in_l
        bit_addr_in_j_sram = slot * j_cache_line_bits
        vpu_address = slot * l_cache_line_bits
        page_info = self.tlb.vpu_pages[vpu_address]
        j_saddr = JSAddr(
            k_index=0,
            j_in_k_index=0,
            bit_addr=bit_addr_in_j_sram,
            ordering=page_info.ordering,
            )
        self.to_global_addr(j_saddr)

    def assign_cache_slot(self, address: GlobalAddress):
        k_maddr = self.to_k_maddr(address)
        # Check that it is aligned to a cache slot
        assert self.k_maddr_is_aligned(k_maddr)
        assert k_maddr.k_index == 0
        slot = self.cache_table.get_free_slot()
        if slot is None:
            slot = self.cache_table.get_eviction_slot()
            self.slot_to_address(slot)
            self.evict_cache_address(address)
        slot_state = self.cache_table.slot_states[slot]
        slot_state.ident = k_maddr.addr//self.params.cache_line_bytes
        slot_state.state = CacheState.I
        return slot

    def require_cache(self, address: GlobalAddress):
        is_fresh = self.tlb.get_is_fresh(address)
        if is_fresh:
            self.tlb.set_not_fresh(address)
        k_maddr = self.to_k_maddr(address)
        assert self.is_cache_line_aligned(address)
        vpu_address = self.to_vpu_addr(address)
        slot = self.cache_table.vpu_address_to_cache_slot(vpu_address)
        if is_fresh:
            # If it's fresh it shouldn't be cached.
            assert slot is None
        if slot is None:
            # We don't have a slot allocated for this.
            slot = self.assign_cache_slot(address)
        slot_state = self.cache_table.get_state(vpu_address)
        j_saddr = self.to_j_saddr(address)
        if slot_state.state == CacheState.I:
            if is_fresh:
                kinstr = kinstructions.ZeroLine(
                    j_saddr=j_saddr,
                    n_cache_lines=1,
                    )
                self.send_instruction(kinstr)
                slot_state.state = CacheState.M
            else:
                # We need to read data into this line.
                kinstr = kinstructions.ReadLine(
                    k_maddr=k_maddr,
                    j_saddr=j_saddr,
                    n_cache_lines=1,
                    )
                self.send_instruction(kinstr)
                slot_state.state = CacheState.S

    def vload(self, vd: int, addr: GlobalAddress, element_width: SizeBits,
              n_elements: int, mask_reg: int):
        # TODO: Support masking
        assert mask_reg is None
        # Require all the cache lines that page to this
        l_cache_line_bytes = self.params.cache_line_bytes * self.params.k_in_l
        last_addr = None
        last_page = None
        page_infos = []
        for some_address in range(addr.addr, addr.addr+(element_width*n_elements)//8):
            cache_line_address = (some_address//l_cache_line_bytes) * l_cache_line_bytes
            page_address = (some_address//self.params.page_bytes) * self.params.page_bytes
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
        j_saddr = self.to_j_saddr(addr)
        kinstr = kinstructions.Load(
            dst=vd,
            j_saddr=j_saddr,
            n_vlines=n_vlines,
            )

        self.send_instruction(kinstr)

    def step(self):
        for kamlet in self.kamlets:
            kamlet.step()
        next(self.reply_monitor)
        self.router_connections()

    async def run(self):
        while True:
            self.step()
            await self.clock.next_cycle()

    async def run_instructions(self, disasm_trace=None):
        while not self.finished:
            instruction_bytes = self.get_scalar_memory(GlobalAddress(bit_addr=self.pc*8), 4)
            is_compressed = decode.is_compressed(instruction_bytes)

            if is_compressed:
                inst_hex = int.from_bytes(instruction_bytes[0:2], byteorder='little')
            else:
                inst_hex = int.from_bytes(instruction_bytes[0:4], byteorder='little')

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

            if hasattr(instruction, 'update_lamlet'):
                await instruction.update_lamlet(self)
            else:
                instruction.update_state(self)

            await self.clock.next_cycle()
