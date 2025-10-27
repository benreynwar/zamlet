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

import decode
from addresses import CacheState, SizeBytes, SizeBits, TLB, CacheTable
from addresses import AddressConverter, Ordering, GlobalAddress, JSAddr, KMAddr, VPUAddress
from params import LamletParams
from message import Header, MessageType, Direction, SendType
from kamlet import Kamlet
import memlet
from memlet import Memlet
from utils import combine_futures, bytes_to_float
from runner import Clock, Future
import kinstructions
import utils


logger = logging.getLogger(__name__)


class RegisterFileSlot:

    def __init__(self, clock, params, name):
        self.clock = clock
        self.params = params
        self.name = name
        self.value = bytes([0]*8)
        self.next_value = None
        self.has_next_value = False
        # This is a future that when it is resolved will
        # update the contents of the register file.
        self.future = None
        self.next_future = None
        self.has_next_future = None

    def updating(self):
        return self.future is not None

    def get_value(self):
        assert not self.updating()
        as_int = int.from_bytes(self.value, byteorder='little', signed=True)
        logger.debug(f'read_reg: {self.name} = 0x{as_int:016x}')
        return self.value

    def set_value(self, value):
        assert not self.has_next_value
        self.has_next_value = True
        assert isinstance(value, bytes)
        assert len(value) == 8
        self.next_value = value
        assert not self.has_next_future
        self.has_next_future = False
        self.next_future = None
        as_int = int.from_bytes(value, byteorder='little', signed=True)
        logger.debug(f'write_reg: {self.name} = 0x{as_int:016x}')

    def set_future(self, future):
        assert not self.has_next_future
        self.has_next_future = True
        self.next_future = future

    async def apply_future(self, future):
        await future
        value = future.result()
        int_value = int.from_bytes(value, byteorder='little', signed=False)
        if self.future == future:
            assert not self.has_next_value
            self.has_next_value = True
            if not self.has_next_future:
                self.has_next_future = True
                self.next_future = None
            assert isinstance(value, bytes)
            assert len(value) == self.params.word_bytes
            self.next_value = value
            logger.debug(f'write_reg: {self.name} = 0x{int_value:016x}')
        else:
            logger.debug(f'write_reg: {self.name} = 0x{int_value:016x} wont apply overwritten')

    def update(self):
        if self.has_next_value:
            self.value = self.next_value
        if self.has_next_future:
            self.future = self.next_future
            if self.future is not None:
                assert isinstance(self.future, Future)
                self.clock.create_task(self.apply_future(self.future))
        self.has_next_value = False
        self.has_next_future = False


class ScalarState:

    def __init__(self, clock: Clock, params: LamletParams):
        self.clock = clock
        self.params = params
        self._rf = [RegisterFileSlot(clock, params, f'x{i}') for i in range(32)]
        self._frf = [RegisterFileSlot(clock, params, f'f{i}') for i in range(32)]

        self.memory = {}
        self.csr = {}

    def regs_ready(self, regs, fregs):
        return all(not self._rf[r].updating() for r in regs) and all(not self._frf[fr].updating() for fr in fregs)

    async def wait_all_regs_ready(self, regs, fregs):
        while not self.regs_ready(regs, fregs):
            await self.clock.next_cycle

    def read_reg(self, reg_num):
        if reg_num == 0:
            return bytes([0]*8)
        return self._rf[reg_num].get_value()

    def read_freg(self, freg_num):
        return self._frf[freg_num].get_value()

    def write_reg(self, reg_num, value: bytes):
        assert isinstance(value, bytes)
        assert len(value) == 8
        self._rf[reg_num].set_value(value)

    def write_freg(self, freg_num, value: bytes):
        assert isinstance(value, bytes)
        assert len(value) == 8
        self._frf[freg_num].set_value(value)

    def write_reg_future(self, reg_num, future):
        self._rf[reg_num].set_future(future)

    def write_freg_future(self, freg_num, future):
        self._frf[freg_num].set_future(future)

    def set_memory(self, address: int, b):
        self.memory[address] = b

    async def get_memory(self, address: int, size: int=1):
        """
        Returns a future that will resolve with the memory value.
        (currently resolves immediately)
        """
        if address not in self.memory:
            raise Exception(f'Address {hex(address)} is not initialized')
        future = self.clock.create_future()
        bs = []
        for index in range(size):
            bs.append(self.memory[address+index])
        future.set_result(bytes(bs))
        return future

    def read_csr(self, csr_addr):
        """Read CSR, returns bytes of length word_bytes."""
        if csr_addr not in self.csr:
            return bytes(self.params.word_bytes)
        return self.csr[csr_addr]

    def write_csr(self, csr_addr, value):
        """Write CSR, value should be bytes."""
        assert isinstance(value, bytes), f"CSR value must be bytes, got {type(value)}"
        self.csr[csr_addr] = value

    def update(self):
        for cb in self._rf:
            cb.update()
        for cb in self._frf:
            cb.update()


