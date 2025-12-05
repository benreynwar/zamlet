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
from enum import Enum
from typing import List, Tuple, Deque, Any
from dataclasses import dataclass

from zamlet import decode
from zamlet import addresses
from zamlet.addresses import SizeBytes, SizeBits, TLB, WordOrder
from zamlet.addresses import AddressConverter, Ordering, GlobalAddress, KMAddr, VPUAddress
from zamlet.kamlet.cache_table import CacheTable, CacheState, WaitingItem, WaitingFuture, ProtocolState
from zamlet.monitor import CompletionType, SpanType
from zamlet.params import LamletParams
from zamlet.message import Header, MessageType, Direction, SendType, TaggedHeader, CHANNEL_MAPPING
from zamlet.kamlet.kamlet import Kamlet
from zamlet.memlet import Memlet
from zamlet.runner import Future
from zamlet.kamlet import kinstructions
from zamlet.transactions.load_stride import LoadStride
from zamlet.transactions.store_stride import StoreStride
from zamlet.transactions.ident_query import IdentQuery
from zamlet.lamlet.scalar import ScalarState
from zamlet import utils
import zamlet.disasm_trace as dt
from zamlet.synchronization import SyncDirection
from zamlet.monitor import Monitor, CompletionType, ResourceType


logger = logging.getLogger(__name__)


