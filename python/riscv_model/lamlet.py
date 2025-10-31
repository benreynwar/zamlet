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
from collections import deque

import decode
from addresses import SizeBytes, SizeBits, TLB
from addresses import AddressConverter, Ordering, GlobalAddress, KMAddr, VPUAddress
from cache_table import CacheTable, CacheState
from params import LamletParams
from message import Header, MessageType, Direction, SendType
from kamlet import Kamlet
from memlet import Memlet
from runner import Future
import kinstructions
from response_tracker import ResponseTracker
from scalar import ScalarState


logger = logging.getLogger(__name__)


class Lamlet:

    def __init__(self, clock, params: LamletParams):
        self.clock = clock
        self.params = params
        self.pc = None
        self.scalar = ScalarState(clock, params)
        self.tlb = TLB(params)
        self.vrf_ordering = [Ordering(None, None) for _ in range(params.n_vregs)]
        self.vl = 0
        self.vtype = 0
        self.exit_code = None

        self.min_x = 0
        self.min_y = 0

        # Send instructions from left/top
        self.instr_x = self.min_x
        self.instr_y = self.min_y - 1

        self.instruction_buffer = deque()

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
                coords=mem_coords,
                kamlet_coords=(kamlet_x, kamlet_y),
                ))
        # A dictionary that maps labels to futures
        # Used for handling responses back from the kamlet grid.
        self.tracker = ResponseTracker(self.clock, self.params)
        self.conv = AddressConverter(self.params, self.tlb)
        self.finished = False

    def set_pc(self, pc):
        self.pc = pc

    def get_kamlet(self, x, y):
        kamlet_column = (x - self.min_x)//self.params.j_cols
        kamlet_row = (y - self.min_y)//self.params.j_rows
        return self.kamlets[kamlet_row*self.params.k_cols+kamlet_column]

    def get_jamlet(self, x, y):
        kamlet = self.get_kamlet(x, y)
        jamlet = kamlet.get_jamlet(x, y)
        return jamlet

    def allocate_memory(self, address: GlobalAddress, size: SizeBytes, is_vpu: bool, ordering: Ordering):
        page_bytes_per_memory = self.params.page_bytes // self.params.k_in_l
        self.tlb.allocate_memory(address, size, is_vpu, ordering)

    def to_scalar_addr(self, addr: GlobalAddress):
        return self.conv.to_scalar_addr(addr)

    
    def to_k_maddr(self, addr):
        return self.conv.to_k_maddr(addr)

    def to_vpu_addr(self, addr):
        return self.conv.to_vpu_addr(addr)

    async def write_bytes(self, address: GlobalAddress, value: bytes):
        k_maddr = self.to_k_maddr(address)
        kinstr = kinstructions.WriteImmBytes(
            k_maddr=k_maddr,
            imm=value,
            )
        await self.add_to_instruction_buffer(kinstr, k_maddr.k_index)

    async def read_bytes(self, address: GlobalAddress, size=1):
        """
        This blocks until the cache is ready an the instruction is received.
        It returns a future that resolves when the value is returned.
        """
        k_maddr = address.to_k_maddr(self.params, self.tlb)
        j_in_k_index = (k_maddr.addr//self.params.word_bytes) % self.params.j_in_k
        logger.debug(f'Lamlet.read_bytes {hex(address.addr)} k_maddr {k_maddr} j_in_k {j_in_k_index}')
        jamlet = self.kamlets[k_maddr.k_index].jamlets[j_in_k_index]
        label = ('READ_BYTES', address, size)
        src_coords_to_methods = {
                (jamlet.x, jamlet.y): self._read_bytes_resolve,
                }
        # Block if we don't have any response idents available
        ident, src_coords_to_future = await self.tracker.register_srcs(
                src_coords_to_methods=src_coords_to_methods, label=label)
        future = src_coords_to_future[(jamlet.x, jamlet.y)]
        kinstr = kinstructions.ReadBytes(
            k_maddr=k_maddr,
            size=size,
            ident=ident,
            )
        await self.add_to_instruction_buffer(kinstr, k_maddr.k_index)
        return future

    async def _read_bytes_resolve(self, packet):
        header = packet[0]
        assert isinstance(header, Header)
        return header.value

    def get_header_source_k_index(self, header):
        x_offset = header.source_x - self.min_x
        y_offset = header.source_y - self.min_y
        k_x = x_offset // self.params.j_cols
        k_y = y_offset // self.params.j_rows
        k_index = k_y * self.params.k_cols  + k_x
        logger.debug(f'({x_offset},{y_offset}) -> k_index {k_index}')
        return k_index

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
                        if conn.age > 500:
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
                    self.tracker.check_packet(packet)
                    header = None
                    packet = []

    async def add_to_instruction_buffer(self, instruction, k_index=None):
        logger.debug(f'{self.clock.cycle}: Adding {instruction} to buffer')
        while len(self.instruction_buffer) >= self.params.instruction_buffer_length:
            await self.clock.next_cycle
        self.instruction_buffer.append((instruction, k_index))

    def update_tokens(self, tokens):
        for index, kamlet in enumerate(self.kamlets):
            while kamlet.available_instruction_tokens:
                kamlet.take_instruction_token()
                tokens[index] += 1

    def have_tokens(self, tokens, k_index):
        if k_index is None:
            return all(tokens)
        else:
            return tokens[k_index]

    def decrement_tokens(self, tokens, k_index):
        if k_index is None:
            for index in range(len(tokens)):
                tokens[index] -= 1
                assert tokens[index] >= 0
        else:
            tokens[k_index] -= 1
            assert tokens[k_index] >= 0

    async def monitor_instruction_buffer(self):
        inactive_count = 0
        old_length = 0
        available_tokens = [0 for _ in range(self.params.k_in_l)]
        while True:
            self.update_tokens(available_tokens)
            logger.debug(f'{self.clock.cycle}: {len(self.instruction_buffer)} instrs in the buffer')
            if self.instruction_buffer and available_tokens:
                k_indices = [x[1] for x in self.instruction_buffer]
                k_indices_same = all(k_indices[0] == x for x in k_indices)
                if len(self.instruction_buffer) >= self.params.instructions_in_packet or (not k_indices_same) or inactive_count > 2:
                    instructions = []
                    dest_k_index = self.instruction_buffer[0][1]
                    while self.instruction_buffer and self.have_tokens(available_tokens, k_indices[0]):
                        logger.debug('doo doo')
                        if self.instruction_buffer[0][1] == k_indices[0]:
                            instructions.append(self.instruction_buffer.popleft()[0])
                            self.decrement_tokens(available_tokens, k_indices[0])
                        else:
                            break
                    if instructions:
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
        x = self.min_x + k_x * self.params.j_cols
        y = self.min_y + k_y * self.params.j_rows
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
                logger.debug(f'{self.clock.cycle}: Writing  byte {hex(byt_address.addr)} {b}')
                await self.write_bytes(byt_address, bytes([b]))
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
        start_addr = GlobalAddress(bit_addr=address*8)
        is_vpu = start_addr.is_vpu(self.params, self.tlb)
        if is_vpu:
            end_addr = start_addr.offset_bytes(size-1)
            assert start_addr.addr//self.params.word_bytes == end_addr.addr//self.params.word_bytes
            read_future = await self.read_bytes(start_addr, size)
        else:
            local_address = start_addr.to_scalar_addr(self.params, self.tlb)
            read_future = await self.scalar.get_memory(local_address, size)
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

    def get_jamlets(self):
        jamlets = []
        for kamlet in  self.kamlets:
            jamlets += kamlet.jamlets
        return jamlets

    async def vload(self, vd: int, addr: int, element_width: SizeBits, n_elements: int, mask_reg: int):
        g_addr = GlobalAddress(bit_addr=addr*8)
        self.check_element_width(g_addr, (n_elements*element_width)//8, element_width)
        k_maddr = self.to_k_maddr(g_addr)
        # TODO: Support masking
        assert mask_reg is None
        n_vlines = element_width * n_elements//(self.params.maxvl_bytes * 8)
        for reg in range(vd, vd+n_vlines):
            self.vrf_ordering[reg] = Ordering(word_order=None, ew=element_width)
        assert (element_width * n_elements) % (self.params.maxvl_bytes * 8) == 0
        kinstr = kinstructions.Load(
            dst=vd,
            k_maddr=k_maddr,
            n_vlines=n_vlines,
            )
        await self.add_to_instruction_buffer(kinstr)

    async def vstore(self, vs3: int, addr: int, element_width: SizeBits,
                     n_elements: int, mask_reg: int):
        g_addr = GlobalAddress(bit_addr=addr*8)
        self.check_element_width(g_addr, (n_elements*element_width)//8, element_width)
        k_maddr = self.to_k_maddr(g_addr)
        # TODO: Support masking
        assert mask_reg is None
        n_vlines = element_width * n_elements//(self.params.maxvl_bytes * 8)
        for reg in range(vs3, vs3+n_vlines):
            assert self.vrf_ordering[reg] == Ordering(word_order=None, ew=element_width)
        assert (element_width * n_elements) % (self.params.maxvl_bytes * 8) == 0
        kinstr = kinstructions.Store(
            src=vs3,
            k_maddr=k_maddr,
            n_vlines=n_vlines,
            )
        await self.add_to_instruction_buffer(kinstr)

    def check_element_width(self, addr: GlobalAddress, size: int, element_width: int):
        """
        Check that this region of memory all has this element width
        """
        # Split the load into a continous load for each cache line
        base_addr = addr.addr
        for offset in range(0, size, self.params.page_bytes):
            page_address = ((base_addr+offset)//self.params.page_bytes) * self.params.page_bytes
            page_info = self.tlb.get_page_info(GlobalAddress(bit_addr=page_address*8))
            assert page_info.local_address.ordering.ew == element_width
            assert page_info.local_address.is_vpu

    def update(self):
        for kamlet in self.kamlets:
            kamlet.update()
        for memlet in self.memlets:
            memlet.update()
        self.scalar.update()
        #self.ident_status(1)

    async def run(self):
        for kamlet in self.kamlets:
            self.clock.create_task(kamlet.run())
        for memlet in self.memlets:
            self.clock.create_task(memlet.run())
        self.clock.create_task(self.router_connections())
        self.clock.create_task(self.monitor_replys())
        self.clock.create_task(self.monitor_instruction_buffer())

    async def run_instruction(self, disasm_trace=None):
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

        logger.info(f'{self.clock.cycle}: pc={hex(self.pc)} bytes={hex(inst_hex)} instruction={inst_str} {type(instruction)}')

        if disasm_trace is not None:
            import disasm_trace as dt
            error = dt.check_instruction(disasm_trace, self.pc, inst_hex, inst_str)
            if error:
                logger.error(error)
                raise ValueError(error)

        await instruction.update_state(self)

    async def run_instructions(self, disasm_trace=None):
        logger.warning('run_instructions')
        while not self.finished:

            await self.clock.next_cycle
            await self.run_instruction(disasm_trace)
            await self.run_instruction(disasm_trace)

    def ident_status(self, ident):
        """
        For a given ident show all the messages todo with it in the system.
        """
        seen = []
        for kamlet in self.kamlets:
            for jamlet in kamlet.jamlets:
                for input_direction, ib in jamlet.router._input_buffers.items():
                    for item in ib.queue:
                        if hasattr(item, 'ident'):
                            if item.ident == ident:
                                seen.append((jamlet.x, jamlet.y, 'I', input_direction, item))
                for output_direction, ib in jamlet.router._output_buffers.items():
                    for item in ib.queue:
                        if hasattr(item, 'ident'):
                            if item.ident == ident:
                                seen.append((jamlet.x, jamlet.y, 'O', output_direction, item))
        for s in seen:
            logger.warning(f'{self.clock.cycle}: seen line is {s}')