class Lamlet:

    def __init__(self, clock, params: LamletParams, left_x=0, top_y=0):
        self.clock = clock
        self.params = params
        self.pc = None
        self.scalar = ScalarState(clock, params)
        self.tlb = TLB(params)
        self.vrf_ordering = [Ordering(None, None) for _ in range(params.n_vregs)]
        self.vl = 0
        self.vtype = 0
        self.exit_code = None
        self.left_x = left_x
        self.top_y = top_y
        # Send instructions from left/top
        self.instr_x = self.left_x
        self.instr_y = self.top_y - 1

        self.instruction_buffer = utils.Queue(params.instruction_buffer_length)

        # Need this for how we arrange memlets
        assert self.params.k_cols % 2 == 0

        self.kamlets = []
        self.memlets = []
        for kamlet_index in range(params.k_in_l):
            kamlet_x = params.j_cols*(kamlet_index%params.k_cols)
            kamlet_y = params.j_rows*(kamlet_index//params.k_cols)
            kamlet = Kamlet(
                clock=clock,
                params=params,
                min_x=kamlet_x,
                min_y=kamlet_y,
                )
            self.kamlets.append(kamlet)
            # The memlet is connected to several routers.
            mem_coords = []
            if kamlet_x < self.params.k_cols//2:
                mem_x = -1
            else:
                mem_x = self.params.k_cols * self.params.j_cols
            for j_in_k_row in range(self.params.j_rows):
                mem_coords.append((mem_x, kamlet_y + j_in_k_row))
            self.memlets.append(Memlet(
                clock=clock,
                params=params,
                coords=mem_coords
                ))
        self.cache_table = CacheTable(params)
        # A dictionary that maps labels to futures
        # Used for handling responses back from the kamlet grid.
        self.waiting = {}
        self.conv = AddressConverter(self.params, self.tlb, self.cache_table)
        self.finished = False

    async def _remove_wait_label(self, label, future):
        await future
        del self.waiting[label]

    def create_wait_future(self, label):
        assert label not in self.waiting
        future = self.clock.create_future()
        self.waiting[label] = future
        self.clock.create_task(self._remove_wait_label(label, future))
        return future

    def exists_wait_future(self, label):
        return label in self.waiting

    def get_wait_future(self, label):
        future = self.waiting[label]
        return future

    def set_pc(self, pc):
        self.pc = pc

    def get_kamlet(self, x, y):
        kamlet_column = (x - self.left_x)//self.params.j_cols
        kamlet_row = (y - self.top_y)//self.params.j_rows
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

    def read_bytes_instruction(self, address: GlobalAddress, size: int):
        j_saddr = address.to_j_saddr(self.params, self.tlb, self.cache_table)
        kinstr = kinstructions.ReadBytesFromSRAM(
            j_saddr=j_saddr,
            size=size,
            target_x=self.instr_x,
            target_y=self.instr_y,
            )
        return j_saddr.k_index, kinstr

    async def send_write_byte_instruction(self, address: GlobalAddress, value: int):
        k_index, instruction = self.write_byte_instruction(address, value)
        await self.add_to_instruction_buffer(instruction, k_index)
        vpu_address = self.to_vpu_addr(address)
        slot_state = self.cache_table.get_state(vpu_address)
        slot_state.state = CacheState.M

    async def read_bytes_resolve(self, future, instruction, k_index):
        value = await self.get_instruction_response(instruction, k_index)
        future.set_result(value)

    async def read_bytes(self, address: GlobalAddress, size=1):
        """
        This blocks until the cache is ready an the instruction is received.
        It returns a future that resolves when the value is returned.
        """
        logger.debug(f'Lamlet.read_bytes {hex(address.addr)}')
        # It must all be on one cache line
        end_address = address.offset_bytes(size-1)
        cache_line_address = self.get_cache_line_address(address)
        final_cache_line_address = self.get_cache_line_address(end_address)
        assert cache_line_address == final_cache_line_address
        await self.require_cache(cache_line_address)
        k_index, instruction = self.read_bytes_instruction(address, size)
        await self.add_to_instruction_buffer(instruction, k_index)
        assert k_index == instruction.j_saddr.k_index
        future = self.clock.create_future()
        self.clock.create_task(self.read_bytes_resolve(future, instruction, k_index))
        return future

    def get_cache_line_address(self, address: GlobalAddress):
        l_cache_line_bits = self.params.cache_line_bytes * self.params.k_in_l * 8
        cache_line_address = GlobalAddress(
            bit_addr=(address.bit_addr//l_cache_line_bits)*l_cache_line_bits,
            )
        return cache_line_address

    async def write_byte(self, address: GlobalAddress, value: int):
        cache_line_address = self.get_cache_line_address(address)
        await self.require_cache(cache_line_address)
        await self.send_write_byte_instruction(address, value)

    async def get_instruction_response(self, instruction, k_index=None):
        assert isinstance(instruction, kinstructions.ReadBytesFromSRAM)
        assert k_index is not None
        assert k_index == instruction.j_saddr.k_index
        future = self.clock.create_future()
        tag = (MessageType.READ_BYTES_FROM_SRAM_RESP, k_index, instruction.j_saddr)
        future = self.create_wait_future(tag)
        await future
        response = future.result()
        return response

    def get_header_source_k_index(self, header):
        x_offset = header.source_x - self.left_x
        y_offset = header.source_y - self.top_y
        k_x = x_offset // self.params.j_cols
        k_y = y_offset // self.params.j_rows
        k_index = k_y * self.params.k_cols  + k_x
        logger.debug(f'({x_offset},{y_offset}) -> k_index {k_index}')
        return k_index

    def process_packet(self, packet):
        header = packet[0]
        assert header.length == len(packet)
        # Currently we only expect messages of type
        if header.message_type == MessageType.READ_BYTES_FROM_SRAM_RESP:
            # A jamlet is replying with the content of an sram read.
            assert header.value is not None
            k_index = self.get_header_source_k_index(header)
            assert len(packet) == 1
            label = (header.message_type, k_index, header.address)
            future = self.get_wait_future(label)
            future.set_result(header.value)
        elif header.message_type == MessageType.WRITE_LINE_NOTIFY:
            k_index, _ = memlet.memlet_coords_to_index(self.params, header.source_x, header.source_y)
            vpu_address = packet[1] * self.params.k_in_l
            write_line_label = self.waiting_write_line_label(vpu_address, k_index)
            future = self.get_wait_future(write_line_label)
            k_index, _ = memlet.memlet_coords_to_index(self.params, header.source_x, header.source_y)
            future.set_result(None)
        elif header.message_type == MessageType.READ_LINE_NOTIFY:
            j_index = header.source_y * self.params.j_cols * self.params.k_cols + header.source_x
            vpu_address = packet[1] * self.params.k_in_l
            read_line_label = self.waiting_read_line_label(vpu_address, j_index)
            future = self.get_wait_future(read_line_label)
            future.set_result(None)
        else:
            raise NotImplementedError

    async def router_connections(self):
        '''
        Move words between router buffers
        '''
        # We should have a grid of routers from (-1, 0) to (n_cols, n_rows-1)
        routers = {}
        n_rows = self.params.j_rows * self.params.k_rows
        n_cols = self.params.j_cols * self.params.k_cols
        for memlet in self.memlets:
            for r in memlet.routers:
                coords = (r.x, r.y)
                assert coords not in routers
                routers[coords] = r
        for kamlet in self.kamlets:
            for jamlet in kamlet.jamlets:
                r = jamlet.router
                coords = (r.x, r.y)
                assert coords not in routers
                routers[coords] = r
        for x in range(-1, n_cols+1):
            for y in range(0, n_rows):
                assert (x, y) in routers

        # Now start the logic to move the messages between the routers
        while True:
            await self.clock.next_cycle
            n_cols = self.params.j_cols * self.params.k_cols
            n_rows = self.params.j_rows * self.params.k_rows
            for x in range(-1, n_cols+1):
                for y in range(0, n_rows):
                    router = routers[(x, y)]
                    for conn in router._input_connections.values():
                        if conn.age > 50:
                            import pdb
                            pdb.set_trace()
                    north = (x, y-1)
                    south = (x, y+1)
                    east = (x+1, y)
                    west = (x-1, y)
                    if north in routers:
                        # Send to the north
                        north_buffer = router._output_buffers[Direction.N]
                        if north_buffer:
                            north_router = routers[north]
                            if north_router.has_input_room(Direction.S):
                                word = north_buffer.popleft()
                                north_router.receive(Direction.S, word)
                                logger.debug(f'{self.clock.cycle}: Moving word north ({x}, {y}) -> ({x}, {y-1}) {word}')
                    if south in routers:
                        # Send to the south
                        south_buffer = router._output_buffers[Direction.S]
                        if south_buffer:
                            south_router = routers[south]
                            if south_router.has_input_room(Direction.N):
                                word = south_buffer.popleft()
                                south_router.receive(Direction.N, word)
                                logger.debug(f'{self.clock.cycle}: Moving word south, ({x}, {y}) -> ({x}, {y+1}) {word}')
                    if east in routers:
                        # Send to the east
                        east_buffer = router._output_buffers[Direction.E]
                        if east_buffer:
                            east_router = routers[east]
                            if east_router.has_input_room(Direction.W):
                                word = east_buffer.popleft()
                                east_router.receive(Direction.W, word)
                                logger.debug(f'{self.clock.cycle}: Moving word east, ({x}, {y}) -> ({x+1}, {y}) {word}')
                    if west in routers:
                        # Send to the west
                        west_buffer = router._output_buffers[Direction.W]
                        if west_buffer:
                            west_router = routers[west]
                            if west_router.has_input_room(Direction.E):
                                word = west_buffer.popleft()
                                west_router.receive(Direction.E, word)
                                logger.debug(f'{self.clock.cycle}: Moving word west, ({x}, {y}) -> ({x-1}, {y}) {word}')

    async def monitor_replys(self):
        buffer = self.kamlets[0].jamlets[0].router._output_buffers[Direction.N]
        header = None
        packet = []
        while True:
            await self.clock.next_cycle
            if buffer:
                word = buffer.popleft()
                if header is None:
                    assert isinstance(word, Header)
                    header = word.copy()
                else:
                    assert not isinstance(word, Header)
                packet.append(word)
                header.length = header.length - 1
                if header.length == 0:
                    self.process_packet(packet)
                    header = None
                    packet = []

    async def add_to_instruction_buffer(self, instruction, k_index=None):
        logger.debug(f'{self.clock.cycle}: Adding {instruction} to buffer')
        while not self.instruction_buffer.can_append():
            await self.clock.next_cycle
        self.instruction_buffer.append((instruction, k_index))

    async def monitor_instruction_buffer(self):
        inactive_count = 0
        old_length = 0
        while True:
            logger.debug(f'{self.clock.cycle}: {len(self.instruction_buffer)} instrs in the buffer')
            if self.instruction_buffer:
                k_indices = [x[1] for x in self.instruction_buffer.queue]
                k_indices_same = all(k_indices[0] == x for x in k_indices)
                if len(self.instruction_buffer) >= self.params.instructions_in_packet or (not k_indices_same) or inactive_count > 2:
                    instructions = []
                    while self.instruction_buffer:
                        if self.instruction_buffer.head()[1] == k_indices[0]:
                            instructions.append(self.instruction_buffer.queue.popleft()[0])
                        else:
                            break
                    assert instructions
                    await self.send_instructions(instructions, k_indices[0])
                    old_length = 0
                    inactive_count = 0
                else:
                    new_length = len(self.instruction_buffer)
                    if new_length == old_length:
                        inactive_count += 1
                    else:
                        inactive_count = 0
                    old_length = new_length
            await self.clock.next_cycle

    async def send_instructions(self, instructions, k_index=None):
        '''
        Send instructions.
        If k_index=None then we broadcast to all the kamlets in this
        lamlet.
        '''
        logger.debug(f'{self.clock.cycle}: Sending instructions {instructions}')
        if k_index is None:
            send_type = SendType.BROADCAST
            k_index = self.params.k_in_l-1
        else:
            send_type = SendType.SINGLE
        k_x = k_index % self.params.k_cols
        k_y = k_index // self.params.k_cols
        x = self.left_x + k_x * self.params.j_cols
        y = self.top_y + k_y * self.params.j_rows
        header = Header(
            target_x=x,
            target_y=y,
            source_x=self.instr_x,
            source_y=self.instr_y,
            length=1+len(instructions),
            message_type=MessageType.INSTRUCTIONS,
            send_type=send_type,
            )
        packet = [header] + instructions
        jamlet = self.kamlets[0].jamlets[0]
        logger.debug(f'Sending instructions to {k_index}, -> ({x}, {y})')
        await self.send_packet(packet, jamlet, Direction.N, port=0)

    async def send_packet(self, packet, jamlet, direction, port):
        queue = jamlet.router._input_buffers[direction]
        assert port == 0
        while packet:
            await self.clock.next_cycle
            if len(queue) < queue.length:
                queue.append(packet.pop(0))

    async def set_memory(self, address: int, data: bytes):
        logger.debug(f'Writing to memory from {hex(address)} to {hex(address+len(data)-1)}')
        global_addr = GlobalAddress(bit_addr=address*8)
        # Check for HTIF tohost write (8-byte aligned)
        if global_addr.addr == self.params.tohost_addr and len(data) == 8:
            logger.debug(f'It is a HTIF addres. finished is {self.finished}')
            tohost_value = int.from_bytes(data, byteorder='little')
            if tohost_value != 0:
                await self.handle_tohost(tohost_value)

        for index, b in enumerate(data):
            byt_address = GlobalAddress(bit_addr=global_addr.addr*8+index*8)
            # If this cache line is fresh then we need to set it to all 0.
            # If the cache line is not loaded then we need to load it.
            if byt_address.is_vpu(self.params, self.tlb):
                logger.debug(f'{self.clock.cycle}: Writing  byte {hex(byt_address.addr)}')
                await self.write_byte(byt_address, b)
                # TODO: Be a bit more careful about whether we need to add this.
                await self.clock.next_cycle
            else:
                scalar_address = self.to_scalar_addr(byt_address)
                self.scalar.set_memory(scalar_address, b)

    async def get_memory_resolve(self, future, byte_futures, address):
        bs = bytearray([])
        for f in byte_futures:
            await f
            b = f.result()
            assert isinstance(b, int)
            bs.append(b)
        logger.debug(f'Read memory address {address}, result is {int.from_bytes(bytes(bs), byteorder="little", signed=True)}')
        future.set_result(bytes(bs))

    async def get_memory(self, address: int, size: int):
        """
        This blocks but only on things that should block the frontend.
        It returns a future that resolves when the value has been
        returned.
        """
        byte_futures = []
        #for index in range(size):
        #    byte_addr = GlobalAddress(bit_addr=(address+index)*8)
        #    is_vpu = byte_addr.is_vpu(self.params, self.tlb)
        #    if is_vpu:
        #        logger.warning(f'{self.clock.cycle}: Try to read a byte from vpu')
        #        read_future = await self.read_bytes(byte_addr, size)
        #        logger.warning(f'{self.clock.cycle}: read the byte')
        #    else:
        #        local_address = byte_addr.to_scalar_addr(self.params, self.tlb)
        #        read_future = await self.scalar.get_memory(local_address, size)
        #    byte_futures.append(read_future)
        # Check that the start and end are in the same word.
        start_addr = GlobalAddress(bit_addr=address*8)
        is_vpu = start_addr.is_vpu(self.params, self.tlb)
        if is_vpu:
            end_addr = start_addr.offset_bytes(size-1)
            assert start_addr.addr//self.params.word_bytes == end_addr.addr//self.params.word_bytes
            read_future = await self.read_bytes(start_addr, size)
        else:
            local_address = start_addr.to_scalar_addr(self.params, self.tlb)
            read_future = await self.scalar.get_memory(local_address, size)
        #future = self.clock.create_future()
        #logger.debug(f'Trying to read memory {address} size {size}')
        #self.clock.create_task(self.get_memory_resolve(future, byte_futures, address))
        #return future
        return read_future

    async def get_memory_blocking(self, address: int, size):
        future = await self.get_memory(address, size)
        await future
        return future.result()

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
        syscall_num = int.from_bytes(await self.get_memory_blocking(magic_mem_addr, 8), byteorder='little')
        arg0 = int.from_bytes(await self.get_memory_blocking(magic_mem_addr + 8, 8), byteorder='little')
        arg1 = int.from_bytes(await self.get_memory_blocking(magic_mem_addr + 16, 8), byteorder='little')
        arg2 = int.from_bytes(await self.get_memory_blocking(magic_mem_addr + 24, 8), byteorder='little')

        logger.debug(f'HTIF syscall: num={syscall_num}, args=({arg0}, {arg1}, {arg2})')

        ret_value = 0
        if syscall_num == 64:  # SYS_write
            fd = arg0
            buf_addr = arg1
            length = arg2

            # Read the buffer
            buf = await self.get_memory_blocking(buf_addr, length)
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

    async def flush_slot(self, slot, old_state):
        # Get the ordering for the slot we're flushing.
        # We can't use the to_j_saddr conversion functions since
        # we've already updated the cache table.
        # That's why we're passing in old_ident.
        if old_state.state == CacheState.M:
            page_bits = self.params.page_bytes * 8
            k_bit_addr = old_state.ident * self.params.cache_line_bytes * 8
            vpu_bit_addr = k_bit_addr * self.params.k_in_l
            vpu_page_address = VPUAddress(
                bit_addr=(k_bit_addr//page_bits) * page_bits,
                ordering=None,
                )
            info = self.tlb.get_page_info_from_vpu_addr(vpu_page_address)
            vpu_address = VPUAddress(bit_addr=vpu_bit_addr,
                                     ordering=info.local_address.ordering)
            write_line_label = self.waiting_write_line_label(vpu_address.addr)
            if self.exists_wait_future(write_line_label):
                # We want to flush this cache line but there is already a flush
                # of this cache line in progress. Wait for that to complete
                # first.
                future = self.get_wait_future(write_line_label)
                await future
            k_maddr = KMAddr(
                k_index=0,
                bit_addr=k_bit_addr,
                ordering=info.local_address.ordering,
                )
            j_saddr = JSAddr(
                k_index=0,
                j_in_k_index=0,
                bit_addr=slot*self.params.cache_line_bytes//self.params.j_in_k*8,
                ordering=info.local_address.ordering,
                )
            kinstr = kinstructions.WriteLine(
                k_maddr=k_maddr,
                j_saddr=j_saddr,
                n_cache_lines=1,
                )
            assert not self.exists_wait_future(write_line_label)
            # Make labels for each of the replys from the memlets
            k_write_line_labels = [self.waiting_write_line_label(vpu_address.addr, k_index)
                                   for k_index in range(self.params.k_in_l)]
            k_futures = []
            for label in k_write_line_labels:
                future = self.create_wait_future(label)
                k_futures.append(future)
            # Register the flushing of this cache line as something that is happening and
            # can be waited on.
            combined_future = self.create_wait_future(write_line_label)
            self.clock.create_task(combine_futures(combined_future, k_futures))
            await self.add_to_instruction_buffer(kinstr)

    async def assign_cache_slot(self, address: GlobalAddress):
        k_maddr = self.to_k_maddr(address)
        # Check that it is aligned to a cache slot
        assert self.k_maddr_is_aligned(k_maddr)
        assert k_maddr.k_index == 0
        ident = k_maddr.addr//self.params.cache_line_bytes
        slot = self.cache_table.get_free_slot(ident)
        if slot is None:
            slot, old_state = self.cache_table.get_eviction_slot(ident)
            await self.flush_slot(slot, old_state)
        return slot

    def waiting_write_line_label(self, mem_address, k_index=None):
        assert isinstance(mem_address, int)
        return ('WRITE_LINE', mem_address, k_index)

    def waiting_read_line_label(self, mem_address, k_index=None):
        assert isinstance(mem_address, int)
        return ('READ_LINE', mem_address, k_index)

    async def read_line(self, k_maddr, j_saddr, slot_state):
        logger.debug('Sending a read line instruction to kamlet')
        logger.debug('blexxxxeoop')
        kinstr = kinstructions.ReadLine(
            k_maddr=k_maddr,
            j_saddr=j_saddr,
            n_cache_lines=1,
            )
        logger.debug('bleeoop')
        read_wait_label = self.waiting_read_line_label(k_maddr.addr*self.params.k_in_l)
        # We also make labels for each jamlet since each one will individually
        # reply.
        logger.debug('bloop')
        j_futures = []
        for j_index in range(self.params.j_in_l):
            j_futures.append(self.create_wait_future(
                self.waiting_read_line_label(k_maddr.addr*self.params.k_in_l, j_index)))
        future = self.create_wait_future(read_wait_label)
        self.clock.create_task(combine_futures(future, j_futures))
        slot_state.state = CacheState.S
        logger.debug('Norp norp')
        await self.add_to_instruction_buffer(kinstr)
        await future

    async def require_cache(self, address: GlobalAddress):
        logger.debug(f'{self.clock.cycle}: Requiring cache for {hex(address.addr)}')
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
            slot = await self.assign_cache_slot(address)
        else:
            # Mark that we've used this cache slot recently.
            self.cache_table.touch_slot(slot)
        slot_state = self.cache_table.get_state(vpu_address)
        j_saddr = self.to_j_saddr(address)
        if slot_state.state == CacheState.I:
            if is_fresh:
                kinstr = kinstructions.ZeroLine(
                    j_saddr=j_saddr,
                    n_cache_lines=1,
                    )
                await self.add_to_instruction_buffer(kinstr)
                await self.clock.next_cycle
                slot_state.state = CacheState.M
            else:
                # If the cache is being written then we need to
                # wait until until the write completes
                wait_label = self.waiting_write_line_label(vpu_address.addr)
                if self.exists_wait_future(wait_label):
                    await self.get_wait_future(wait_label)
                # We need to read data into this line.
                # Does a read future already exist?
                read_wait_label = self.waiting_read_line_label(vpu_address.addr)
                if self.exists_wait_future(read_wait_label):
                    await self.get_wait_future(read_wait_label)
                else:
                    await self.read_line(k_maddr, j_saddr, slot_state)
                assert slot_state.state == CacheState.S
                
    def split_access_by_cacheline(self, addr: GlobalAddress, n_vlines: int):
        """
        We take an address and a number of vector lines, and we split it into
        separate access where each access lies within a single cache line.
        """
        vline_bytes = self.params.j_in_l * self.params.word_bytes
        base_vline_index = None
        last_cl_addr = None
        continuous_loads = []
        for vline_index in range(n_vlines):
            vline_addr = GlobalAddress(bit_addr=(addr.addr + vline_index*vline_bytes)*8)
            cl_addr = vline_addr.get_cache_line(self.params)
            if cl_addr != last_cl_addr:
                last_cl_addr = cl_addr
                if base_vline_index is not None:
                    continuous_loads.append((base_vline_index, vline_index-base_vline_index))
                base_vline_index = vline_index
        continuous_loads.append((base_vline_index, n_vlines-base_vline_index))
        return continuous_loads

    async def vload(self, vd: int, addr: int, element_width: SizeBits, n_elements: int, mask_reg: int):
        g_addr = GlobalAddress(bit_addr=addr*8)
        end_addr = GlobalAddress(bit_addr=addr*8 + element_width * n_elements - 1)
        # TODO: Support masking
        assert mask_reg is None

        n_vlines = element_width * n_elements//(self.params.maxvl_bytes * 8)
        assert (element_width * n_elements) % (self.params.maxvl_bytes * 8) == 0

        # Split the load into a continous load for each cache line
        split_loads = self.split_access_by_cacheline(g_addr, n_vlines)

        vline_bytes = self.params.j_in_l * self.params.word_bytes
        for vline_index, n_vlines in split_loads:
            vline_addr = GlobalAddress(bit_addr=(addr + vline_index*vline_bytes)*8)
            logger.debug(f'{self.clock.cycle}: Loading to {hex(vline_addr.addr)} -> {vd+vline_index} vlines={n_vlines}')
            cl_addr = vline_addr.get_cache_line(self.params)
            await self.require_cache(cl_addr)

            page_address = (vline_addr.addr//self.params.page_bytes) * self.params.page_bytes
            page_info = self.tlb.get_page_info(GlobalAddress(bit_addr=page_address*8))
            assert page_info.local_address.ordering.ew == element_width
            assert page_info.local_address.is_vpu

            for index in range(vline_index, vline_index+n_vlines):
                r = vd + index
                self.vrf_ordering[r] = page_info.local_address.ordering

            j_saddr = self.to_j_saddr(vline_addr)
            kinstr = kinstructions.Load(
                dst=vd+vline_index,
                j_saddr=j_saddr,
                n_vlines=n_vlines,
                )
            await self.add_to_instruction_buffer(kinstr)

    async def vstore(self, vs3: int, addr: int, element_width: SizeBits,
                     n_elements: int, mask_reg: int):
        logger.debug(f'{self.clock.cycle}: vstore from {vs3} to {hex(addr)}')
        g_addr = GlobalAddress(bit_addr=addr*8)
        end_addr = GlobalAddress(bit_addr=addr*8 + element_width * n_elements - 1)
        # TODO: Support masking
        assert mask_reg is None

        n_vlines = element_width * n_elements//(self.params.maxvl_bytes * 8)
        assert (element_width * n_elements) % (self.params.maxvl_bytes * 8) == 0

        # Split the load into a continous load for each cache line
        split_stores = self.split_access_by_cacheline(g_addr, n_vlines)

        vline_bytes = self.params.j_in_l * self.params.word_bytes
        for vline_index, n_vlines in split_stores:
            vline_addr = GlobalAddress(bit_addr=(addr + vline_index*vline_bytes)*8)
            logger.info(f'{self.clock.cycle}: Storing to {hex(vline_addr.addr)}->{vs3+vline_index} vlines={n_vlines}')
            cl_addr = vline_addr.get_cache_line(self.params)
            await self.require_cache(cl_addr)

            page_address = (vline_addr.addr//self.params.page_bytes) * self.params.page_bytes
            page_info = self.tlb.get_page_info(GlobalAddress(bit_addr=page_address*8))
            assert page_info.local_address.ordering.ew == element_width
            assert page_info.local_address.is_vpu

            j_saddr = self.to_j_saddr(vline_addr)

            kinstr_store = kinstructions.Store(
                src=vs3+vline_index,
                j_saddr=j_saddr,
                n_vlines=n_vlines,
                )
            await self.add_to_instruction_buffer(kinstr_store)
            # Mark cache as modified (dirty)
            vpu_address = self.to_vpu_addr(vline_addr)
            slot_state = self.cache_table.get_state(vpu_address)
            slot_state.state = CacheState.M

    def update(self):
        assert len(self.waiting) < 200
        for kamlet in self.kamlets:
            kamlet.update()
        for memlet in self.memlets:
            memlet.update()
        self.scalar.update()
        self.instruction_buffer.update()

    async def run(self):
        for kamlet in self.kamlets:
            self.clock.create_task(kamlet.run())
        for memlet in self.memlets:
            self.clock.create_task(memlet.run())
        self.clock.create_task(self.router_connections())
        self.clock.create_task(self.monitor_replys())
        self.clock.create_task(self.monitor_instruction_buffer())

    async def run_instructions(self, disasm_trace=None):
        logger.warning('run_instructions')
        while not self.finished:

            await self.clock.next_cycle

            first_bytes = await self.get_memory_blocking(self.pc, 2)
            is_compressed = decode.is_compressed(first_bytes)

            if is_compressed:
                instruction_bytes = first_bytes
                inst_hex = int.from_bytes(instruction_bytes[0:2], byteorder='little')
            else:
                instruction_bytes = await self.get_memory_blocking(self.pc, 4)
                inst_hex = int.from_bytes(instruction_bytes[0:4], byteorder='little')

            instruction = decode.decode(instruction_bytes)

            # Use disasm(pc) method if available, otherwise use str()
            if hasattr(instruction, 'disasm'):
                inst_str = instruction.disasm(self.pc)
            else:
                inst_str = str(instruction)

            logger.info(f'{self.clock.cycle}: pc={hex(self.pc)} bytes={hex(inst_hex)} instruction={inst_str}')

            if disasm_trace is not None:
                import disasm_trace as dt
                error = dt.check_instruction(disasm_trace, self.pc, inst_hex, inst_str)
                if error:
                    logger.error(error)
                    raise ValueError(error)

            await instruction.update_state(self)

