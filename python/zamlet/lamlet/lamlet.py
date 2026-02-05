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
from typing import List, Deque, Any

from zamlet import decode
from zamlet import addresses
from zamlet.addresses import SizeBytes, SizeBits, TLB, WordOrder, MemoryType
from zamlet.addresses import AddressConverter, Ordering, GlobalAddress, KMAddr, VPUAddress
from zamlet.kamlet.cache_table import (
    CacheTable, CacheState, ProtocolState, SendState)
from zamlet.lamlet.lamlet_waiting_item import (
    LamletWaitingItem, LamletWaitingFuture,
    LamletWaitingLoadIndexedElement, LamletWaitingStoreIndexedElement)
from zamlet.monitor import CompletionType, SpanType
from zamlet.params import LamletParams
from zamlet.message import (Header, MessageType, Direction, SendType, TaggedHeader,
                            WriteMemWordHeader, CHANNEL_MAPPING, IdentHeader,
                            ElementIndexHeader, ReadMemWordHeader)
from zamlet.kamlet.kamlet import Kamlet
from zamlet.memlet import Memlet
from zamlet.runner import Future
from zamlet.kamlet import kinstructions
from zamlet.transactions.load_stride import LoadStride
from zamlet.transactions.store_stride import StoreStride
from zamlet.transactions.load_indexed_unordered import LoadIndexedUnordered
from zamlet.transactions.store_indexed_unordered import StoreIndexedUnordered
from zamlet.transactions.ident_query import IdentQuery
from zamlet.transactions.load_indexed_element import LoadIndexedElement
from zamlet.transactions.store_indexed_element import StoreIndexedElement
from zamlet.transactions.write_imm_bytes import WriteImmBytes
from zamlet.transactions.read_byte import ReadByte
from zamlet.lamlet.scalar import ScalarState
from zamlet.lamlet.ordered_buffer import OrderedBuffer, ElementEntry, ElementState
from zamlet import utils
import zamlet.disasm_trace as dt
from zamlet.synchronization import SyncDirection, Synchronizer
from zamlet.monitor import Monitor, CompletionType, ResourceType
from zamlet.lamlet import ident_query
from zamlet.lamlet.ident_query import RefreshState
from zamlet.lamlet import ordered
from zamlet.lamlet import unordered
from zamlet.lamlet import vregister


logger = logging.getLogger(__name__)


