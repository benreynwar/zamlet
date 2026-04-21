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
    LamletWaitingItem, LamletWaitingFuture, LamletWaitingReadRegElement,
    LamletWaitingVrgatherBroadcast,
    LamletWaitingLoadIndexedElement, LamletWaitingStoreIndexedElement)
from zamlet.monitor import CompletionType, SpanType
from zamlet.params import ZamletParams
from zamlet.message import (Header, MessageType, Direction, SendType, TaggedHeader,
                            WriteMemWordHeader, CHANNEL_MAPPING, IdentHeader,
                            ElementIndexHeader, ReadMemWordHeader)
from zamlet.kamlet.kamlet import Kamlet
from zamlet.memlet import Memlet, memlet_coords
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
from zamlet.oamlet.scalar import ScalarState
from zamlet.oamlet import reduction
from zamlet.lamlet.ordered_buffer import OrderedBuffer, ElementEntry, ElementState
from zamlet import utils
import zamlet.disasm_trace as dt
from zamlet.synchronization import SyncDirection, Synchronizer
from zamlet.monitor import Monitor, CompletionType, ResourceType
from zamlet.lamlet import ident_query
from zamlet.lamlet.ident_query import IdentQuerySlot
from zamlet.lamlet import ordered
from zamlet.lamlet import unordered
from zamlet.lamlet import vregister


logger = logging.getLogger(__name__)