class RefreshState(Enum):
    DORMANT = 0
    READY_TO_SEND = 1
    WAITING_FOR_RESPONSE = 2


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
        self.waiting_items: List[WaitingItem|None] = [None for _ in range(params.n_items)]

        self.next_writeset_ident = 0
        self.next_instr_ident = 0
        # Track oldest active instr_ident for flow control (None = unknown/all free)
        self._oldest_active_ident: int | None = None
        # Ident query state machine
        self._ident_query_state = RefreshState.DORMANT
        self._ident_query_ident = params.max_response_tags  # Dedicated ident for queries
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

    def _get_free_witem_index(self) -> int | None:
        """Get a free slot index in waiting_items, or None if full."""
        for index, item in enumerate(self.waiting_items):
            if item is None:
                return index
        return None

    async def add_witem(self, witem: WaitingItem) -> int:
        """Add a waiting item to the list, waiting if necessary. Returns the slot index."""
        while True:
            index = self._get_free_witem_index()
            if index is not None:
                break
            await self.clock.next_cycle
        self.waiting_items[index] = witem
        return index

    def get_witem_by_ident(self, instr_ident: int) -> WaitingItem | None:
        """Find a waiting item by its instr_ident. Raises if duplicates found."""
        matches = [item for item in self.waiting_items
                   if item is not None and item.instr_ident == instr_ident]
        if len(matches) > 1:
            raise ValueError(f"Multiple waiting items with instr_ident {instr_ident}")
        return matches[0] if matches else None

    def remove_witem_by_ident(self, instr_ident: int):
        """Remove a waiting item by its instr_ident."""
        for index, item in enumerate(self.waiting_items):
            if item is not None and item.instr_ident == instr_ident:
                self.waiting_items[index] = None
                return
        raise ValueError(f"No waiting item with instr_ident {instr_ident}")

    def get_oldest_active_instr_ident_distance(self, baseline: int) -> int | None:
        """Return the distance to the oldest active instr_ident from baseline.

        Distance is computed as (ident - baseline) % max_response_tags, so older idents
        (further back in the circular space) have smaller distances.

        Returns None if no waiting items have an instr_ident set (all free).
        """
        max_tags = self.params.max_response_tags
        idents = [item.instr_ident for item in self.waiting_items
                  if item is not None and item.instr_ident is not None]
        if not idents:
            return None  # All free
        distances = [(ident - baseline) % max_tags for ident in idents]
        min_dist = min(distances)
        min_idx = distances.index(min_dist)
        logger.debug(f'{self.clock.cycle}: lamlet: get_oldest_active_instr_ident_distance '
                     f'baseline={baseline} idents={idents} distances={distances} '
                     f'min_dist={min_dist} from ident={idents[min_idx]}')
        return min_dist

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
        instr_ident = await self.get_instr_ident()
        kinstr = kinstructions.WriteImmBytes(
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
        instr_ident = await self.get_instr_ident()
        future = self.clock.create_future()
        witem = WaitingFuture(future=future, instr_ident=instr_ident)
        await self.add_witem(witem)
        kinstr = kinstructions.ReadByte(
            k_maddr=k_maddr,
            instr_ident=instr_ident,
            )
        await self.add_to_instruction_buffer(kinstr, self._setup_span_id, k_maddr.k_index)
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
                            raise RuntimeError(
                                f"Router ({x}, {y}) connection stuck for {conn.age} cycles")
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

    async def sync_network_connections(self):
        """
        Move bytes between synchronizers in adjacent kamlets.
        This is a separate network from the main router network.
        Synchronizers connect to all 8 neighbors (N, S, E, W, NE, NW, SE, SW).
        """
        # Build a map of (k_x, k_y) -> synchronizer
        synchronizers = {}
        for kamlet in self.kamlets:
            k_x = kamlet.min_x // self.params.j_cols
            k_y = kamlet.min_y // self.params.j_rows
            synchronizers[(k_x, k_y)] = kamlet.synchronizer

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
            item = self.get_witem_by_ident(header.ident)
            assert item is not None, f"No waiting item for ident {header.ident}"
            assert isinstance(item, WaitingFuture)
            item.future.set_result(header.value)
            self.remove_witem_by_ident(header.ident)
            logger.debug(f'{self.clock.cycle}: lamlet: Got a READ_BYTE_RESP from ({header.source_x, header.source_y}) is {header.value}')
        elif header.message_type == MessageType.READ_WORDS_RESP:
            item = self.get_witem_by_ident(header.ident)
            assert item is not None, f"No waiting item for ident {header.ident}"
            assert isinstance(item, WaitingFuture)
            item.future.set_result(packet[1:])
            self.remove_witem_by_ident(header.ident)
            logger.debug(f'{self.clock.cycle}: lamlet: Got a READ_WORDS_RESP from ({header.source_x, header.source_y}) is {packet[1:]}')
        elif header.message_type == MessageType.IDENT_QUERY_RESP:
            assert len(packet) == 2, f"packet len {len(packet)}"
            assert header.ident == self._ident_query_ident
            min_distance = int.from_bytes(packet[1], byteorder='little')
            self._receive_ident_query_response(min_distance)
        else:
            raise NotImplementedError()

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
                        instructions.append(instr)
                        self._use_token(instr_k_index)
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
                ident_query = self._create_ident_query()
                self._use_token(None)
                # Move tokens to active query tracker (will be returned when response arrives)
                for i in range(self.params.k_in_l):
                    self._tokens_in_active_query[i] = self._tokens_used_since_query[i]
                    self._tokens_used_since_query[i] = 0
                # Add to broadcast packet, or send separately if packet is single-kamlet
                if send_k_index is None:
                    instructions.append(ident_query)
                else:
                    if instructions:
                        await self.send_instructions(instructions, send_k_index)
                    instructions = [ident_query]
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
            k_index = self.params.k_in_l - 1
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
            if instr.instr_ident is not None:
                if is_broadcast:
                    for kamlet in self.kamlets:
                        self.monitor.record_kinstr_exec_created(
                            instr, kamlet.min_x, kamlet.min_y)
                else:
                    kamlet = self.kamlets[k_index]
                    self.monitor.record_kinstr_exec_created(
                        instr, kamlet.min_x, kamlet.min_y)
                # All kinstr_exec children created - finalize (if FIRE_AND_FORGET)
                kinstr_span_id = self.monitor.get_kinstr_span_id(instr.instr_ident)
                if kinstr_span_id is not None:
                    kinstr_item = self.monitor.get_span(kinstr_span_id)
                    if kinstr_item.completion_type == CompletionType.FIRE_AND_FORGET:
                        self.monitor.finalize_children(kinstr_span_id)
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

    def _get_available_idents(self) -> int:
        """Return the number of idents available before collision."""
        max_tags = self.params.max_response_tags
        if self._oldest_active_ident is None:
            # No query response yet - next_instr_ident is how many we've used since start
            return max_tags - self.next_instr_ident
        return (self._oldest_active_ident - self.next_instr_ident) % max_tags

    def _create_ident_query(self) -> IdentQuery:
        """Create an IdentQuery instruction and update state."""
        assert self._ident_query_state == RefreshState.READY_TO_SEND

        self._ident_query_baseline = self.next_instr_ident
        # Capture lamlet's waiting items distance now, not when response arrives
        self._ident_query_lamlet_dist = self.get_oldest_active_instr_ident_distance(
            self._ident_query_baseline)

        kinstr = IdentQuery(
            instr_ident=self._ident_query_ident,
            baseline=self._ident_query_baseline,
            previous_instr_ident=self._last_sent_instr_ident,
        )
        self.monitor.record_kinstr_created(kinstr, self._ident_query_span_id)

        self._ident_query_state = RefreshState.WAITING_FOR_RESPONSE
        logger.debug(f'{self.clock.cycle}: lamlet: created ident query '
                     f'baseline={self._ident_query_baseline} '
                     f'previous_instr_ident={self._last_sent_instr_ident} '
                     f'lamlet_dist={self._ident_query_lamlet_dist}')
        return kinstr

    def _receive_ident_query_response(self, kamlet_min_distance: int):
        """Process ident query response. Called from message handler."""
        assert self._ident_query_state == RefreshState.WAITING_FOR_RESPONSE

        max_tags = self.params.max_response_tags
        assert 0 <= kamlet_min_distance <= max_tags

        baseline = self._ident_query_baseline

        # Use lamlet distance captured when query was created
        lamlet_min_distance = self._ident_query_lamlet_dist
        assert lamlet_min_distance is None or 0 <= lamlet_min_distance < max_tags

        # Combine: take the minimum distance (oldest ident) from both
        # kamlet_min_distance == max_tags means all kamlets are free
        # lamlet_min_distance == None means lamlet has no waiting items
        if kamlet_min_distance == max_tags and lamlet_min_distance is None:
            min_distance = max_tags
        elif kamlet_min_distance == max_tags:
            min_distance = lamlet_min_distance
        elif lamlet_min_distance is None:
            min_distance = kamlet_min_distance
        else:
            min_distance = min(kamlet_min_distance, lamlet_min_distance)

        if min_distance == max_tags:
            self._oldest_active_ident = None
        else:
            self._oldest_active_ident = (baseline + min_distance) % max_tags

        self._ident_query_state = RefreshState.DORMANT

        # Get query span_id before completing (completing removes from lookup table)
        query_span_id = self.monitor.get_kinstr_span_id(self._ident_query_ident)

        # Complete the IdentQuery kinstr before validation check
        self.monitor.complete_span(query_span_id)

        if self.monitor.enabled:
            # Only check kinstrs created before the query (span_id < query_span_id)
            monitor_oldest = self.monitor.get_oldest_active_instr_ident()
            if monitor_oldest is None:
                monitor_distance = max_tags
            else:
                oldest_span_id = self.monitor.get_kinstr_span_id(monitor_oldest)
                if oldest_span_id >= query_span_id:
                    monitor_distance = max_tags
                else:
                    monitor_distance = (monitor_oldest - baseline) % max_tags
            if monitor_distance < min_distance:
                span_id = self.monitor.get_kinstr_span_id(monitor_oldest)
                dump = self.monitor.dump_span(span_id) if span_id else f"no span_id for {monitor_oldest}"
                assert False, \
                    f"Monitor older than lamlet: monitor={monitor_oldest} (dist={monitor_distance}) " \
                    f"lamlet={self._oldest_active_ident} (dist={min_distance})\n{dump}"

        # Return instruction queue tokens tracked in _tokens_in_active_query.
        # This includes the IdentQuery itself (counted via _use_token when sent).
        # Check > 1 because the IdentQuery token is reserved and can't be used by regular instructions.
        for k_index in range(self.params.k_in_l):
            assert self._tokens_in_active_query[k_index] >= 1, \
                f"Expected at least 1 token returned for k_index={k_index}, got {self._tokens_in_active_query[k_index]}"
        tokens_returned = any(self._tokens_in_active_query[k] > 1 for k in range(self.params.k_in_l))
        for k_index in range(self.params.k_in_l):
            self._available_tokens[k_index] += self._tokens_in_active_query[k_index]
        if tokens_returned:
            self.monitor.record_resource_available(ResourceType.INSTR_BUFFER_TOKENS, None, None)

        logger.debug(f'{self.clock.cycle}: lamlet: ident query response '
                     f'baseline={baseline} kamlet_dist={kamlet_min_distance} '
                     f'lamlet_dist={lamlet_min_distance} min_distance={min_distance} '
                     f'oldest_active={self._oldest_active_ident} '
                     f'available_tokens={self._available_tokens}')

    async def _monitor_ident_query(self):
        """Coroutine to manage the ident query state machine.

        Sets state to READY_TO_SEND when ident space is running low.
        The actual sending is done by monitor_instruction_buffer.
        """
        max_tags = self.params.max_response_tags

        while True:
            if self._ident_query_state == RefreshState.DORMANT:
                # Transition to READY_TO_SEND when we have less than half idents free
                if self._get_available_idents() < max_tags // 2:
                    self._ident_query_state = RefreshState.READY_TO_SEND

            await self.clock.next_cycle

    async def get_instr_ident(self, n_idents=1):
        """Allocate n_idents consecutive instruction identifiers.

        Waits if not enough idents are available.
        """
        assert n_idents >= 1
        max_tags = self.params.max_response_tags

        if self._get_available_idents() < n_idents:
            self.monitor.record_resource_exhausted(ResourceType.INSTR_IDENT, None, None)
            while self._get_available_idents() < n_idents:
                await self.clock.next_cycle
            self.monitor.record_resource_available(ResourceType.INSTR_IDENT, None, None)

        ident = self.next_instr_ident
        if self._oldest_active_ident is None:
            self._oldest_active_ident = ident
        self.next_instr_ident = (self.next_instr_ident + n_idents) % max_tags
        return ident

    async def vload(self, vd: int, addr: int, ordering: addresses.Ordering,
                    n_elements: int, mask_reg: int|None, start_index: int,
                    parent_span_id: int,
                    reg_ordering: addresses.Ordering | None = None,
                    stride_bytes: int | None = None):
        element_bytes = ordering.ew // 8
        if stride_bytes is not None and stride_bytes != element_bytes:
            await self.vloadstorestride(vd, addr, ordering, n_elements, mask_reg,
                                        start_index, is_store=False,
                                        parent_span_id=parent_span_id,
                                        reg_ordering=reg_ordering,
                                        stride_bytes=stride_bytes)
        else:
            await self.vloadstore(vd, addr, ordering, n_elements, mask_reg, start_index,
                                  is_store=False, parent_span_id=parent_span_id,
                                  reg_ordering=reg_ordering)

    async def vstore(self, vs: int, addr: int, ordering: addresses.Ordering,
                    n_elements: int, mask_reg: int|None, start_index: int,
                    parent_span_id: int,
                    stride_bytes: int | None = None):
        element_bytes = ordering.ew // 8
        if stride_bytes is not None and stride_bytes != element_bytes:
            await self.vloadstorestride(vs, addr, ordering, n_elements, mask_reg,
                                        start_index, is_store=True,
                                        parent_span_id=parent_span_id,
                                        stride_bytes=stride_bytes)
        else:
            await self.vloadstore(vs, addr, ordering, n_elements, mask_reg, start_index,
                                  is_store=True, parent_span_id=parent_span_id)

    async def vloadstore(self, reg_base: int, addr: int, ordering: addresses.Ordering,
                         n_elements: int, mask_reg: int|None, start_index: int, is_store: bool,
                         parent_span_id: int,
                         reg_ordering: addresses.Ordering | None = None,
                         stride_bytes: int | None = None):
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
                        instr_ident = await self.get_instr_ident(2)
                        if is_store:
                            byte_mask = [0] * wb
                            start_word_byte = k_maddr.addr % wb
                            for byte_index in range(start_word_byte, start_word_byte + size):
                                byte_mask[byte_index] = 1
                            byte_mask_as_int = utils.list_of_uints_to_uint(byte_mask, width=1)
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
                            kinstr = kinstructions.LoadWord(
                                dst=reg_addr,
                                src=k_maddr,
                                byte_mask=byte_mask_as_int,
                                writeset_ident=writeset_ident,
                                mask_reg=mask_reg,
                                mask_index=mask_index,
                                instr_ident=instr_ident,
                            )
                    await self.add_to_instruction_buffer(kinstr, parent_span_id)
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
                                writeset_ident=writeset_ident, start_byte=start_byte_in_element,
                                parent_span_id=parent_span_id)
            else:
                if section.is_vpu:
                    section_elements = ((section.end_address - section.start_address) * 8)//reg_ew
                    starting_g_addr = GlobalAddress(bit_addr=section.start_address*8, params=self.params)
                    self.check_element_width(starting_g_addr, section.end_address - section.start_address, mem_ew)
                    k_maddr = self.to_k_maddr(starting_g_addr)

                    l_cache_line_bytes = self.params.cache_line_bytes * self.params.k_in_l
                    assert section.start_address//l_cache_line_bytes == (section.end_address-1)//l_cache_line_bytes

                    if is_store:
                        instr_ident = await self.get_instr_ident()
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
                        instr_ident = await self.get_instr_ident()
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
                    await self.add_to_instruction_buffer(kinstr, parent_span_id)
                else:
                    await self.vloadstore_scalar(reg_base, section.start_address, ordering, section_elements,
                                                 mask_reg, section.start_index, writeset_ident, is_store,
                                                 parent_span_id)

    async def vloadstorestride(self, reg_base: int, addr: int, ordering: addresses.Ordering,
                               n_elements: int, mask_reg: int | None, start_index: int,
                               is_store: bool, parent_span_id: int, stride_bytes: int,
                               reg_ordering: addresses.Ordering | None = None):
        """
        Handle strided vector loads/stores using LoadStride/StoreStride instructions.

        Strided access means elements are at addr, addr+stride, addr+2*stride, etc.
        Elements are placed contiguously in the register file.

        LoadStride/StoreStride is limited to j_in_l elements per instruction,
        so we process in chunks.
        """
        g_addr = GlobalAddress(bit_addr=addr * 8, params=self.params)
        mem_ew = ordering.ew

        if reg_ordering is None:
            reg_ordering = ordering
        reg_ew = reg_ordering.ew

        writeset_ident = self.get_writeset_ident()

        # Set up register file ordering for registers
        vline_bits = self.params.maxvl_bytes * 8
        n_vlines = (reg_ew * n_elements + vline_bits - 1) // vline_bits
        for vline_reg in range(reg_base, reg_base + n_vlines):
            self.vrf_ordering[vline_reg] = Ordering(word_order=addresses.WordOrder.STANDARD, ew=reg_ew)

        # Process in chunks of j_in_l elements
        j_in_l = self.params.j_in_l
        for chunk_start in range(0, n_elements, j_in_l):
            chunk_n = min(j_in_l, n_elements - chunk_start)
            chunk_addr = addr + chunk_start * stride_bytes
            chunk_g_addr = GlobalAddress(bit_addr=chunk_addr * 8, params=self.params)
            instr_ident = await self.get_instr_ident(n_idents=self.params.word_bytes + 1)

            if is_store:
                kinstr = StoreStride(
                    src=reg_base,
                    g_addr=chunk_g_addr,
                    start_index=start_index + chunk_start,
                    n_elements=chunk_n,
                    src_ordering=reg_ordering,
                    mask_reg=mask_reg,
                    writeset_ident=writeset_ident,
                    instr_ident=instr_ident,
                    stride_bytes=stride_bytes,
                )
            else:
                kinstr = LoadStride(
                    dst=reg_base,
                    g_addr=chunk_g_addr,
                    start_index=start_index + chunk_start,
                    n_elements=chunk_n,
                    dst_ordering=reg_ordering,
                    mask_reg=mask_reg,
                    writeset_ident=writeset_ident,
                    instr_ident=instr_ident,
                    stride_bytes=stride_bytes,
                )
            await self.add_to_instruction_buffer(kinstr, parent_span_id)

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
            start_index: int, writeset_ident: int, is_store: bool, parent_span_id: int):
        """
        Reads elements from the scalar memory and sends them to the appropriate kamlets where they will update the
        vector register.

        FIXME: This function is untested. Add tests for vector loads/stores to scalar memory.
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
                    instr_ident = await self.get_instr_ident()
                    kinstr = kinstructions.LoadImmByte(
                        dst=vd,
                        imm=byte_imm,
                        bit_mask=bit_mask,
                        mask_reg=mask_reg,
                        mask_index=mask_index,
                        writeset_ident=writeset_ident,
                        instr_ident=instr_ident,
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
                    instr_ident = await self.get_instr_ident()
                    kinstr = kinstructions.LoadImmWord(
                        dst=vd,
                        imm=word_imm,
                        byte_mask=byte_mask_as_int,
                        mask_reg=mask_reg,
                        mask_index=mask_index,
                        writeset_ident=writeset_ident,
                        instr_ident=instr_ident,
                        )
            await self.add_to_instruction_buffer(kinstr, parent_span_id, k_index=k_index)

    async def vload_scalar_partial(self, vd: int, addr: int, size: int, dst_ordering: Ordering,
                                   mask_reg: int, mask_index: int, element_index: int,
                                   start_byte: int, writeset_ident: int, parent_span_id: int):
        """
        Reads a partial element from the scalar memory and sends it to the appropriate jamlet where it will update a
        vector register.

        start_byte: Which byte in element we starting loading from.
        size: How many bytes from the element we load.

        FIXME: This function is untested. Add tests for vector loads/stores to scalar memory.
        """
        assert start_byte + size < self.params.word_bytes
        g_addr = GlobalAddress(bit_addr=addr*8, params=self.params)
        scalar_addr = g_addr.to_scalar_addr(self.tlb)
        vw_index = element_index % self.params.j_in_l
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                self.params, dst_ordering.word_order, vw_index)
        kinstr: kinstructions.KInstr
        instr_ident = await self.get_instr_ident()
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
                instr_ident=instr_ident,
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
                instr_ident=instr_ident,
                )
        await self.add_to_instruction_buffer(kinstr, parent_span_id, k_index=k_index)

    async def vstore_scalar_partial(self, vd: int, addr: int, size: int, src_ordering: Ordering,
                                    mask_reg: int, mask_index: int, element_index: int,
                                    writeset_ident: int, start_byte: int):
        """FIXME: This function is untested. Add tests for vector loads/stores to scalar memory."""
        raise NotImplementedError("vstore_scalar_partial not yet implemented")

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
        self.clock.create_task(self.sync_network_connections())
        self.clock.create_task(self.monitor_replys())
        self.clock.create_task(self.monitor_instruction_buffer())
        self.clock.create_task(self._monitor_ident_query())

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