class Lamlet:

    def __init__(self, clock, params: LamletParams):
        self.clock = clock
        self.params = params
        self.monitor = Monitor(clock, params)
        # Create a span for setup/initialization phase
        self._setup_span_id = self.monitor.create_span(
            span_type=SpanType.SETUP,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
        )
        # Create a span for ident query flow control
        self._ident_query_span_id = self.monitor.create_span(
            span_type=SpanType.FLOW_CONTROL,
            component="lamlet",
            completion_type=CompletionType.TRACKED,
        )
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
                tlb=self.tlb,
                monitor=self.monitor,
                lamlet_x=self.instr_x,
                lamlet_y=self.instr_y,
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
                monitor=self.monitor,
                ))
        # A dictionary that maps labels to futures
        # Used for handling responses back from the kamlet grid.
        #self.tracker = ResponseTracker(self.clock, self.params)
        self.conv = AddressConverter(self.params, self.tlb)
        self.finished = False

        # These are actions that are waiting on a cache state to update, or for messages to be received.
        # FIFO ordering - oldest items first for priority processing.
        self.waiting_items: deque[LamletWaitingItem] = deque()

        self.next_writeset_ident = 0
        self.next_instr_ident = 0
        # Track oldest active instr_ident for flow control (None = unknown/all free)
        self._oldest_active_ident: int | None = None
        # Ident query state machine
        self._ident_query_state = RefreshState.DORMANT
        self._ident_query_ident = params.max_response_tags  # Dedicated ident for queries
        # Dedicated idents for ordered barrier instructions (one per ordered buffer slot)
        self._ordered_barrier_idents = [
            params.max_response_tags + 1 + i for i in range(params.n_ordered_buffers)]
        self._ident_query_baseline = 0
        # Track last instr_ident sent to kamlets (for IdentQuery.previous_instr_ident)
        # Initialize to max_response_tags - 2 so first query reports max_response_tags - 1 as oldest
        self._last_sent_instr_ident: int = params.max_response_tags - 2

        # Per-kamlet instruction queue token tracking
        # Available tokens = how many instructions we can send to this kamlet
        self._available_tokens = [params.instruction_queue_length for _ in range(params.k_in_l)]
        # Tokens used since we sent the last ident query (will be returned by NEXT query)
        self._tokens_used_since_query = [0 for _ in range(params.k_in_l)]
        # Tokens that will be returned when the current in-flight query responds
        self._tokens_in_active_query = [0 for _ in range(params.k_in_l)]

        # Send queues for packets going into the router network from the lamlet
        # Separate queue per message type for deterministic ordering
        self._send_queues = {
            # Channel 0 (responses)
            MessageType.INSTRUCTIONS: utils.Queue(length=2),
            MessageType.READ_MEM_WORD_RESP: utils.Queue(length=2),
            MessageType.WRITE_MEM_WORD_RESP: utils.Queue(length=2),
            # Channel 1 (requests)
            MessageType.WRITE_MEM_WORD_REQ: utils.Queue(length=2),
        }

        # Lamlet's synchronizer at position (0, -1), connected to kamlet (0,0)
        self.synchronizer = Synchronizer(
            clock=clock,
            params=params,
            x=self.instr_x,
            y=self.instr_y,
            cache_table=None,  # Lamlet manages its own waiting items
            monitor=self.monitor,
        )

        # Ordered indexed operation buffers, indexed by buffer_id (0 to n_ordered_buffers-1)
        self._ordered_buffers: list[OrderedBuffer | None] = [
            None for _ in range(self.params.n_ordered_buffers)]

    def has_free_witem_slot(self) -> bool:
        """Check if there's room for another waiting item."""
        return len(self.waiting_items) < self.params.n_items

    async def add_witem(self, witem: LamletWaitingItem) -> None:
        """Add a waiting item to the deque, waiting if necessary."""
        while not self.has_free_witem_slot():
            await self.clock.next_cycle
        self.waiting_items.append(witem)

    def get_witem_by_ident(self, instr_ident: int) -> LamletWaitingItem | None:
        """Find a waiting item by its instr_ident. Raises if duplicates found."""
        matches = [item for item in self.waiting_items if item.instr_ident == instr_ident]
        if len(matches) > 1:
            raise ValueError(f"Multiple waiting items with instr_ident {instr_ident}")
        return matches[0] if matches else None

    def remove_witem_by_ident(self, instr_ident: int):
        """Remove a waiting item by its instr_ident."""
        for item in list(self.waiting_items):
            if item.instr_ident == instr_ident:
                self.waiting_items.remove(item)
                return
        raise ValueError(f"No waiting item with instr_ident {instr_ident}")

    async def get_instr_ident(self, n_idents: int = 1) -> int:
        """Allocate n_idents consecutive instruction identifiers."""
        return await ident_query.get_instr_ident(self, n_idents)

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

    def allocate_memory(self, address: GlobalAddress, size: SizeBytes, memory_type: MemoryType,
                        ordering: Ordering | None, readable: bool = True, writable: bool = True):
        assert size % self.params.page_bytes == 0
        self.tlb.allocate_memory(address, size, memory_type, ordering, readable, writable)
        # Register non-idempotent pages with ScalarState
        if memory_type == MemoryType.SCALAR_NON_IDEMPOTENT:
            for page_offset in range(0, size, self.params.page_bytes):
                page_addr = address.addr + page_offset
                page_info = self.tlb.get_page_info(GlobalAddress(bit_addr=page_addr*8, params=self.params))
                self.scalar.register_non_idempotent_page(page_info.local_address.addr)

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
        instr_ident = await ident_query.get_instr_ident(self)
        kinstr = WriteImmBytes(
            k_maddr=k_maddr,
            imm=value,
            instr_ident=instr_ident,
            )
        await self.add_to_instruction_buffer(kinstr, self._setup_span_id, k_maddr.k_index)

    async def read_byte(self, address: GlobalAddress):
        """
        This blocks until the cache is ready an the instruction is received.
        It returns a future that resolves when the value is returned.
        """
        k_maddr = address.to_k_maddr(self.tlb)
        j_in_k_index = (k_maddr.addr//self.params.word_bytes) % self.params.j_in_k
        logger.debug(f'{self.clock.cycle}: lamlet: Lamlet.read_bytes {hex(address.addr)} k_maddr {k_maddr} j_in_k {j_in_k_index}')
        instr_ident = await ident_query.get_instr_ident(self)
        future = self.clock.create_future()
        witem = LamletWaitingFuture(future=future, instr_ident=instr_ident)
        await self.add_witem(witem)
        kinstr = ReadByte(
            k_maddr=k_maddr,
            instr_ident=instr_ident,
            )
        await self.add_to_instruction_buffer(kinstr, self._setup_span_id, k_maddr.k_index)
        return future

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
                        if conn.age > 500 and conn.age % 50 == 0:
                            logger.warning(
                                f"Router ({x}, {y}) connection stuck for {conn.age} cycles")
                    north = (x, y-1)
                    south = (x, y+1)
                    east = (x+1, y)
                    west = (x-1, y)
                    # Track present/moving for each direction
                    north_present = bool(router._output_buffers[Direction.N])
                    south_present = bool(router._output_buffers[Direction.S])
                    east_present = bool(router._output_buffers[Direction.E])
                    west_present = bool(router._output_buffers[Direction.W])
                    h_present = bool(router._output_buffers[Direction.H])
                    north_moving = False
                    south_moving = False
                    east_moving = False
                    west_moving = False
                    h_moving = False

                    if north in routers:
                        # Send to the north
                        north_buffer = router._output_buffers[Direction.N]
                        if north_buffer:
                            north_router = routers[north]
                            if north_router.has_input_room(Direction.S):
                                word = north_buffer.popleft()
                                north_router.receive(Direction.S, word)
                                north_moving = True
                                logger.debug(f'{self.clock.cycle}: Moving word north ({x}, {y}) -> ({x}, {y-1}) {word}')
                    if south in routers:
                        # Send to the south
                        south_buffer = router._output_buffers[Direction.S]
                        if south_buffer:
                            south_router = routers[south]
                            if south_router.has_input_room(Direction.N):
                                word = south_buffer.popleft()
                                south_router.receive(Direction.N, word)
                                south_moving = True
                                logger.debug(f'{self.clock.cycle}: Moving word south, ({x}, {y}) -> ({x}, {y+1}) {word}')
                    if east in routers:
                        # Send to the east
                        east_buffer = router._output_buffers[Direction.E]
                        if east_buffer:
                            east_router = routers[east]
                            if east_router.has_input_room(Direction.W):
                                word = east_buffer.popleft()
                                east_router.receive(Direction.W, word)
                                east_moving = True
                                logger.debug(f'{self.clock.cycle}: Moving word east, ({x}, {y}) -> ({x+1}, {y}) {word}')
                    if west in routers:
                        # Send to the west
                        west_buffer = router._output_buffers[Direction.W]
                        if west_buffer:
                            west_router = routers[west]
                            if west_router.has_input_room(Direction.E):
                                word = west_buffer.popleft()
                                west_router.receive(Direction.E, word)
                                west_moving = True
                                logger.debug(f'{self.clock.cycle}: Moving word west, ({x}, {y}) -> ({x-1}, {y}) {word}')

                    # Report router output state for all directions
                    self.monitor.report_router_output(x, y, channel, Direction.N,
                                                      north_present, north_moving)
                    self.monitor.report_router_output(x, y, channel, Direction.S,
                                                      south_present, south_moving)
                    self.monitor.report_router_output(x, y, channel, Direction.E,
                                                      east_present, east_moving)
                    self.monitor.report_router_output(x, y, channel, Direction.W,
                                                      west_present, west_moving)
                    self.monitor.report_router_output(x, y, channel, Direction.H,
                                                      h_present, h_moving)

    async def sync_network_connections(self):
        """
        Move bytes between synchronizers in adjacent kamlets (and the lamlet).
        This is a separate network from the main router network.
        Synchronizers connect to all 8 neighbors (N, S, E, W, NE, NW, SE, SW).
        The lamlet's synchronizer is at (0, -1) and connects to kamlet (0,0) and (1,0).
        """
        # Build a map of (k_x, k_y) -> synchronizer
        synchronizers = {}
        for kamlet in self.kamlets:
            k_x = kamlet.min_x // self.params.j_cols
            k_y = kamlet.min_y // self.params.j_rows
            synchronizers[(k_x, k_y)] = kamlet.synchronizer

        # Add lamlet's synchronizer at (0, -1)
        synchronizers[(0, -1)] = self.synchronizer

        # Direction deltas for all 8 directions
        direction_deltas = {
            SyncDirection.N: (0, -1),
            SyncDirection.S: (0, 1),
            SyncDirection.E: (1, 0),
            SyncDirection.W: (-1, 0),
            SyncDirection.NE: (1, -1),
            SyncDirection.NW: (-1, -1),
            SyncDirection.SE: (1, 1),
            SyncDirection.SW: (-1, 1),
        }

        # Opposite directions for receiving
        opposite_direction = {
            SyncDirection.N: SyncDirection.S,
            SyncDirection.S: SyncDirection.N,
            SyncDirection.E: SyncDirection.W,
            SyncDirection.W: SyncDirection.E,
            SyncDirection.NE: SyncDirection.SW,
            SyncDirection.SW: SyncDirection.NE,
            SyncDirection.NW: SyncDirection.SE,
            SyncDirection.SE: SyncDirection.NW,
        }

        while True:
            await self.clock.next_cycle

            # Update all synchronizer buffers
            for sync in synchronizers.values():
                sync.update()

            # Move bytes between synchronizers
            for (x, y), sync in synchronizers.items():
                for direction in SyncDirection:
                    if sync.has_output(direction):
                        dx, dy = direction_deltas[direction]
                        neighbor_coords = (x + dx, y + dy)
                        if neighbor_coords in synchronizers:
                            neighbor = synchronizers[neighbor_coords]
                            recv_dir = opposite_direction[direction]
                            if neighbor.can_receive(recv_dir):
                                byte_val = sync.get_output(direction)
                                if byte_val is not None:
                                    neighbor.receive(recv_dir, byte_val)

    async def monitor_channel0(self):
        """Handle channel 0 packets (responses that must be consumed immediately)."""
        buffer = self.kamlets[0].jamlets[0].routers[0]._output_buffers[Direction.N]
        header = None
        packet = []
        while True:
            await self.clock.next_cycle
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
                    self._process_channel0_packet(packet)
                    header = None
                    packet = []

    def _process_channel0_packet(self, packet):
        """Process a channel 0 packet (responses). These never need to send."""
        header = packet[0]
        assert isinstance(header, Header)
        assert header.length == len(packet)

        # Get message span_id before completing it (completing may trigger parent auto-complete)
        message_span_id = self.monitor.get_message_span_id_by_header(header)

        # Record message received for all channel 0 responses
        self.monitor.record_message_received_by_header(
            header, dst_x=self.instr_x, dst_y=self.instr_y)

        if header.message_type == MessageType.READ_BYTE_RESP:
            assert len(packet) == 1
            item = self.get_witem_by_ident(header.ident)
            assert item is not None, f"No waiting item for ident {header.ident}"
            assert isinstance(item, LamletWaitingFuture)
            item.future.set_result(header.value)
            self.remove_witem_by_ident(header.ident)
            self.monitor.complete_kinstr(header.ident)
            logger.debug(f'{self.clock.cycle}: lamlet: Got a READ_BYTE_RESP from ({header.source_x, header.source_y}) is {header.value}')
        elif header.message_type == MessageType.READ_WORDS_RESP:
            item = self.get_witem_by_ident(header.ident)
            assert item is not None, f"No waiting item for ident {header.ident}"
            assert isinstance(item, LamletWaitingFuture)
            item.future.set_result(packet[1:])
            self.remove_witem_by_ident(header.ident)
            self.monitor.complete_kinstr(header.ident)
            logger.debug(f'{self.clock.cycle}: lamlet: Got a READ_WORDS_RESP from ({header.source_x, header.source_y}) is {packet[1:]}')
        elif header.message_type == MessageType.IDENT_QUERY_RESP:
            # Get kinstr span_id from message span (message already completed above,
            # which may have auto-completed the kinstr and removed it from lookup)
            message_span = self.monitor.get_span(message_span_id)
            kinstr_span_id = message_span.parent.span_id if message_span.parent else None
            assert len(packet) == 2, f"packet len {len(packet)}"
            assert header.ident == self._ident_query_ident
            min_distance = int.from_bytes(packet[1], byteorder='little')
            ident_query.receive_ident_query_response(self, min_distance, kinstr_span_id)
        elif header.message_type == MessageType.LOAD_INDEXED_ELEMENT_RESP:
            assert len(packet) == 1
            assert isinstance(header, ElementIndexHeader)
            ordered.handle_load_indexed_element_resp(self, header)
        elif header.message_type == MessageType.STORE_INDEXED_ELEMENT_RESP:
            assert isinstance(header, ElementIndexHeader)
            if header.masked or header.fault:
                assert len(packet) == 1
                ordered.handle_store_indexed_element_resp(self, header, None, None)
            else:
                assert len(packet) == 3
                addr = packet[1]
                data = packet[2]
                ordered.handle_store_indexed_element_resp(self, header, addr, data)
        elif header.message_type == MessageType.WRITE_MEM_WORD_RESP:
            assert len(packet) == 1
            ordered.handle_ordered_write_mem_word_resp(self, header)
        elif header.message_type == MessageType.WRITE_MEM_WORD_DROP:
            assert len(packet) == 1
            ordered.handle_ordered_write_mem_word_drop(self, header)
        elif header.message_type == MessageType.WRITE_MEM_WORD_RETRY:
            assert len(packet) == 1
            ordered.handle_ordered_write_mem_word_retry(self, header)
        else:
            raise NotImplementedError(f"Unexpected channel 0 message: {header.message_type}")

    async def monitor_channel1andup(self):
        """Handle channel 1+ packets (requests that may need to send responses)."""
        while True:
            await self.clock.next_cycle
            for channel in range(1, self.params.n_channels):
                buffer = self.kamlets[0].jamlets[0].routers[channel]._output_buffers[Direction.N]
                if buffer:
                    packet = await self._receive_packet(buffer)
                    await self._process_channel1andup_packet(packet)

    async def _receive_packet(self, buffer):
        """Receive a complete packet from a buffer."""
        while not buffer:
            await self.clock.next_cycle
        header = buffer.popleft()
        assert isinstance(header, Header)
        packet = [header]
        remaining_words = header.length - 1
        while remaining_words > 0:
            await self.clock.next_cycle
            if buffer:
                word = buffer.popleft()
                packet.append(word)
                remaining_words -= 1
        return packet

    async def _process_channel1andup_packet(self, packet):
        """Process a channel 1+ packet (requests). These may need to send responses."""
        header = packet[0]
        assert isinstance(header, IdentHeader)
        assert header.length == len(packet)

        # All channel 1+ messages to lamlet have a tag
        assert hasattr(header, 'tag'), f"Header {type(header).__name__} missing tag attribute"
        self.monitor.record_message_received_by_header(header, 0, -1)

        if header.message_type == MessageType.READ_MEM_WORD_REQ:
            assert isinstance(header, ReadMemWordHeader)
            scalar_addr = packet[1]
            assert isinstance(scalar_addr, int)
            if header.ordered:
                ordered.handle_read_mem_word_req_ordered(self, header, scalar_addr)
            else:
                await unordered.handle_read_mem_word_req(self, header, scalar_addr)
        elif header.message_type == MessageType.WRITE_MEM_WORD_REQ:
            assert isinstance(header, WriteMemWordHeader)
            scalar_addr = packet[1]
            src_word = packet[2]
            assert isinstance(scalar_addr, int), f"Expected int, got {type(scalar_addr)}: {scalar_addr}"
            assert isinstance(src_word, (bytes, bytearray)), \
                f"Expected bytes/bytearray, got {type(src_word)}: {src_word}"
            await unordered.handle_write_mem_word_req(self, header, scalar_addr, src_word)
        else:
            raise NotImplementedError(f"Unexpected channel 1+ message: {header.message_type}")

    async def add_to_instruction_buffer(self, instruction, parent_span_id: int, k_index=None):
        logger.debug(f'{self.clock.cycle}: lamlet: Adding {type(instruction)} to buffer')
        self.monitor.record_kinstr_created(instruction, parent_span_id)
        while len(self.instruction_buffer) >= self.params.instruction_buffer_length:
            await self.clock.next_cycle
        self.instruction_buffer.append((instruction, k_index))

    def _have_tokens(self, k_index: int | None, is_ident_query: bool = False) -> bool:
        """Check if we have tokens available for the given k_index (or all if None).

        Regular instructions need > 1 token (last token reserved for IdentQuery).
        IdentQuery only needs > 0 tokens.
        """
        min_tokens = 0 if is_ident_query else 1
        if k_index is None:
            return all(t > min_tokens for t in self._available_tokens)
        else:
            return self._available_tokens[k_index] > min_tokens

    def _use_token(self, k_index: int | None):
        """Use a token for the given k_index (or all if None for broadcast)."""
        if k_index is None:
            for i in range(self.params.k_in_l):
                assert self._available_tokens[i] > 0
                self._available_tokens[i] -= 1
                self._tokens_used_since_query[i] += 1
            logger.debug(f'{self.clock.cycle}: lamlet: _use_token broadcast, '
                        f'available={self._available_tokens}')
        else:
            assert self._available_tokens[k_index] > 0
            self._available_tokens[k_index] -= 1
            self._tokens_used_since_query[k_index] += 1
            logger.debug(f'{self.clock.cycle}: lamlet: _use_token k={k_index}, '
                        f'available={self._available_tokens}')

    def _should_send_ident_query_for_tokens(self) -> bool:
        """Check if we should send an ident query to reclaim tokens."""
        # Send query if any kamlet has less than half its tokens available
        # and we're not already waiting for a response
        if self._ident_query_state != RefreshState.DORMANT:
            return False
        threshold = self.params.instruction_queue_length // 2
        return any(t < threshold for t in self._available_tokens)

    async def monitor_instruction_buffer(self):
        inactive_count = 0
        old_length = 0
        while True:
            # Check if we need to send an ident query to reclaim tokens
            if self._should_send_ident_query_for_tokens():
                self._ident_query_state = RefreshState.READY_TO_SEND

            instructions = []
            send_k_index = None

            if self.instruction_buffer:
                k_indices = [x[1] for x in self.instruction_buffer]
                k_indices_same = all(k_indices[0] == x for x in k_indices)
                should_send = (len(self.instruction_buffer) >= self.params.instructions_in_packet or
                               (not k_indices_same) or inactive_count > 2)

                if should_send and self._have_tokens(k_indices[0]):
                    send_k_index = k_indices[0]
                    while self.instruction_buffer:
                        instr, instr_k_index = self.instruction_buffer[0]
                        if instr_k_index != send_k_index:
                            break
                        if not self._have_tokens(instr_k_index):
                            self.monitor.record_resource_exhausted(
                                ResourceType.INSTR_BUFFER_TOKENS, None, None)
                            break
                        self.instruction_buffer.popleft()
                        span_id = self.monitor.get_kinstr_span_id(instr.instr_ident)
                        self.monitor.add_event(span_id, "dispatched")
                        instructions.append(instr)
                        self._use_token(instr_k_index)
                        # Mark the corresponding lamlet waiting item as dispatched
                        witem = self.get_witem_by_ident(instr.instr_ident)
                        if witem is not None:
                            assert isinstance(witem, LamletWaitingItem)
                            witem.dispatched = True
                    old_length = 0
                    inactive_count = 0
                else:
                    new_length = len(self.instruction_buffer)
                    if new_length == old_length:
                        inactive_count += 1
                    else:
                        inactive_count = 0
                    old_length = new_length

            # Insert IdentQuery if pending - the reserved token must be available.
            # This is guaranteed because: (1) regular instructions can't use the last token,
            # (2) IdentQuery uses the reserved token and moves to WAITING_FOR_RESPONSE,
            # (3) the response returns tokens (including the one used by IdentQuery),
            # (4) only then does it return to READY_TO_SEND.
            if self._ident_query_state == RefreshState.READY_TO_SEND:
                assert self._have_tokens(None, is_ident_query=True)
                iq_kinstr = ident_query.create_ident_query(self)
                iq_span_id = self.monitor.get_kinstr_span_id(iq_kinstr.instr_ident)
                self.monitor.add_event(iq_span_id, "dispatched")
                self._use_token(None)
                # Move tokens to active query tracker (will be returned when response arrives)
                for i in range(self.params.k_in_l):
                    self._tokens_in_active_query[i] = self._tokens_used_since_query[i]
                    self._tokens_used_since_query[i] = 0
                # Add to broadcast packet, or send separately if packet is single-kamlet
                if send_k_index is None:
                    instructions.append(iq_kinstr)
                else:
                    if instructions:
                        await self.send_instructions(instructions, send_k_index)
                    instructions = [iq_kinstr]
                    send_k_index = None

            if instructions:
                await self.send_instructions(instructions, send_k_index)

            await self.clock.next_cycle

    async def send_instructions(self, instructions, k_index=None):
        '''
        Send instructions.
        If k_index=None then we broadcast to all the kamlets in this
        lamlet.
        '''
        logger.debug(f'{self.clock.cycle}: Sending instructions {instructions}')
        # Track last instr_ident sent (for IdentQuery.previous_instr_ident)
        for instr in instructions:
            if instr.instr_ident is not None and instr.instr_ident < self.params.max_response_tags:
                self._last_sent_instr_ident = instr.instr_ident
        is_broadcast = k_index is None
        if is_broadcast:
            send_type = SendType.BROADCAST
            x = self.params.k_cols * self.params.j_cols - 1
            y = self.params.k_rows * self.params.j_rows - 1
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
        logger.debug(f'Sending instructions to {k_index} ({send_type.name}), -> ({x}, {y})')
        # Create kinstr_exec items for each kamlet that receives the instruction
        for instr in instructions:
            assert instr.instr_ident is not None
            if is_broadcast:
                for kamlet in self.kamlets:
                    self.monitor.record_kinstr_exec_created(
                        instr, kamlet.min_x, kamlet.min_y)
                    kinstr_exec_span_id = self.monitor.get_kinstr_exec_span_id(
                        instr.instr_ident, kamlet.min_x, kamlet.min_y)
                    # Record message only for kamlet's origin jamlet
                    self.monitor.record_message_sent(
                        kinstr_exec_span_id, 'INSTRUCTION',
                        instr.instr_ident, None,
                        self.instr_x, self.instr_y,
                        kamlet.min_x, kamlet.min_y)
            else:
                kamlet = self.kamlets[k_index]
                self.monitor.record_kinstr_exec_created(
                    instr, kamlet.min_x, kamlet.min_y)
                kinstr_exec_span_id = self.monitor.get_kinstr_exec_span_id(
                    instr.instr_ident, kamlet.min_x, kamlet.min_y)
                self.monitor.record_message_sent(
                    kinstr_exec_span_id, 'INSTRUCTION',
                    instr.instr_ident, None,
                    self.instr_x, self.instr_y,
                    kamlet.min_x, kamlet.min_y)
            # Finalize kinstr children if FIRE_AND_FORGET and finalize_after_send
            if instr.finalize_after_send:
                kinstr_span_id = self.monitor.get_kinstr_span_id(instr.instr_ident)
                kinstr_item = self.monitor.get_span(kinstr_span_id)
                if kinstr_item.completion_type == CompletionType.FIRE_AND_FORGET:
                    self.monitor.finalize_children(kinstr_span_id)
        await self.send_packet(packet, jamlet, Direction.N, port=0)

    async def send_packet(self, packet, jamlet, direction, port,
                          parent_span_id: int | None = None):
        """Queue a packet for sending.

        parent_span_id is required for non-INSTRUCTION messages. For INSTRUCTIONS,
        message recording is handled separately due to broadcast complexity.
        """
        header = packet[0]
        message_type = header.message_type
        assert port == 0
        assert direction == Direction.N

        if message_type == MessageType.INSTRUCTIONS:
            assert parent_span_id is None
        else:
            assert parent_span_id is not None
            tag = header.tag if hasattr(header, 'tag') else None
            self.monitor.record_message_sent(
                parent_span_id, message_type.name,
                ident=header.ident, tag=tag,
                src_x=self.instr_x, src_y=self.instr_y,
                dst_x=header.target_x, dst_y=header.target_y,
            )

        send_queue = self._send_queues[message_type]
        while not send_queue.can_append():
            await self.clock.next_cycle
        send_queue.append(packet)

    async def _send_packets_ch0(self):
        """Drain the channel 0 send queues and inject packets into the router network."""
        jamlet = self.kamlets[0].jamlets[0]
        router_queue = jamlet.routers[0]._input_buffers[Direction.N]
        while True:
            sent_something = False
            for msg_type, send_queue in self._send_queues.items():
                if CHANNEL_MAPPING.get(msg_type, 0) == 0 and send_queue:
                    packet = send_queue.popleft()
                    await self._send_packet_words(packet, router_queue)
                    sent_something = True
            if not sent_something:
                await self.clock.next_cycle

    async def _send_packets_ch1andup(self):
        """Drain channel 1+ send queues and inject packets into the router network."""
        jamlet = self.kamlets[0].jamlets[0]
        while True:
            sent_something = False
            for msg_type, send_queue in self._send_queues.items():
                channel = CHANNEL_MAPPING.get(msg_type, 0)
                if channel >= 1 and send_queue:
                    router_queue = jamlet.routers[channel]._input_buffers[Direction.N]
                    packet = send_queue.popleft()
                    await self._send_packet_words(packet, router_queue)
                    sent_something = True
            if not sent_something:
                await self.clock.next_cycle

    async def _send_packet_words(self, packet, router_queue):
        """Send all words of a packet into the router queue, one per cycle."""
        while packet:
            await self.clock.next_cycle
            if router_queue.can_append():
                word = packet.pop(0)
                router_queue.append(word)

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
                self.scalar.set_memory(scalar_address, bytes([b]))

    def directly_set_memory(self, address: int, data: bytes):
        """
        Write bytes directly to memory, bypassing simulation.

        WARNING: This is for test initialization only. It does not accurately model
        how the hardware would work - it bypasses cache coherency, message passing,
        and timing. Use only for setting up initial test state.

        For VPU memory, writes directly to the memlet's backing memory.
        For scalar memory, writes directly to scalar state.
        """
        for index, b in enumerate(data):
            byte_addr = GlobalAddress(bit_addr=(address + index) * 8, params=self.params)
            if byte_addr.is_vpu(self.tlb):
                k_maddr = byte_addr.to_k_maddr(self.tlb)
                memlet = self.memlets[k_maddr.k_index]
                cache_line_index = k_maddr.addr // self.params.cache_line_bytes
                offset_in_line = k_maddr.addr % self.params.cache_line_bytes

                # Get or create cache line
                if cache_line_index not in memlet.lines:
                    memlet.lines[cache_line_index] = bytearray(self.params.cache_line_bytes)
                elif isinstance(memlet.lines[cache_line_index], bytes):
                    memlet.lines[cache_line_index] = bytearray(memlet.lines[cache_line_index])

                memlet.lines[cache_line_index][offset_in_line] = b
            else:
                scalar_address = self.to_scalar_addr(byte_addr)
                self.scalar.set_memory(scalar_address, bytes([b]))

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
        page_bytes = self.params.page_bytes
        page_offset = address % page_bytes
        if page_offset + size > page_bytes:
            # We need to do two reads. One in each page.
            first_size = page_bytes - page_offset
            second_size = size - first_size
            first_future = await self.get_memory(address, first_size)
            second_future = await self.get_memory(address + first_size, second_size)
            await first_future
            await second_future
            combined = first_future.result() + second_future.result()
            result_future = self.clock.create_future()
            result_future.set_result(combined)
        else:
            start_addr = GlobalAddress(bit_addr=address*8, params=self.params)
            is_vpu = start_addr.is_vpu(self.tlb)
            if is_vpu:
                read_futures = [await self.read_byte(GlobalAddress(bit_addr=(start_addr.addr+offset)*8, params=self.params))
                                for offset in range(size)]
                read_future = self.clock.create_future()
                self.clock.create_task(self.combine_read_futures(read_future, read_futures))
            else:
                local_address = start_addr.to_scalar_addr(self.tlb)
                data = self.scalar.get_memory(local_address, size=size)
                read_future = self.clock.create_future()
                read_future.set_result(data)
            result_future = read_future
        return result_future

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

    async def vload(self, vd: int, addr: int, ordering: addresses.Ordering,
                    n_elements: int, mask_reg: int | None, start_index: int,
                    parent_span_id: int,
                    reg_ordering: addresses.Ordering | None = None,
                    stride_bytes: int | None = None) -> addresses.VectorOpResult:
        return await unordered.vload(self, vd, addr, ordering, n_elements, mask_reg, start_index,
                                     parent_span_id, reg_ordering, stride_bytes)

    async def vstore(self, vs: int, addr: int, ordering: addresses.Ordering,
                     n_elements: int, mask_reg: int | None, start_index: int,
                     parent_span_id: int,
                     stride_bytes: int | None = None) -> addresses.VectorOpResult:
        return await unordered.vstore(self, vs, addr, ordering, n_elements, mask_reg, start_index,
                                      parent_span_id, stride_bytes)

    async def vload_indexed_unordered(self, vd: int, base_addr: int, index_reg: int,
                                       index_ew: int, data_ew: int, n_elements: int,
                                       mask_reg: int | None, start_index: int,
                                       parent_span_id: int) -> addresses.VectorOpResult:
        return await unordered.vload_indexed_unordered(self, vd, base_addr, index_reg, index_ew,
                                                       data_ew, n_elements, mask_reg, start_index,
                                                       parent_span_id)

    async def vstore_indexed_unordered(self, vs: int, base_addr: int, index_reg: int,
                                        index_ew: int, data_ew: int, n_elements: int,
                                        mask_reg: int | None, start_index: int,
                                        parent_span_id: int) -> addresses.VectorOpResult:
        return await unordered.vstore_indexed_unordered(self, vs, base_addr, index_reg, index_ew,
                                                        data_ew, n_elements, mask_reg, start_index,
                                                        parent_span_id)

    async def vload_indexed_ordered(self, vd: int, base_addr: int, index_reg: int,
                                    index_ew: int, data_ew: int, n_elements: int,
                                    mask_reg: int | None, start_index: int,
                                    parent_span_id: int) -> addresses.VectorOpResult:
        return await ordered.vload_indexed_ordered(self, vd, base_addr, index_reg, index_ew,
                                                   data_ew, n_elements, mask_reg, start_index,
                                                   parent_span_id)

    async def vstore_indexed_ordered(self, vs: int, base_addr: int, index_reg: int,
                                     index_ew: int, data_ew: int, n_elements: int,
                                     mask_reg: int | None, start_index: int,
                                     parent_span_id: int) -> addresses.VectorOpResult:
        return await ordered.vstore_indexed_ordered(self, vs, base_addr, index_reg, index_ew,
                                                    data_ew, n_elements, mask_reg, start_index,
                                                    parent_span_id)

    async def vrgather(self, vd: int, vs2: int, vs1: int,
                       start_index: int, n_elements: int,
                       index_ew: int, data_ew: int,
                       word_order: addresses.WordOrder, vlmax: int,
                       mask_reg: int | None, parent_span_id: int) -> int:
        """Execute vrgather. Returns sync_ident that can be awaited if needed."""
        return await vregister.vrgather(self, vd, vs2, vs1, start_index, n_elements,
                                        index_ew, data_ew, word_order, vlmax,
                                        mask_reg, parent_span_id)

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
        for queue in self._send_queues.values():
            queue.update()

    async def run(self):
        for kamlet in self.kamlets:
            self.clock.create_task(kamlet.run())
        for memlet in self.memlets:
            self.clock.create_task(memlet.run())
        for channel in range(self.params.n_channels):
            self.clock.create_task(self.router_connections(channel))
        self.clock.create_task(self.sync_network_connections())
        self.clock.create_task(self.synchronizer.run())
        self.clock.create_task(self.monitor_channel0())
        self.clock.create_task(self.monitor_channel1andup())
        self.clock.create_task(self.monitor_instruction_buffer())
        self.clock.create_task(ident_query.monitor_ident_query(self))
        self.clock.create_task(self._send_packets_ch0())
        self.clock.create_task(self._send_packets_ch1andup())
        self.clock.create_task(ordered.ordered_buffer_process(self))

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

        logger.debug(f'{self.clock.cycle}: pc={hex(self.pc)} bytes={hex(inst_hex)} instruction={inst_str} {type(instruction)}')

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