class Oamlet:

    def __init__(self, clock, params: ZamletParams,
                 word_order: WordOrder = WordOrder.STANDARD):
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
        # Lamlet's synchronizer at position (0, -1)
        self.synchronizer = Synchronizer(
            clock=clock,
            params=params,
            kx=0,
            ky=-1,
            cache_table=None,  # Lamlet manages its own waiting items
            monitor=self.monitor,
        )
        self.scalar = ScalarState(clock, params, self.monitor,
                                  synchronizer=self.synchronizer)
        self.tlb = TLB(params)
        self.vrf_ordering: List[Ordering|None] = [None for _ in range(params.n_vregs)]
        # Per-vline pending-write counter. Incremented when the lamlet has
        # dispatched an async operation that will eventually emit a kinstr
        # writing this vreg (e.g. vrgather.vx waiting on a remote element
        # read), decremented when the kinstr is appended to the instruction
        # buffer. Dispatch sites must ``await_vreg_write_pending`` before
        # emitting kinstrs that read or write the vreg, so later instructions
        # can't slip a kinstr past the pending write.
        self.vrf_write_pending: List[int] = [0 for _ in range(params.n_vregs)]
        self.vl = 0
        self.vtype = 0
        self.vstart = 0
        self.exit_code = None

        self.word_order = word_order
        # Scratch arch index tracker. Compound lamlet ops (e.g. reductions,
        # strided/indexed batches) use arch indices in [N_ARCH_VREGS, n_vregs)
        # for internal temporaries. The kamlet rename table treats these the
        # same as ISA arch indices: w() allocates a fresh phys on first
        # write, and a FreeRegister kinstr at the release point unmaps the
        # arch and returns its phys to the kamlet's free queue. The lamlet
        # tracker below just remembers which scratch arch indices are
        # currently in use so we don't double-allocate.
        self._scratch_arch_free: deque[int] = deque(
            range(params.n_arch_vregs, params.n_vregs))

        # Scratch VPU pages for ew remap workaround, one per (phys, ew).
        # Uses address range 0xF0000000+. See TODO.md for replacing with a
        # dedicated register-to-register ew remap kinstr.
        self._scratch_base = 0xF0000000
        self._scratch_pages: set[tuple[int, int]] = set()  # allocated (phys, ew) pairs

        self.min_x = params.west_offset
        self.min_y = params.north_offset

        # Lamlet is at top of jamlet grid in routing coords
        self.instr_x = params.west_offset
        self.instr_y = 0

        self.instruction_buffer: Deque[Any] = deque()

        # Need this for how we arrange memlets
        assert self.params.k_cols % 2 == 0

        self.kamlets = []
        self.memlets = []
        for kamlet_index in range(params.k_in_l):
            kamlet_x = params.west_offset + params.j_cols * (kamlet_index % params.k_cols)
            kamlet_y = params.north_offset + params.j_rows * (kamlet_index // params.k_cols)
            mem_coords = memlet_coords(params, kamlet_index)
            kamlet = Kamlet(
                clock=clock,
                params=params,
                min_x=kamlet_x,
                min_y=kamlet_y,
                tlb=self.tlb,
                monitor=self.monitor,
                lamlet_x=self.instr_x,
                lamlet_y=self.instr_y,
                mem_coords=mem_coords,
                )
            self.kamlets.append(kamlet)
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
        # 0 = no bound (full 64-bit indices), N = mask indices to lower N bits
        self.index_bound_bits: int = 0
        self.active_writeset_ident: int | None = None
        self.next_instr_ident = 0
        # Track oldest active instr_ident for flow control (None = unknown/all free)
        self._oldest_active_ident: int | None = None
        # Ident query circular buffer.
        # Each slot has a dedicated sync ident. _iq_newest is the next
        # slot to use for sending. Pointers wrap at n_ident_query_slots.
        # _iq_full distinguishes full (_iq_oldest == _iq_newest,
        # full=True) from empty (equal, full=False).
        n_iq = params.n_ident_query_slots
        self._iq_slots = [IdentQuerySlot() for _ in range(n_iq)]
        self._iq_idents = [
            params.max_response_tags + i for i in range(n_iq)]
        # _iq_oldest: oldest slot not yet fully drained (gates _iq_full /
        # slot reuse; advances when the lamlet's local sync for that
        # slot's sync_ident has drained).
        # _iq_response_head: next slot expected to receive its response
        # (preserves FIFO matching of response → slot). Advances on
        # response arrival.
        # Invariant: _iq_oldest is "behind or equal to" _iq_response_head,
        # which is "behind or equal to" _iq_newest (mod n_iq).
        self._iq_oldest = 0
        self._iq_response_head = 0
        self._iq_newest = 0
        self._iq_full = False
        # Dedicated idents for ordered barrier instructions (after ident query idents)
        self._ordered_barrier_idents = [
            params.max_response_tags + n_iq + i
            for i in range(params.n_ordered_buffers)]
        # Track last instr_ident sent to kamlets (for IdentQuery.previous_instr_ident)
        # Initialize to max_response_tags - 2 so first query reports
        # max_response_tags - 1 as oldest
        self._last_sent_instr_ident: int = params.max_response_tags - 2

        # Per-kamlet instruction queue token tracking
        # Available tokens = how many instructions we can send to this kamlet
        self._available_tokens = [
            params.instruction_queue_length for _ in range(params.k_in_l)]
        # Tokens used since we sent the last ident query (will be snapshotted
        # into the next slot when a query is sent)
        self._tokens_used_since_query = [0 for _ in range(params.k_in_l)]

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

        # Lamlet network buffers. router_connections moves words between these
        # and jamlet(0,0)'s N direction, just like any other router link.
        self._receive_buffers = [
            utils.Queue(length=params.router_output_buffer_length)
            for _ in range(params.n_channels)
        ]
        self._send_word_buffers = [
            utils.Queue(length=params.router_output_buffer_length)
            for _ in range(params.n_channels)
        ]

        # Ordered indexed operation buffers, indexed by buffer_id (0 to n_ordered_buffers-1)
        self._ordered_buffers: list[OrderedBuffer | None] = [
            None for _ in range(self.params.n_ordered_buffers)]

    def has_free_witem_slot(self) -> bool:
        """Check if there's room for another waiting item."""
        return len(self.waiting_items) < self.params.witem_table_depth

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

    def _scratch_active_count(self) -> int:
        return self.params.n_vregs - self.params.n_arch_vregs - len(self._scratch_arch_free)

    def alloc_temp_regs(self, n: int) -> list[int]:
        """Reserve n scratch arch indices in [n_arch_vregs, n_vregs).

        These get embedded directly in kinstructions; the kamlet's rename
        table allocates a phys for each on first write. The caller must
        await free_temp_regs at the release point — that emits a
        FreeRegister kinstr per arch (which returns the phys to the
        kamlet's free queue) and returns the arch slot to this lamlet
        tracker for reuse.
        """
        assert len(self._scratch_arch_free) >= n, \
            f"only {len(self._scratch_arch_free)} scratch arches free, need {n}"
        regs = [self._scratch_arch_free.popleft() for _ in range(n)]
        active = self._scratch_active_count()
        capacity = self.params.n_vregs - self.params.n_arch_vregs
        logger.debug(
            f'{self.clock.cycle}: lamlet alloc_temp_regs n={n} regs={regs} '
            f'active={active}/{capacity}')
        return regs

    async def free_temp_regs(self, regs: list[int], parent_span_id: int) -> None:
        """Release scratch arch indices.

        Emits a FreeRegister kinstr for each arch (so the kamlet returns its
        phys to the free queue) and then returns the arch index to the
        lamlet tracker. The kinstr goes into the FIFO after every prior
        instruction that used the arch, so the kamlet handles ordering;
        callers do not need to wait for the prior uses to drain.
        """
        capacity = self.params.n_vregs - self.params.n_arch_vregs
        logger.debug(
            f'{self.clock.cycle}: lamlet free_temp_regs n={len(regs)} regs={regs} '
            f'active_before={self._scratch_active_count()}/{capacity}')
        for reg in regs:
            assert self.params.n_arch_vregs <= reg < self.params.n_vregs, \
                f"reg={reg} is not a scratch arch index"
            assert reg not in self._scratch_arch_free, \
                f"reg={reg} already in scratch free queue"
            free_ident = await ident_query.get_instr_ident(self)
            await self.add_to_instruction_buffer(
                kinstructions.FreeRegister(reg=reg, instr_ident=free_ident),
                parent_span_id)
            self._scratch_arch_free.append(reg)

    def get_scratch_page(self, phys: int, ew: int) -> int:
        """Get a scratch VPU page for a (phys, ew) pair. Allocates lazily."""
        ew_index = {1: 0, 8: 1, 16: 2, 32: 3, 64: 4}[ew]
        key = (phys, ew)
        addr = self._scratch_base + (phys * 8 + ew_index) * self.params.page_bytes
        if key not in self._scratch_pages:
            g_addr = GlobalAddress(bit_addr=addr * 8, params=self.params)
            self.allocate_memory(
                g_addr, self.params.page_bytes, memory_type=MemoryType.VPU)
            self._scratch_pages.add(key)
        return addr

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

    @property
    def sew(self):
        vsew = (self.vtype >> 3) & 0x7
        return 8 << vsew

    @property
    def lmul(self):
        vlmul = self.vtype & 0x7
        if vlmul <= 3:
            return 1 << vlmul
        else:
            return 1

    def set_vtype(self, ew: int, lmul: int):
        vsew = {8: 0, 16: 1, 32: 2, 64: 3}[ew]
        vlmul = {1: 0, 2: 1, 4: 2, 8: 3}[lmul]
        self.vtype = (vsew << 3) | vlmul

    def emul_for_eew(self, eew: int) -> int:
        """EMUL = LMUL * EEW / SEW, clamped to a minimum of 1 vline
        (fractional EMUL still occupies one register)."""
        return max(1, self.lmul * eew // self.sew)

    async def await_vreg_write_pending(self, vreg: int, n_vlines: int) -> None:
        """Block until no pending async writes target any vline in the range.

        Dispatch sites that read or write architectural vreg state must call
        this before setting/asserting ``vrf_ordering`` or emitting kinstrs
        that touch the vreg, so deferred writes (e.g. vrgather.vx's
        VBroadcastOp) are ordered ahead of later consumers.
        """
        while any(self.vrf_write_pending[vreg + i] > 0 for i in range(n_vlines)):
            await self.clock.next_cycle

    def set_vrf_ordering(self, vd: int, eew: int):
        """Unconditionally relabel vrf_ordering for every vline in ``vd``'s
        EMUL group. Intended for full-overwrite destinations where the prior
        data is being replaced — no read, no remap, no check. For partial
        writes or reads, use ``ensure_vrf_ordering`` instead."""
        ordering = Ordering(self.word_order, eew)
        n_vlines = self.emul_for_eew(eew)
        logger.info(f'set_vrf_ordering: vd=v{vd} eew={eew} '
                    f'lmul={self.lmul} n_vlines={n_vlines} regs=v{vd}..v{vd + n_vlines - 1}')
        for i in range(n_vlines):
            self.vrf_ordering[vd + i] = ordering

    async def ensure_vrf_ordering(
            self, vreg: int, ew: int, span_id: int,
            *, allow_uninitialized: bool = False) -> None:
        """Make vreg's ordering match (self.word_order, ew) across its EMUL group.

        Uninitialized entries (None): set the target ordering if
        ``allow_uninitialized`` is True, else assert. word_order mismatch is
        always a fatal assert — we never silently remap across word_orders.
        ew mismatches are remapped via scratch memory, except that either side
        at ew=1 (mask register) asserts because remap_reg_ew requires
        ew % 8 == 0. After any required remap, the final ordering is set.
        """
        n_vlines = self.emul_for_eew(ew)
        regs_to_remap = []
        for i in range(n_vlines):
            reg = vreg + i
            cur = self.vrf_ordering[reg]
            if cur is None:
                assert allow_uninitialized, (
                    f'v{reg} has no ordering (expected ew={ew})')
                continue
            assert cur.word_order == self.word_order, (
                f'v{reg} word_order={cur.word_order} does not match current '
                f'word_order={self.word_order}; refusing to silently remap')
            if cur.ew == ew:
                continue
            assert cur.ew != 1 and ew != 1, (
                f'v{reg} mask-register ew mismatch (cur ew={cur.ew}, '
                f'target ew={ew}); mask regs cannot round-trip through memory')
            regs_to_remap.append(reg)
        if regs_to_remap:
            dst_ordering = Ordering(self.word_order, ew)
            logger.warning(
                f'ensure_vrf_ordering: remapping v{regs_to_remap} to ew={ew}')
            await unordered.remap_reg_ew(
                self, regs_to_remap, regs_to_remap, dst_ordering, span_id)
        self.set_vrf_ordering(vreg, ew)

    def mark_vreg_write_pending(self, vreg: int, eew: int) -> None:
        """Increment the pending-write counter for every vline in vreg's EMUL group."""
        n_vlines = self.emul_for_eew(eew)
        for i in range(n_vlines):
            self.vrf_write_pending[vreg + i] += 1

    def clear_vreg_write_pending(self, vreg: int, eew: int) -> None:
        """Decrement the pending-write counter (paired with mark_vreg_write_pending)."""
        n_vlines = self.emul_for_eew(eew)
        for i in range(n_vlines):
            assert self.vrf_write_pending[vreg + i] > 0, (
                f'clear_vreg_write_pending: v{vreg + i} counter already zero')
            self.vrf_write_pending[vreg + i] -= 1

    def allocate_memory(self, address: GlobalAddress, size: SizeBytes, memory_type: MemoryType,
                        readable: bool = True, writable: bool = True):
        assert size % self.params.page_bytes == 0
        self.tlb.allocate_memory(address, size, memory_type, readable, writable)
        # Register non-idempotent pages with ScalarState
        if memory_type == MemoryType.SCALAR_NON_IDEMPOTENT:
            for page_offset in range(0, size, self.params.page_bytes):
                page_addr = address.addr + page_offset
                page_info = self.tlb.get_page_info(
                    GlobalAddress(bit_addr=page_addr*8, params=self.params))
                self.scalar.register_non_idempotent_page(page_info.physical_addr)

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
            writeset_ident=ident_query.get_writeset_ident(self),
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
            writeset_ident=ident_query.get_writeset_ident(self),
            )
        await self.add_to_instruction_buffer(kinstr, self._setup_span_id, k_maddr.k_index)
        return future

    async def read_register_element(self, vreg, element_index, element_width):
        """Read a single element from a vector register. Returns a Future.

        Sends a ReadRegWord kinstr to the kamlet that owns the element.
        The kamlet reads the full word from rf_slice and sends it back.
        The waiting item extracts the element and sign-extends to XLEN.
        """
        ordering = self.vrf_ordering[vreg]
        assert ordering.ew == element_width
        vw_index = element_index % self.params.j_in_l
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
            self.params, ordering.word_order, vw_index)
        instr_ident = await ident_query.get_instr_ident(self)
        future = self.clock.create_future()
        witem = LamletWaitingReadRegElement(
            future=future, instr_ident=instr_ident,
            element_width=element_width, word_bytes=self.params.word_bytes,
        )
        await self.add_witem(witem)
        kinstr = kinstructions.ReadRegWord(
            src=vreg,
            j_in_k_index=j_in_k_index,
            instr_ident=instr_ident,
        )
        await self.add_to_instruction_buffer(
            kinstr, self._ident_query_span_id, k_index,
        )
        return future

    async def router_connections(self, channel):
        '''
        Move words between router buffers
        '''
        routers = {}
        j_cols = self.params.j_cols * self.params.k_cols
        j_rows = self.params.j_rows * self.params.k_rows
        grid_width = 2 * self.params.west_offset + j_cols
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
        for x in range(grid_width):
            for y in range(self.params.north_offset, self.params.north_offset + j_rows):
                assert (x, y) in routers

        # Now start the logic to move the messages between the routers
        while True:
            await self.clock.next_cycle
            for x in range(grid_width):
                for y in range(self.params.north_offset, self.params.north_offset + j_rows):
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
                    elif x == self.instr_x and y == self.params.north_offset:
                        # Send to the lamlet
                        north_buffer = router._output_buffers[Direction.N]
                        if north_buffer:
                            recv_buf = self._receive_buffers[channel]
                            if recv_buf.can_append():
                                word = north_buffer.popleft()
                                recv_buf.append(word)
                                north_moving = True
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

            send_buf = self._send_word_buffers[channel]
            lamlet_s_present = bool(send_buf)
            lamlet_s_moving = False
            if send_buf:
                lamlet_target = (self.instr_x, self.params.north_offset)
                j00_input = routers[lamlet_target]._input_buffers[Direction.N]
                if j00_input.can_append():
                    word = send_buf.popleft()
                    j00_input.append(word)
                    lamlet_s_moving = True
            self.monitor.report_router_output(
                self.instr_x, 0, channel, Direction.S,
                lamlet_s_present, lamlet_s_moving)

    async def sync_network_connections(self):
        """
        Move bytes between synchronizers in adjacent kamlets (and the lamlet).
        This is a separate network from the main router network.
        Synchronizers connect to all 8 neighbors (N, S, E, W, NE, NW, SE, SW).
        The lamlet's synchronizer is at (0, -1) and connects to kamlet (0,0) and (1,0).
        """
        # Build a map of (kx, ky) -> synchronizer
        synchronizers = {}
        for kamlet in self.kamlets:
            kx = (kamlet.min_x - self.params.west_offset) // self.params.j_cols
            ky = (kamlet.min_y - self.params.north_offset) // self.params.j_rows
            synchronizers[(kx, ky)] = kamlet.synchronizer

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

    async def monitor_waiting_items(self):
        """Advance post-response state on lamlet waiting items.

        Each cycle, iterates the waiting_items deque and calls
        ``monitor_lamlet`` on each. Items that transition to ``ready()``
        (e.g. LamletWaitingVrgatherBroadcast after the VBroadcastOp is
        appended) are removed. Items with purely sync response-path
        removal (LamletWaitingReadRegElement etc.) have a no-op
        ``monitor_lamlet`` and never become ``ready`` via this path.
        """
        while True:
            await self.clock.next_cycle
            for item in list(self.waiting_items):
                if item not in self.waiting_items:
                    continue
                await item.monitor_lamlet(self)
                if item.ready():
                    self.waiting_items.remove(item)
                    break

    async def monitor_channel0(self):
        """Handle channel 0 packets (responses that must be consumed immediately)."""
        buffer = self._receive_buffers[0]
        header = None
        packet = []
        while True:
            await self.clock.next_cycle
            if buffer:
                word = buffer.popleft()
                if header is None:
                    assert isinstance(word, Header)
                    header = word.copy()
                    remaining_words = header.length + 1
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
        assert header.length == len(packet) - 1

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
        elif header.message_type == MessageType.READ_REG_WORD_RESP:
            assert len(packet) == 2
            item = self.get_witem_by_ident(header.ident)
            assert item is not None, f"No waiting item for ident {header.ident}"
            if isinstance(item, LamletWaitingVrgatherBroadcast):
                # Stash the word; monitor_waiting_items will emit the
                # VBroadcastOp and remove the item once the buffer has room.
                item.resolve(packet[1])
                self.monitor.complete_kinstr(header.ident)
            else:
                assert isinstance(item, LamletWaitingReadRegElement)
                item.resolve(packet[1])
                self.remove_witem_by_ident(header.ident)
                self.monitor.complete_kinstr(header.ident)
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
            min_distance = packet[1]
            ident_query.receive_ident_query_response(
                self, header.ident, min_distance, kinstr_span_id)
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
                buffer = self._receive_buffers[channel]
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
        remaining_words = header.length
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
        assert header.length == len(packet) - 1

        # All channel 1+ messages to lamlet have a tag
        assert hasattr(header, 'tag'), f"Header {type(header).__name__} missing tag attribute"
        self.monitor.record_message_received_by_header(
            header, self.instr_x, self.instr_y)

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
            assert isinstance(src_word, int), \
                f"Expected int, got {type(src_word)}: {src_word}"
            await unordered.handle_write_mem_word_req(self, header, scalar_addr, src_word)
        else:
            raise NotImplementedError(f"Unexpected channel 1+ message: {header.message_type}")

    async def add_to_instruction_buffer(self, instruction, parent_span_id: int, k_index=None):
        logger.debug(f'{self.clock.cycle}: lamlet: Adding {type(instruction)} to buffer')
        self.monitor.record_kinstr_created(instruction, parent_span_id)
        while len(self.instruction_buffer) >= self.params.instruction_buffer_length:
            await self.clock.next_cycle
        self.instruction_buffer.append((instruction, k_index))
        self.monitor.record_lamlet_instr_added()

    def _have_tokens(self, k_index: int | None, is_ident_query: bool = False) -> bool:
        """Check if we have tokens available for the given k_index (or all if None).

        Regular instructions need > 1 token on the target kamlet and
        > 0 on all kamlets (so a broadcast ident query is always possible).
        IdentQuery only needs > 0 tokens on all kamlets.
        """
        if not all(t > 0 for t in self._available_tokens):
            return False
        if is_ident_query:
            return True
        if k_index is None:
            return all(t > 1 for t in self._available_tokens)
        else:
            return self._available_tokens[k_index] > 1

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

    async def _monitor_instruction_buffer_state(self):
        while True:
            await self.clock.next_cycle
            self.monitor.record_lamlet_cycle_state(
                buf_len=len(self.instruction_buffer),
                free_idents=ident_query.get_available_idents(self),
                free_tokens={i: t for i, t in enumerate(self._available_tokens)},
            )

    def _dispatch_instr(self, instr):
        """Mark an instruction as dispatched in the monitor and lamlet."""
        span_id = self.monitor.get_kinstr_span_id(instr.instr_ident)
        self.monitor.add_event(span_id, "dispatched")
        witem = self.get_witem_by_ident(instr.instr_ident)
        if witem is not None:
            assert isinstance(witem, LamletWaitingItem)
            witem.dispatched = True

    async def _flush_packet(self, packet, packet_dest):
        """Send a packet if non-empty. Returns ([], None)."""
        if packet:
            logger.debug(
                f'{self.clock.cycle}: lamlet: flush packet'
                f' size={len(packet)} dest={packet_dest}'
                f' tokens={self._available_tokens}')
            await self.send_instructions(packet, packet_dest)
        return [], None

    async def _add_ident_query(self, packet, packet_dest):
        """Add an ident query to the packet stream.

        If current packet is single-kamlet, flush it first since the
        ident query is broadcast.
        Returns (packet, packet_dest) with the query appended.
        """
        if packet_dest is not None:
            packet, packet_dest = await self._flush_packet(
                packet, packet_dest)
        assert self._have_tokens(None, is_ident_query=True)
        # Use broadcast token before create so it's included in the
        # token snapshot that create_ident_query captures.
        self._use_token(None)
        iq_kinstr = ident_query.create_ident_query(self)
        self._dispatch_instr(iq_kinstr)
        packet.append(iq_kinstr)
        packet_dest = None
        return packet, packet_dest

    async def monitor_instruction_buffer(self):
        packet = []
        packet_dest = None
        inactive_count = 0
        while True:
            added_any = False

            while self.instruction_buffer:
                instr, k_index = self.instruction_buffer[0]

                # No tokens: flush what we have and stop
                if not self._have_tokens(k_index):
                    self.monitor.record_resource_exhausted(
                        ResourceType.INSTR_BUFFER_TOKENS, None, None)
                    packet, packet_dest = await self._flush_packet(
                        packet, packet_dest)
                    break

                # Destination change: flush current packet
                if packet and k_index != packet_dest:
                    packet, packet_dest = await self._flush_packet(
                        packet, packet_dest)

                # Pop and add to packet
                self.instruction_buffer.popleft()
                packet.append(instr)
                packet_dest = k_index
                self._use_token(k_index)
                self._dispatch_instr(instr)
                added_any = True

                # Ident query threshold reached
                if ident_query.should_send_ident_query(self):
                    packet, packet_dest = \
                        await self._add_ident_query(packet, packet_dest)

                # Max packet length
                if len(packet) >= self.params.instructions_in_packet:
                    packet, packet_dest = await self._flush_packet(
                        packet, packet_dest)

            # Buffer empty but ident query needed
            if not added_any and ident_query.should_send_ident_query(self):
                packet, packet_dest = \
                    await self._add_ident_query(packet, packet_dest)
                added_any = True

            # Idle timeout: flush packet if no new instructions for a while
            if added_any:
                inactive_count = 0
            elif self.instruction_buffer or packet:
                inactive_count += 1
                if inactive_count > 2 and packet:
                    packet, packet_dest = await self._flush_packet(
                        packet, packet_dest)
                    inactive_count = 0

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
            x = self.params.west_offset + self.params.k_cols * self.params.j_cols - 1
            y = self.params.north_offset + self.params.k_rows * self.params.j_rows - 1
        else:
            send_type = SendType.SINGLE
            kx = k_index % self.params.k_cols
            ky = k_index // self.params.k_cols
            x = self.min_x + kx * self.params.j_cols
            y = self.min_y + ky * self.params.j_rows
        header = Header(
            target_x=x,
            target_y=y,
            source_x=self.instr_x,
            source_y=self.instr_y,
            length=len(instructions),
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
        """Drain channel 0 send queues into the lamlet's send word buffer."""
        word_buf = self._send_word_buffers[0]
        while True:
            sent_something = False
            for msg_type, send_queue in self._send_queues.items():
                if CHANNEL_MAPPING.get(msg_type, 0) == 0 and send_queue:
                    packet = send_queue.popleft()
                    await self._send_packet_words(packet, word_buf)
                    sent_something = True
            if not sent_something:
                await self.clock.next_cycle

    async def _send_packets_ch1andup(self):
        """Drain channel 1+ send queues into the lamlet's send word buffers."""
        while True:
            sent_something = False
            for msg_type, send_queue in self._send_queues.items():
                channel = CHANNEL_MAPPING.get(msg_type, 0)
                if channel >= 1 and send_queue:
                    word_buf = self._send_word_buffers[channel]
                    packet = send_queue.popleft()
                    await self._send_packet_words(packet, word_buf)
                    sent_something = True
            if not sent_something:
                await self.clock.next_cycle

    async def _send_packet_words(self, packet, word_buf):
        """Send all words of a packet into a word buffer, one per cycle."""
        while packet:
            await self.clock.next_cycle
            if word_buf.can_append():
                word = packet.pop(0)
                word_buf.append(word)
            else:
                pass  # Wait for router_connections to drain the buffer

    async def set_memory(self, address: int, data: bytes,
                         ordering: 'addresses.Ordering | None' = None,
                         weak_ordering: 'addresses.Ordering | None' = None):
        assert not (ordering is not None and weak_ordering is not None), (
            'set_memory: cannot pass both ordering and weak_ordering')
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
                vline_info = self.tlb.get_vline_info(byt_address)
                if vline_info.local_address.ordering is None:
                    if ordering is not None:
                        self.tlb.set_vline_ordering(byt_address, ordering)
                    elif weak_ordering is not None:
                        self.tlb.set_vline_ordering(
                            byt_address, weak_ordering, weak=True)
                    else:
                        assert False, (
                            f'set_memory to VPU address 0x{byt_address.addr:x} '
                            f'requires ordering or weak_ordering')
                elif ordering is not None:
                    assert vline_info.local_address.ordering == ordering, (
                        f'set_memory ordering mismatch at 0x{byt_address.addr:x}: '
                        f'vline has {vline_info.local_address.ordering}, '
                        f'caller passed {ordering}')
                await self.write_bytes(byt_address, bytes([b]))
                # TODO: Be a bit more careful about whether we need to add this.
                await self.clock.next_cycle
            else:
                scalar_address = self.to_scalar_addr(byt_address)
                await self.scalar.set_memory(
                    scalar_address, bytes([b]), allow_wait=True)

    async def set_memory_existing_ew(self, address: int, data: bytes):
        """Write data to memory using existing vline orderings.

        For VPU bytes, the vline must already have an ordering set.
        For scalar bytes, no ordering is needed.
        Only used during test setup.
        """
        global_addr = GlobalAddress(bit_addr=address*8, params=self.params)
        for index, b in enumerate(data):
            byt_address = GlobalAddress(
                bit_addr=global_addr.addr*8+index*8, params=self.params)
            if byt_address.is_vpu(self.tlb):
                vline_info = self.tlb.get_vline_info(byt_address)
                assert vline_info.local_address.ordering is not None, (
                    f'set_memory_existing_ew at 0x{byt_address.addr:x}: '
                    f'vline has no ordering')
                await self.write_bytes(byt_address, bytes([b]))
                await self.clock.next_cycle
            else:
                scalar_address = self.to_scalar_addr(byt_address)
                await self.scalar.set_memory(
                    scalar_address, bytes([b]), allow_wait=True)

    def directly_set_memory(self, address: int, data: bytes,
                            ordering: 'addresses.Ordering | None' = None):
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
                vline_info = self.tlb.get_vline_info(byte_addr)
                if vline_info.local_address.ordering is None:
                    assert ordering is not None, (
                        f'directly_set_memory to VPU address 0x{byte_addr.addr:x} '
                        f'requires ordering')
                    self.tlb.set_vline_ordering(byte_addr, ordering)
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
                self.scalar._memory[scalar_address] = b

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
        It returns a future that resolves when the value has been returned.

        TODO: For scalar reads this currently stalls on all pending vector writes
        (including instruction fetch). A store buffer tracking in-flight scalar write
        addresses would let us only stall when there's an actual address overlap.
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
                data = await self.scalar.get_memory(
                    local_address, size=size, allow_wait=True)
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

    async def _remap_vline(self, vline_addr: int, new_ordering: addresses.Ordering,
                           parent_span_id: int):
        """Remap a single vline's data from its current ew to new_ordering's ew.

        Loads the full vline at old ew into a temp reg, then stores it back at the new ew.
        The full-vline store sets the vline ordering and vloadstore handles the reg ew
        conversion via remap_reg_ew.
        """
        vline_bytes = self.params.vline_bytes
        g_addr = addresses.GlobalAddress(bit_addr=vline_addr * 8, params=self.params)
        vline_info = self.tlb.get_vline_info(g_addr)
        old_ordering = vline_info.local_address.ordering
        assert old_ordering is not None
        old_elements = vline_bytes * 8 // old_ordering.ew
        new_elements = vline_bytes * 8 // new_ordering.ew
        temp_regs = self.alloc_temp_regs(1)
        await self.vload(
            temp_regs[0], vline_addr, old_ordering,
            n_elements=old_elements, mask_reg=None, start_index=0,
            parent_span_id=parent_span_id, emul=1)
        await self.vstore(
            temp_regs[0], vline_addr, new_ordering,
            n_elements=new_elements, mask_reg=None, start_index=0,
            parent_span_id=parent_span_id, emul=1)
        await self.free_temp_regs(temp_regs, parent_span_id)

    def _vline_is_partial(self, vline_index: int, elements_per_vline: int,
                          n_elements: int, start_index: int,
                          mask_reg: int | None) -> bool:
        """Check whether a vline will be only partially written/read."""
        if mask_reg is not None:
            return True
        vline_first_element = vline_index * elements_per_vline
        vline_last_element = vline_first_element + elements_per_vline
        return start_index > vline_first_element or \
            start_index + n_elements < vline_last_element

    async def _remap_partial_vlines_for_store(
            self, addr: int, ordering: addresses.Ordering, emul: int,
            n_elements: int, start_index: int, mask_reg: int | None,
            parent_span_id: int):
        """Remap partial vlines with ew mismatch before a unit-stride store."""
        vline_bytes = self.params.vline_bytes
        elements_per_vline = vline_bytes * 8 // ordering.ew
        for i in range(emul):
            vline_addr = addr + i * vline_bytes
            if not self._vline_is_partial(
                    i, elements_per_vline, n_elements, start_index, mask_reg):
                continue
            g_addr = addresses.GlobalAddress(
                bit_addr=vline_addr * 8, params=self.params)
            page_info = self.tlb.get_page_info(g_addr.get_page())
            if page_info.is_vpu:
                existing = self.tlb.get_vline_info(g_addr).local_address.ordering
                if existing is not None and existing != ordering:
                    await self._remap_vline(
                        vline_addr, ordering, parent_span_id)

    async def _remap_weak_vlines_for_load(
            self, addr: int, ordering: addresses.Ordering, emul: int,
            parent_span_id: int):
        """Remap weakly-ordered vlines with ew mismatch before a unit-stride load."""
        vline_bytes = self.params.vline_bytes
        for i in range(emul):
            vline_addr = addr + i * vline_bytes
            g_addr = addresses.GlobalAddress(
                bit_addr=vline_addr * 8, params=self.params)
            page_info = self.tlb.get_page_info(g_addr.get_page())
            if page_info.is_vpu:
                vline_info = self.tlb.get_vline_info(g_addr)
                existing = vline_info.local_address.ordering
                if (vline_info.weakly_ordered and existing is not None
                        and existing != ordering):
                    await self._remap_vline(
                        vline_addr, ordering, parent_span_id)

    def _set_vline_orderings_unit_stride(self, addr: int, ordering: addresses.Ordering,
                                         emul: int):
        """Set ordering on vlines touched by an aligned unit-stride load/store."""
        vline_bytes = self.params.vline_bytes
        assert addr % vline_bytes == 0
        for i in range(emul):
            vline_addr = addr + i * vline_bytes
            g_addr = addresses.GlobalAddress(
                bit_addr=vline_addr * 8, params=self.params)
            page_info = self.tlb.get_page_info(g_addr.get_page())
            if page_info.is_vpu:
                self.tlb.set_vline_ordering(g_addr, ordering)

    async def vload(self, vd: int, addr: int, ordering: addresses.Ordering,
                    n_elements: int, mask_reg: int | None, start_index: int,
                    parent_span_id: int, emul: int | None = None,
                    stride_bytes: int | None = None) -> addresses.VectorOpResult:
        if n_elements == 0:
            return addresses.VectorOpResult()
        if emul is None:
            emul = self.lmul
        assert emul in (1, 2, 4, 8), f'vload: invalid emul={emul}'
        elements_per_vline = self.params.vline_bytes * 8 // ordering.ew
        vlmax = elements_per_vline * emul
        assert n_elements <= vlmax, (
            f'vload: n_elements={n_elements} exceeds vlmax={vlmax} '
            f'(ew={ordering.ew}, emul={emul})')
        element_bytes = ordering.ew // 8
        is_unit_stride = stride_bytes is None or stride_bytes == element_bytes
        is_aligned = addr % self.params.vline_bytes == 0
        await self.await_vreg_write_pending(vd, emul)
        if is_unit_stride and is_aligned:
            await self._remap_weak_vlines_for_load(
                addr, ordering, emul, parent_span_id)
        for i in range(emul):
            self.vrf_ordering[vd + i] = ordering
        return await unordered.vload(self, vd, addr, ordering, n_elements, mask_reg, start_index,
                                     parent_span_id, stride_bytes)

    async def vstore(self, vs: int, addr: int, ordering: addresses.Ordering,
                     n_elements: int, mask_reg: int | None, start_index: int,
                     parent_span_id: int, emul: int | None = None,
                     stride_bytes: int | None = None) -> addresses.VectorOpResult:
        if n_elements == 0:
            return addresses.VectorOpResult()
        if emul is None:
            emul = self.lmul
        element_bytes = ordering.ew // 8
        is_unit_stride = stride_bytes is None or stride_bytes == element_bytes
        is_aligned = addr % self.params.vline_bytes == 0
        await self.await_vreg_write_pending(vs, emul)
        if is_unit_stride and is_aligned:
            await self._remap_partial_vlines_for_store(
                addr, ordering, emul, n_elements, start_index, mask_reg,
                parent_span_id)
            self._set_vline_orderings_unit_stride(addr, ordering, emul)
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

    async def vslide(self, vd: int, vs2: int,
                     offset: int, direction: 'vregister.SlideDirection',
                     start_index: int, n_elements: int,
                     data_ew: int,
                     word_order: addresses.WordOrder, vlmax: int,
                     mask_reg: int | None, parent_span_id: int) -> int:
        """Execute vslideup / vslidedown. Returns sync_ident."""
        return await vregister.vslide(self, vd, vs2, offset, direction,
                                      start_index, n_elements, data_ew,
                                      word_order, vlmax, mask_reg, parent_span_id)


    def update(self):
        for kamlet in self.kamlets:
            kamlet.update()
        for memlet in self.memlets:
            memlet.update()
        self.scalar.update()
        for queue in self._send_queues.values():
            queue.update()
        for buf in self._receive_buffers:
            buf.update()
        for buf in self._send_word_buffers:
            buf.update()

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
        self.clock.create_task(self.monitor_waiting_items())
        self.clock.create_task(self.monitor_channel1andup())
        self.clock.create_task(self.monitor_instruction_buffer())
        self.clock.create_task(self._monitor_instruction_buffer_state())
        self.clock.create_task(self._send_packets_ch0())
        self.clock.create_task(self._send_packets_ch1andup())
        self.clock.create_task(ordered.ordered_buffer_process(self))
        self.clock.create_task(self.scalar.cleanup_might_touch())

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
            dt.check_instruction(disasm_trace, self.pc, inst_hex, inst_str)

        try:
            await instruction.update_state(self)
        except Exception:
            logger.error(f'Exception at pc={hex(self.pc)} instruction={inst_str}')
            raise

    async def run_instructions(self, disasm_trace=None):
        while not self.finished:

            await self.clock.next_cycle
            logger.debug(f'{self.clock.cycle}: run_instructions: about to run first instruction')
            await self.run_instruction(disasm_trace)
            logger.debug(f'{self.clock.cycle}: run_instructions: about to run second instruction')
            await self.run_instruction(disasm_trace)

    async def handle_vreduction_instr(self, op, dst, src_vector, src_scalar_reg, mask_reg,
                                     n_elements, src_ew, accum_ew, word_order, vlmax,
                                     parent_span_id):
        """Handle vector reduction instruction via tree reduction."""
        await reduction.handle_vreduction_instr(
            self, op, dst, src_vector, src_scalar_reg, mask_reg,
            n_elements, src_ew, accum_ew, word_order, vlmax, parent_span_id,
        )

