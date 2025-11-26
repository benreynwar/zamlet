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
from typing import List, Tuple, Deque, Any
from dataclasses import dataclass

from zamlet import decode
from zamlet import addresses
from zamlet.addresses import SizeBytes, SizeBits, TLB, WordOrder
from zamlet.addresses import AddressConverter, Ordering, GlobalAddress, KMAddr, VPUAddress
from zamlet.kamlet.cache_table import CacheTable, CacheState, WaitingItem, WaitingFuture, ProtocolState
from zamlet.params import LamletParams
from zamlet.message import Header, MessageType, Direction, SendType, TaggedHeader, CHANNEL_MAPPING
from zamlet.kamlet.kamlet import Kamlet
from zamlet.memlet import Memlet
from zamlet.runner import Future
from zamlet.kamlet import kinstructions
from zamlet.lamlet.scalar import ScalarState
from zamlet import utils
import zamlet.disasm_trace as dt


logger = logging.getLogger(__name__)

@dataclass
class SectionInfo:
    """
    A section of memory that is guaranteed to all be on one page.
    """
    # Is the page on the VPU
    is_vpu: bool
    # Is this memory region part of an element (i.e. not even an entire element)
    # This happens when an element is split across 2 pages.
    is_a_partial_element: bool
    # The element_index that these region starts with
    start_index: int
    # The logical address of the start of the section
    start_address: int
    # The logical address of the end of the section
    end_address: int


class Lamlet:

    def __init__(self, clock, params: LamletParams):
        self.clock = clock
        self.params = params
        self.pc = None
        self.scalar = ScalarState(clock, params)
        self.tlb = TLB(params)
        self.vrf_ordering: List[Ordering|None] = [None for _ in range(params.n_vregs)]
        self.vl = 0
        self.vtype = 0
        self.vstart = 0
        self.exit_code = None

        self.word_order = WordOrder.STANDARD

        self.min_x = 0
        self.min_y = 0

        # Send instructions from left/top
        self.instr_x = self.min_x
        self.instr_y = self.min_y - 1

        self.instruction_buffer: Deque[Any] = deque()

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
        #self.tracker = ResponseTracker(self.clock, self.params)
        self.conv = AddressConverter(self.params, self.tlb)
        self.finished = False

        # These are actions that are waiting on a cache state to update, or for messages to be received.
        self.waiting_items: List[WaitingItem|None] = [None for _ in range(params.n_items)]

        self.next_writeset_ident = 0
        self.next_instr_ident = 0

    async def get_free_item_index(self):
        while True:
            valid_indices = [index for index, x in enumerate(self.waiting_items) if x is None]
            if valid_indices:
                break
            await self.clock.next_cycle
        return valid_indices[0]

    #async def add_item(self, new_item, cache_is_write, cache_slot):
    #    item = WaitingItem(
    #        item=new_item,
    #        cache_is_write=cache_is_write,
    #        cache_is_avail=True,
    #        cache_slot=cache_slot,
    #        )
    #    new_item_index = await self.get_free_item_index()
    #    self.waiting_items[new_item_index] = item
    #    return new_item_index

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

    def allocate_memory(self, address: GlobalAddress, size: SizeBytes, is_vpu: bool, ordering: Ordering|None):
        page_bytes_per_memory = self.params.page_bytes // self.params.k_in_l
        self.tlb.allocate_memory(address, size, is_vpu, ordering)

    def to_scalar_addr(self, addr: GlobalAddress):
        return self.conv.to_scalar_addr(addr)

    def to_global_addr(self, addr):
        return self.conv.to_global_addr(addr)
    
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

    async def read_byte(self, address: GlobalAddress):
        """
        This blocks until the cache is ready an the instruction is received.
        It returns a future that resolves when the value is returned.
        """
        k_maddr = address.to_k_maddr(self.tlb)
        j_in_k_index = (k_maddr.addr//self.params.word_bytes) % self.params.j_in_k
        logger.debug(f'{self.clock.cycle}: lamlet: Lamlet.read_bytes {hex(address.addr)} k_maddr {k_maddr} j_in_k {j_in_k_index}')
        item_index = await self.get_free_item_index()
        # The waiting item indicates that we are waiting for a response.
        future = self.clock.create_future()
        self.waiting_items[item_index] = WaitingFuture(future=future)
        kinstr = kinstructions.ReadByte(
            k_maddr=k_maddr,
            ident=item_index,
            )
        await self.add_to_instruction_buffer(kinstr, k_maddr.k_index)
        return future

    async def _read_bytes_resolve(self, packet):
        header = packet[0]
        assert isinstance(header, Header)
        return header.value

    #async def read_register_element(self, vreg: int, element_index: int, element_width: int):
    #    """
    #    Read an element from a vector register.
    #    Returns a future that resolves to the value as bytes.
    #    """
    #    # Determine which jamlet/kamlet holds this element
    #    vw_index = element_index % self.params.j_in_l
    #    k_index, j_in_k_index = addresses.vw_index_to_k_indices(
    #        self.params, addresses.WordOrder.STANDARD, vw_index)

    #    jamlet = self.kamlets[k_index].jamlets[j_in_k_index]
    #    label = ('READ_REGISTER_ELEMENT', vreg, element_index)
    #    src_coords_to_methods = {
    #        (jamlet.x, jamlet.y): self._read_bytes_resolve,
    #    }
    #    ident, src_coords_to_future = await self.tracker.register_srcs(
    #        src_coords_to_methods=src_coords_to_methods, label=label)
    #    future = src_coords_to_future[(jamlet.x, jamlet.y)]

    #    kinstr = kinstructions.ReadRegElement(
    #        rd=0,
    #        src=vreg,
    #        element_index=element_index,
    #        element_width=element_width,
    #        ident=ident,
    #    )
    #    await self.add_to_instruction_buffer(kinstr, k_index=k_index)
    #    return future

    def get_header_source_k_index(self, header):
        x_offset = header.source_x - self.min_x
        y_offset = header.source_y - self.min_y
        k_x = x_offset // self.params.j_cols
        k_y = y_offset // self.params.j_rows
        k_index = k_y * self.params.k_cols  + k_x
        logger.debug(f'({x_offset},{y_offset}) -> k_index {k_index}')
        return k_index

    async def router_connections(self, channel):
        '''
        Move words between router buffers
        '''
        # We should have a grid of routers from (-1, 0) to (n_cols, n_rows-1)
        routers = {}
        n_rows = self.params.j_rows * self.params.k_rows
        n_cols = self.params.j_cols * self.params.k_cols
        for memlet in self.memlets:
            for router_channels in memlet.routers:
                r = router_channels[channel]
                coords = (r.x, r.y)
                assert coords not in routers
                routers[coords] = r
        for kamlet in self.kamlets:
            for jamlet in kamlet.jamlets:
                r = jamlet.routers[channel]
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
        header = None
        packet = []
        while True:
            await self.clock.next_cycle
            for channel in range(self.params.n_channels):
                buffer = self.kamlets[0].jamlets[0].routers[channel]._output_buffers[Direction.N]
                if buffer:
                    word = buffer.popleft()
                    if header is None:
                        assert isinstance(word, Header)
                        header = word.copy()
                        remaining_words = header.length
                    else:
                        assert not isinstance(word, Header)
                    packet.append(word)
                    remaining_words -= 1
                    if remaining_words == 0:
                        self.process_packet(packet)
                        header = None
                        packet = []

    def process_packet(self, packet):
        header = packet[0]
        assert isinstance(header, Header)
        assert header.length == len(packet)
        if header.message_type == MessageType.READ_BYTE_RESP:
            assert len(packet) == 1
            item = self.waiting_items[header.ident]
            assert isinstance(item.item, Future)
            item.item.set_result(header.value)
            self.waiting_items[header.ident] = None
            logger.debug(f'{self.clock.cycle}: lamlet: Got a READ_BYTE_RESP from ({header.source_x, header.source_y}) is {header.value}')
        elif header.message_type == MessageType.READ_WORDS_RESP:
            item = self.waiting_items[header.ident]
            assert isinstance(item.item, Future)
            item.item.set_result(packet[1:])
            self.waiting_items[header.ident] = None
            logger.debug(f'{self.clock.cycle}: lamlet: Got a READ_WORDS_RESP from ({header.source_x, header.source_y}) is {packet[1:]}')
        else:
            raise NotImplementedError()

    async def add_to_instruction_buffer(self, instruction, k_index=None):
        logger.debug(f'{self.clock.cycle}: lamlet: Adding {type(instruction)} to buffer')
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
            if self.instruction_buffer and available_tokens:
                k_indices = [x[1] for x in self.instruction_buffer]
                k_indices_same = all(k_indices[0] == x for x in k_indices)
                if len(self.instruction_buffer) >= self.params.instructions_in_packet or (not k_indices_same) or inactive_count > 2:
                    instructions = []
                    dest_k_index = self.instruction_buffer[0][1]
                    while self.instruction_buffer and self.have_tokens(available_tokens, k_indices[0]):
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
        channel = CHANNEL_MAPPING[packet[0].message_type]
        queue = jamlet.routers[channel]._input_buffers[direction]
        assert port == 0
        while packet:
            await self.clock.next_cycle
            if len(queue) < queue.length:
                queue.append(packet.pop(0))

    async def set_memory(self, address: int, data: bytes):
        logger.debug(f'Writing to memory from {hex(address)} to {hex(address+len(data)-1)}')
        global_addr = GlobalAddress(bit_addr=address*8, params=self.params)
        # Check for HTIF tohost write (8-byte aligned)
        if global_addr.addr == self.params.tohost_addr and len(data) == 8:
            logger.debug(f'It is a HTIF addres. finished is {self.finished}')
            tohost_value = int.from_bytes(data, byteorder='little')
            if tohost_value != 0:
                await self.handle_tohost(tohost_value)

        for index, b in enumerate(data):
            byt_address = GlobalAddress(bit_addr=global_addr.addr*8+index*8, params=self.params)
            # If this cache line is fresh then we need to set it to all 0.
            # If the cache line is not loaded then we need to load it.
            if byt_address.is_vpu(self.tlb):
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

    async def combine_read_futures(self, combined_future: Future, read_futures: List[Future]):
        for future in read_futures:
            await future
        byts = [future.result() for future in read_futures]
        all_byts = bytes()
        for byt in byts:
            all_byts += byt
        combined_future.set_result(all_byts)

    async def get_memory(self, address: int, size: int) -> Future:
        """
        This blocks but only on things that should block the frontend.
        It returns a future that resolves when the value has been
        returned.
        """
        start_addr = GlobalAddress(bit_addr=address*8, params=self.params)
        is_vpu = start_addr.is_vpu(self.tlb)
        if is_vpu:
            logger.info(f'get_memory: VPU read addr=0x{address:x}, start_addr.addr={start_addr.addr}')
            read_futures = [await self.read_byte(GlobalAddress(bit_addr=(start_addr.addr+offset)*8, params=self.params))
                            for offset in range(size)]
            read_future = self.clock.create_future()
            self.clock.create_task(self.combine_read_futures(read_future, read_futures))
        else:
            local_address = start_addr.to_scalar_addr(self.tlb)
            read_future = await self.scalar.get_memory(local_address, size=size)
        return read_future

    async def get_memory_blocking(self, address: int, size: int):
        future = await self.get_memory(address, size)
        await future
        result = future.result()
        return result

    async def handle_tohost(self, tohost_value):
        """Handle HTIF syscall via tohost write."""
        # Check if this is an exit code (LSB = 1)
        if tohost_value & 1:
            self.finished = True
            self.exit_code = tohost_value >> 1
            if self.exit_code == 0:
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

    def get_memory_split(self, g_addr: GlobalAddress, element_width: int, n_elements: int,
                         first_index: int) -> List[SectionInfo]:
        """
        Takes an address in global memory and a size.
        Works out what pages that is distributed across.
        For each page the data might be in scalar memory or vpu memory.
          - We need to split the it into accesses in scalar memory and vpu memory.
          - We need to consider elements that might be split across the transition from
            scalar memory to vpu memory.
        It returns a list of tuples where each tuple represents either a partial element
        of an element that straddles a vpu/scalar memory boundary or a list of elements
        entirely in the vpu or scalar memory. 
        Each tuple is of the form
        (is_vpu, is_partial, starting_index, starting_address, ending_address)
        The ending address is the byte address after the final byte.
        """

        start_index = first_index
        start_addr = g_addr.addr
        lumps: List[Tuple[bool, int, int, int]] = []
        element_offset_bits = (start_addr*8) % element_width
        assert element_offset_bits % 8 == 0
        element_offset = element_offset_bits//8
        eb = element_width//8

        l_cache_line_bytes = self.params.cache_line_bytes * self.params.k_in_l

        while start_index < n_elements:
            current_element_addr = g_addr.addr + start_index * eb
            page_address = (start_addr//self.params.page_bytes) * self.params.page_bytes
            page_info = self.tlb.get_page_info(GlobalAddress(bit_addr=page_address*8, params=self.params))
            remaining_elements = n_elements - start_index

            cache_line_boundary = ((start_addr // l_cache_line_bytes) + 1) * l_cache_line_bytes
            page_boundary = page_address + self.params.page_bytes
            next_boundary = min(cache_line_boundary, page_boundary)

            end_addr = min(current_element_addr + remaining_elements * eb, next_boundary)

            lumps.append((page_info.local_address.is_vpu, start_index, start_addr, end_addr))
            start_index = (end_addr - g_addr.addr)//eb
            start_addr = end_addr

        # Now loop through the regions and see if there are any elements that span regions.
        # i.e. a single element that is partially in the scalar memory and partially in the VPU memory.
        # We make tuples of the form (is_vpu, is_a_partial_element, start_index, start_address, end_address)
        sections : List[SectionInfo]
        if not element_offset:
            sections = [SectionInfo(is_vpu, False, start_index, start_addr, end_addr)
                        for is_vpu, start_index, start_addr, end_addr in lumps]
        else:
            sections = []
            next_index = first_index
            logger.info(f'get_memory_split: Processing lumps with element_offset={element_offset}')
            for lump_is_vpu, lump_start_index, lump_start_addr, lump_end_addr in lumps:
                logger.info(f'  Lump: is_vpu={lump_is_vpu}, start_idx={lump_start_index}, '
                           f'start_addr=0x{lump_start_addr:x}, end_addr=0x{lump_end_addr:x}')
                assert next_index == lump_start_index

                start_offset = (lump_start_addr - g_addr.addr) % eb
                if start_offset != 0:
                    start_whole_addr = lump_start_addr + (eb - start_offset)
                    assert start_whole_addr-1 <= lump_end_addr
                    logger.info(f'    Adding partial start: idx={next_index}, '
                               f'start=0x{lump_start_addr:x}, end=0x{start_whole_addr:x}')
                    sections.append(SectionInfo(lump_is_vpu, True, next_index, lump_start_addr, start_whole_addr))
                    next_index += 1
                else:
                    start_whole_addr = lump_start_addr

                end_offset = (lump_end_addr - g_addr.addr) % eb
                if end_offset != 0:
                    end_whole_addr = lump_end_addr - end_offset
                else:
                    end_whole_addr = lump_end_addr

                if end_whole_addr - start_whole_addr > 0:
                    logger.info(f'    Adding whole elements: idx={next_index}, '
                               f'start=0x{start_whole_addr:x}, end=0x{end_whole_addr:x}')
                    sections.append(SectionInfo(lump_is_vpu, False, next_index, start_whole_addr, end_whole_addr))
                    next_index += (end_whole_addr - start_whole_addr) // eb
                if lump_end_addr != end_whole_addr:
                    logger.info(f'    Adding partial end: idx={next_index}, '
                               f'start=0x{end_whole_addr:x}, end=0x{lump_end_addr:x}')
                    sections.append(SectionInfo(lump_is_vpu, True, next_index, end_whole_addr, lump_end_addr))
        logger.info(f'get_memory_split: Generated {len(sections)} sections')
        for i, section in enumerate(sections):
            logger.info(f'  Section {i}: is_vpu={section.is_vpu}, partial={section.is_a_partial_element}, '
                       f'idx={section.start_index}, start=0x{section.start_address:x}, '
                       f'end=0x{section.end_address:x}')
        return sections

    def get_writeset_ident(self):
        ident = self.next_writeset_ident
        self.next_writeset_ident += 1
        return ident

    def get_instr_ident(self, n_idents=1):
        assert n_idents >= 1
        ident = self.next_instr_ident
        self.next_instr_ident += n_idents
        return ident

    async def vload(self, vd: int, addr: int, ordering: addresses.Ordering,
                    n_elements: int, mask_reg: int|None, start_index: int,
                    reg_ordering: addresses.Ordering | None = None):
        await self.vloadstore(vd, addr, ordering, n_elements, mask_reg, start_index,
                              is_store=False, reg_ordering=reg_ordering)

    async def vstore(self, vs: int, addr: int, ordering: addresses.Ordering,
                    n_elements: int, mask_reg: int|None, start_index: int):
        await self.vloadstore(vs, addr, ordering, n_elements, mask_reg, start_index, is_store=True)

    async def vloadstore(self, reg_base: int, addr: int, ordering: addresses.Ordering,
                         n_elements: int, mask_reg: int|None, start_index: int, is_store: bool,
                         reg_ordering: addresses.Ordering | None = None):
        """
        We have 3 different kinds of vector loads/stores.
        - In VPU memory and aligned (this is the fastest by far)
        - In VPU memory but not aligned
            (We need to read from another jamlets memory).
        - In Scalar memory. We need to send the data element by element.

        And we could have a load that spans scalar and VPU regions of memory. Potentially
        an element could be half in VPU memory and half in scalar memory.
        """
        g_addr = GlobalAddress(bit_addr=addr*8, params=self.params)
        mem_ew = ordering.ew
        # For loads, reg_ordering specifies the register element width (defaults to memory ew)
        # For stores, register ordering comes from the register file state
        if is_store:
            assert reg_ordering is None, "reg_ordering should not be specified for stores"
            reg_ordering = self.vrf_ordering[reg_base]
            assert reg_ordering is not None, f"Register v{reg_base} has no ordering set"
        elif reg_ordering is None:
            reg_ordering = ordering
        reg_ew = reg_ordering.ew

        size = (n_elements * reg_ew) // 8
        wb = self.params.word_bytes

        # This is an identifier that groups a number of writes to a vector register together.
        # These writes are guanteed to work on separate bytes so that the write order does not matter.
        writeset_ident = self.get_writeset_ident()

        vline_bits = self.params.maxvl_bytes * 8
        n_vlines = (reg_ew * n_elements + vline_bits - 1) // vline_bits
        for vline_reg in range(reg_base, reg_base+n_vlines):
            self.vrf_ordering[vline_reg] = Ordering(word_order=addresses.WordOrder.STANDARD, ew=reg_ew)

        base_reg_addr = addresses.RegAddr(
            reg=reg_base, addr=0, params=self.params, ordering=reg_ordering)

        # reg_ew determines the size of elements we're moving (not mem_ew which is just memory ordering)
        for section in self.get_memory_split(g_addr, reg_ew, n_elements, start_index):
            if section.is_a_partial_element:
                reg_addr = base_reg_addr.offset_bytes(section.start_address - g_addr.addr)
                # The partial is either the start of an element or the end of an element.
                # Either the starting_addr or the ending_addr must be a cache line boundary
                start_is_cacheline_boundary = section.start_address % self.params.cache_line_bytes == 0
                end_is_cacheline_boundary = section.end_address % self.params.cache_line_bytes == 0
                if not (start_is_cacheline_boundary or end_is_cacheline_boundary):
                    logger.error(f'Partial element not at cache line boundary: start=0x{section.start_address:x}, end=0x{section.end_address:x}, '
                                f'cache_line_bytes={self.params.cache_line_bytes}, start_idx={section.start_index}')
                assert start_is_cacheline_boundary or end_is_cacheline_boundary
                assert not (start_is_cacheline_boundary and end_is_cacheline_boundary)
                starting_g_addr = GlobalAddress(bit_addr=section.start_address*8, params=self.params)
                k_maddr = self.to_k_maddr(starting_g_addr)
                assert reg_ew % 8 == 0
                mask_index = section.start_index // self.params.j_in_l
                size = section.end_address - section.start_address
                if section.is_vpu:
                    dst = reg_base + (section.start_index * reg_ew)//(self.params.vline_bytes * 8)
                    kinstr: kinstructions.KInstr
                    if size <= 1:
                        dst_offset = ((section.start_index * reg_ew) % (self.params.vline_bytes * 8))//8
                        bit_mask = (1 << 8) - 1
                        if is_store:
                            kinstr = kinstructions.StoreByte(
                                src=reg_addr,
                                dst=k_maddr,
                                bit_mask=bit_mask,
                                writeset_ident=writeset_ident,
                                mask_reg=mask_reg,
                                mask_index=mask_index,
                                ident=writeset_ident,
                                )
                        else:
                            kinstr = kinstructions.LoadByte(
                                dst=reg_addr,
                                src=k_maddr,
                                bit_mask=bit_mask,
                                writeset_ident=writeset_ident,
                                mask_reg=mask_reg,
                                mask_index=mask_index,
                                ident=writeset_ident,
                                )
                    else:
                        instr_ident = self.get_instr_ident(2)
                        if is_store:
                            byte_mask = [0] * wb
                            start_word_byte = k_maddr.addr % wb
                            for byte_index in range(start_word_byte, start_word_byte + size):
                                byte_mask[byte_index] = 1
                            byte_mask_as_int = utils.list_of_uints_to_uint(byte_mask, width=1)
                            logger.info(f'StoreWord partial: idx={section.start_index}, '
                                       f'src=0x{section.start_address:x}-0x{section.end_address:x}, '
                                       f'src_reg={reg_addr}, dst_addr=0x{k_maddr.addr:x}, '
                                       f'byte_mask=0x{byte_mask_as_int:x}, instr_ident={instr_ident}')
                            kinstr = kinstructions.StoreWord(
                                src=reg_addr,
                                dst=k_maddr,
                                byte_mask=byte_mask_as_int,
                                writeset_ident=writeset_ident,
                                mask_reg=mask_reg,
                                mask_index=mask_index,
                                instr_ident=instr_ident,
                            )
                        else:
                            byte_mask = [0] * wb
                            start_word_byte = reg_addr.offset_in_word % wb
                            for byte_index in range(start_word_byte, start_word_byte + size):
                                byte_mask[byte_index] = 1
                            byte_mask_as_int = utils.list_of_uints_to_uint(byte_mask, width=1)
                            logger.info(f'LoadWord partial: idx={section.start_index}, '
                                       f'src=0x{section.start_address:x}-0x{section.end_address:x}, '
                                       f'dst_reg={dst}, dst_offset={reg_addr.offset_in_word}, byte_mask=0x{byte_mask_as_int:x}, '
                                       f'k_maddr={k_maddr}')
                            kinstr = kinstructions.LoadWord(
                                dst=reg_addr,
                                src=k_maddr,
                                byte_mask=byte_mask_as_int,
                                writeset_ident=writeset_ident,
                                mask_reg=mask_reg,
                                mask_index=mask_index,
                                instr_ident=instr_ident,
                            )
                    await self.add_to_instruction_buffer(kinstr)
                else:
                    element_offset = starting_g_addr.bit_addr % (self.params.word_bytes * 8)
                    assert element_offset % 8 == 0
                    assert reg_ew % 8 == 0
                    if start_is_page_boundary:
                        # We're the second segment of the element
                        start_byte_in_element = (reg_ew - element_offset)//8
                    else:
                        # We're the first segment of the element
                        start_byte_in_element = (element_offset)//8
                    if is_store:
                        await self.vstore_scalar_partial(
                                vd=vd, addr=section.start_address, size=size, src_ordering=ordering,
                                mask_reg=mask_reg, mask_index=mask_index, element_index=section.start_index,
                                writeset_ident=writeset_ident, start_byte=start_byte_in_element)
                    else:
                        await self.vload_scalar_partial(
                                vd=vd, addr=section.start_address, size=size, dst_ordering=ordering,
                                mask_reg=mask_reg, mask_index=mask_index, element_index=section.start_index,
                                writeset_ident=writeset_ident, start_byte=start_byte_in_element)
            else:
                if section.is_vpu:
                    section_elements = ((section.end_address - section.start_address) * 8)//reg_ew
                    starting_g_addr = GlobalAddress(bit_addr=section.start_address*8, params=self.params)
                    self.check_element_width(starting_g_addr, section.end_address - section.start_address, mem_ew)
                    k_maddr = self.to_k_maddr(starting_g_addr)

                    l_cache_line_bytes = self.params.cache_line_bytes * self.params.k_in_l
                    assert section.start_address//l_cache_line_bytes == (section.end_address-1)//l_cache_line_bytes

                    if is_store:
                        instr_ident = self.get_instr_ident()
                        logger.info(f'Store: idx={section.start_index}, '
                                   f'addr=0x{section.start_address:x}-0x{section.end_address:x}, '
                                   f'k_addr=0x{k_maddr.addr:x}, n_elements={section_elements}, '
                                   f'instr_ident={instr_ident}')
                        kinstr = kinstructions.Store(
                            src=reg_base,
                            k_maddr=k_maddr,
                            start_index=section.start_index,
                            n_elements=section_elements,
                            src_ordering=reg_ordering,
                            mask_reg=mask_reg,
                            writeset_ident=writeset_ident,
                            instr_ident=instr_ident,
                            )
                    else:
                        instr_ident = self.get_instr_ident()
                        kinstr = kinstructions.Load(
                            dst=reg_base,
                            k_maddr=k_maddr,
                            start_index=section.start_index,
                            n_elements=section_elements,
                            dst_ordering=reg_ordering,
                            mask_reg=mask_reg,
                            writeset_ident=writeset_ident,
                            instr_ident=instr_ident,
                            )
                        logger.debug(f'{self.clock.cycle}: LAMLET CREATE Load instr_ident={instr_ident} dst=v{reg_base} mask_reg={mask_reg}')
                    await self.add_to_instruction_buffer(kinstr)
                else:
                    if is_store:
                        await self.vstore_scalar(reg_base, section.start_address, ordering, section_elements,
                                           mask_reg, section.start_index, writeset_ident)
                    else:
                        await self.vload_scalar(reg_base, section.start_address, ordering, section_elements,
                                          mask_reg, section.start_index, writeset_ident)


    #async def vload(self, vd: int, addr: int, ordering: addresses.Ordering,
    #                n_elements: int, mask_reg: int, start_index: int):
    #    """
    #    We have 3 different kinds of vector loads.
    #    - In VPU memory and aligned (this is the fastest by far)
    #    - In VPU memory but not aligned
    #        (We need to read from another jamlets memory).
    #    - In Scalar memory. We need to send the data element by element.

    #    And we could have a load that spans scalar and VPU regions of memory. Potentially
    #    an element could be half in VPU memory and half in scalar memory.
    #    """
    #    logger.info(f'vload: addr=0x{addr:x}, element_width={ordering.ew}, n_elements={n_elements}')
    #    g_addr = GlobalAddress(bit_addr=addr*8, params=self.params)
    #    ew = ordering.ew

    #    vline_aligned = ((addr % self.params.vline_bytes) * 8 ==
    #                     (start_index * ew) % (self.params.vline_bytes * 8))

    #    size = (n_elements*ew)//8
    #    eb = ew // 8
    #    wb = self.params.word_bytes

    #    # This is an identifier that groups a number of writes to a vector register together.
    #    # These writes are guanteed to work on separate bytes so that the write order does not matter.
    #    writeset_ident = self.get_writeset_ident()

    #    vline_bits = self.params.maxvl_bytes * 8
    #    n_vlines = (ew * n_elements + vline_bits - 1) // vline_bits
    #    for reg in range(vd, vd+n_vlines):
    #        self.vrf_ordering[reg] = Ordering(word_order=addresses.WordOrder.STANDARD, ew=ew)

    #    for is_vpu, is_partial_element, starting_index, starting_addr, ending_addr in self.get_memory_split(
    #            g_addr, ew, n_elements, start_index):
    #        if is_partial_element:
    #            # The partial is either the start of an element or the end of an element.
    #            # Either the starting_addr or the ending_addr must be a page boundary
    #            start_is_page_boundary = starting_addr % self.params.page_bytes == 0
    #            end_is_page_boundary = ending_addr % self.params.page_bytes == 0
    #            assert start_is_page_boundary or end_is_page_boundary
    #            assert not (start_is_page_boundary and end_is_page_boundary)
    #            starting_g_addr = GlobalAddress(bit_addr=starting_addr*8, params=self.params)
    #            k_maddr = self.to_k_maddr(starting_g_addr)
    #            assert ew % 8 == 0
    #            mask_index = starting_index // self.params.j_in_l
    #            size = ending_addr - starting_addr
    #            if is_vpu:
    #                dst = vd + (starting_index * ew)//(self.params.vline_bytes * 8)
    #                kinstr: kinstructions.KInstr
    #                if size <= 1:
    #                    dst_offset = ((starting_index * ew) % (self.params.vline_bytes * 8))//8
    #                    reg_addr = addresses.RegAddr(
    #                            reg=dst, addr=dst_offset, params=self.params, ordering=ordering)
    #                    bit_mask = (1 << 8) - 1
    #                    kinstr = kinstructions.LoadByte(
    #                        dst=reg_addr,
    #                        src=k_maddr,
    #                        bit_mask=bit_mask,
    #                        writeset_ident=writeset_ident,
    #                        mask_reg=mask_reg,
    #                        mask_index=mask_index,
    #                        ident=writeset_ident,
    #                        )
    #                else:
    #                    dst_offset = ((starting_index * ew) % (self.params.vline_bytes * 8))//8
    #                    dst_offset = dst_offset//wb * wb
    #                    reg_addr = addresses.RegAddr(
    #                            reg=dst, addr=dst_offset, params=self.params, ordering=ordering)
    #                    byte_mask = [0] * wb
    #                    start_word_byte = starting_g_addr.addr % wb
    #                    for byte_index in range(start_word_byte, start_word_byte + size):
    #                        byte_mask[byte_index] = 1
    #                    byte_mask_as_int = utils.list_of_uints_to_uint(byte_mask, width=1)
    #                    kinstr = kinstructions.LoadWord(
    #                        dst=reg_addr,
    #                        src=k_maddr,
    #                        byte_mask=byte_mask_as_int,
    #                        writeset_ident=writeset_ident,
    #                        mask_reg=mask_reg,
    #                        mask_index=mask_index,
    #                    )
    #                await self.add_to_instruction_buffer(kinstr)
    #            else:
    #                element_offset = starting_g_addr.bit_addr % (self.params.word_bytes * 8)
    #                assert element_offset % 8 == 0
    #                assert ew % 8 == 0
    #                if start_is_page_boundary:
    #                    # We're the second segment of the element
    #                    start_byte_in_element = (ew - element_offset)//8
    #                else:
    #                    # We're the first segment of the element
    #                    start_byte_in_element = (element_offset)//8
    #                await self.vload_scalar_partial(
    #                        vd=vd, addr=starting_addr, size=size, dst_ordering=ordering,
    #                        mask_reg=mask_reg, mask_index=mask_index, element_index=starting_index,
    #                        writeset_ident=writeset_ident, start_byte=start_byte_in_element)
    #        else:
    #            if is_vpu:
    #                section_elements = ((ending_addr - starting_addr) * 8)//ew
    #                starting_g_addr = GlobalAddress(bit_addr=starting_addr*8, params=self.params)
    #                self.check_element_width(starting_g_addr, ending_addr - starting_addr, ew)
    #                k_maddr = self.to_k_maddr(starting_g_addr)
    #                kinstr = kinstructions.Load(
    #                    dst=vd,
    #                    k_maddr=k_maddr,
    #                    start_index=starting_index,
    #                    n_elements=section_elements,
    #                    dst_ordering=ordering,
    #                    mask_reg=mask_reg,
    #                    writeset_ident=writeset_ident,
    #                    )
    #                await self.add_to_instruction_buffer(kinstr)
    #            else:
    #                self.vload_scalar(vd, starting_addr, ordering, section_elements, mask_reg, starting_index, writeset_ident)

    async def vloadstore_scalar(
            self, vd: int, addr: int, ordering: Ordering, n_elements: int, mask_reg: int,
            start_index: int, writeset_ident: int, is_store: bool):
        """
        Reads a elements from the scalar memory and send them to the appropriate kamlets where they will update the
        vector register.
        """
        for element_index in range(start_index, start_index+n_elements):
            start_addr_bits = addr + (element_index - start_index) * ordering.ew
            g_addr = GlobalAddress(bit_addr=start_addr_bits, params=self.params)
            scalar_addr = g_addr.to_scalar_addr(self.tlb)
            vw_index = element_index % self.params.j_in_l
            k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                    self.params, ordering.word_order, vw_index)
            wb = self.params.word_bytes
            mask_index = element_index // self.params.j_in_l
            if ordering.ew in (1, 8):
                # We're just sending a byte
                if ordering.ew == 1:
                    bit_mask = 1 << (addr.bit_addr % 8)
                else:
                    bit_mask = (1 << 8) - 1
                if is_store:
                    kinstr = kinstructions.StoreByte(
                        src=vd,
                        bit_mask=bit_mask,
                        mask_reg=mask_reg,
                        mask_index=mask_index,
                        writeset_ident=writeset_ident,
                        )
                else:
                    byte_imm = self.scalar.memory[scalar_addr.addr]
                    kinstr = kinstructions.LoadImmByte(
                        dst=vd,
                        imm=byte_imm,
                        bit_mask=bit_mask,
                        mask_reg=mask_reg,
                        mask_index=mask_index,
                        writeset_ident=writeset_ident,
                        )
            else:
                # We're sending a word
                word_addr = (scalar_addr.addr//wb) * wb
                byte_mask = [0] * wb
                start_byte = element_index//self.params.j_in_l * ordering.ew//8
                if ordering.ew == 1:
                    end_byte = start_byte
                else:
                    end_byte = start_byte + ordering.ew//8 - 1
                for byte_index in range(start_byte, end_byte+1):
                    byte_mask[byte_index] = 1
                bytes_mask_as_int = utils.list_of_uints_to_uint(byte_mask, width=1)
                if is_store:
                    raise NotImplementedError("StoreWord for scalar memory not yet implemented")
                else:
                    word_imm = self.scalar.memory[word_addr: word_addr + wb]
                    kinstr = kinstructions.LoadImmWord(
                        dst=vd,
                        imm=word_imm,
                        byte_mask=byte_mask_as_int,
                        mask_reg=mask_reg,
                        mask_index=mask_index,
                        writeset_ident=writeset_ident,
                        )
            await self.add_to_instruction_buffer(kinstr, k_index=k_index)

    async def vload_scalar_partial(self, vd: int, addr: int, size: int, dst_ordering: Ordering,
                                   mask_reg: int, mask_index: int, element_index: int,
                                   start_byte: int, writeset_ident: int):
        """
        Reads a partial element from the scalar memory and sends it to the appropriate jamlet where it will update a
        vector register.

        start_byte: Which byte in element we starting loading from. 
        size: How many bytes from the element we load.
        """
        assert start_byte + size < self.params.word_bytes
        g_addr = GlobalAddress(bit_addr=addr*8, params=self.params)
        scalar_addr = g_addr.to_scalar_addr(self.tlb)
        vw_index = element_index % self.params.j_in_l
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                self.params, dst_ordering.word_order, vw_index)
        kinstr: kinstructions.KInstr
        if size == 1:
            bit_mask = (1 << 8) - 1
            byte_imm = self.scalar.memory[scalar_addr.addr]
            kinstr = kinstructions.LoadImmByte(
                dst=addresses.RegAddr(vd, start_byte, dst_ordering, self.params),
                imm=byte_imm,
                bit_mask=bit_mask,
                mask_reg=mask_reg,
                mask_index=mask_index,
                writeset_ident=writeset_ident,
                )
        else:
            word_addr = scalar_addr.addr - start_byte
            word_imm = self.scalar.memory[word_addr: word_addr+self.params.word_bytes]
            byte_mask = [0]*self.params.word_bytes
            for byte_index in range(start_byte, start_byte+size):
                byte_mask[byte_index] = 1
            byte_mask = utils.list_of_uints_to_uint(byte_mask, width=1)
            kinstr = kinstructions.LoadImmWord(
                dst=addresses.RegAddr(vd, 0, dst_ordering, self.params),
                imm=word_imm,
                byte_mask=byte_mask,
                mask_reg=mask_reg,
                mask_index=mask_index,
                writeset_ident=writeset_ident,
                )
        await self.add_to_instruction_buffer(kinstr, k_index=k_index)

    #async def vstore(self, vs3: int, addr: int, element_width: SizeBits,
    #                 n_elements: int, mask_reg: int):
    #    g_addr = GlobalAddress(bit_addr=addr*8, params=self.params)
    #    self.check_element_width(g_addr, (n_elements*element_width)//8, element_width)
    #    k_maddr = self.to_k_maddr(g_addr)
    #    n_vlines = element_width * n_elements//(self.params.maxvl_bytes * 8)
    #    for reg in range(vs3, vs3+n_vlines):
    #        assert self.vrf_ordering[reg] == Ordering(word_order=addresses.WordOrder.STANDARD, ew=element_width)
    #    kinstr = kinstructions.Store(
    #        src=vs3,
    #        k_maddr=k_maddr,
    #        n_elements=n_elements,
    #        element_width=element_width,
    #        word_order=k_maddr.ordering.word_order,
    #        mask_reg=mask_reg,
    #        )
    #    await self.add_to_instruction_buffer(kinstr)

    def check_element_width(self, addr: GlobalAddress, size: int, element_width: int):
        """
        Check that this region of memory all has this element width
        """
        # Split the load into a continous load for each cache line
        base_addr = addr.addr
        for offset in range(0, size, self.params.page_bytes):
            page_address = ((base_addr+offset)//self.params.page_bytes) * self.params.page_bytes
            page_info = self.tlb.get_page_info(GlobalAddress(bit_addr=page_address*8, params=self.params))
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
        for channel in range(self.params.n_channels):
            self.clock.create_task(self.router_connections(channel))
        self.clock.create_task(self.monitor_replys())
        self.clock.create_task(self.monitor_instruction_buffer())

    async def run_instruction(self, disasm_trace=None):
        logger.debug(f'{self.clock.cycle}: run_instruction: fetching at pc={hex(self.pc)}')
        first_bytes = await self.get_memory_blocking(self.pc, 2)
        logger.debug(f'{self.clock.cycle}: run_instruction: got first_bytes={first_bytes.hex()}')
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
            error = dt.check_instruction(disasm_trace, self.pc, inst_hex, inst_str)
            if error:
                logger.error(error)
                raise ValueError(error)

        await instruction.update_state(self)

    async def run_instructions(self, disasm_trace=None):
        while not self.finished:

            await self.clock.next_cycle
            logger.debug(f'{self.clock.cycle}: run_instructions: about to run first instruction')
            await self.run_instruction(disasm_trace)
            logger.debug(f'{self.clock.cycle}: run_instructions: about to run second instruction')
            await self.run_instruction(disasm_trace)

    async def handle_vreduction_vs_instr(self, op, dst, src_vector, src_scalar_reg, mask_reg,
                                         n_elements, element_width, word_order):
        """Handle vector reduction instruction.

        Creates and sends a VreductionVsOp instruction to kamlet.
        TODO: Implement this method.
        """
        raise NotImplementedError("handle_vreduction_vs_instr not yet implemented")

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

