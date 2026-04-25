import logging
import random
from collections import defaultdict
from typing import List, Optional

from zamlet.runner import Clock, Future
from zamlet.params import ZamletParams
from zamlet.monitor import Monitor
from zamlet.register_file_slot import RegisterFileSlot
from zamlet.synchronization import Synchronizer
from zamlet.trap import CSR_MSTATUS, CSR_MTVEC, CSR_MEPC, CSR_MCAUSE, CSR_MTVAL


logger = logging.getLogger(__name__)


class ScalarState:

    def __init__(self, clock: Clock, params: ZamletParams, monitor: Monitor,
                 synchronizer: Optional[Synchronizer] = None):
        self.clock: Clock = clock
        self.params: ZamletParams = params
        self.monitor: Monitor = monitor
        self.synchronizer: Optional[Synchronizer] = synchronizer
        self._rf: List[RegisterFileSlot] = [
            RegisterFileSlot(clock, params, f'x{i}', monitor) for i in range(32)]
        self._frf: List[RegisterFileSlot] = [
            RegisterFileSlot(clock, params, f'f{i}', monitor) for i in range(32)]

        self._memory: dict[int, int] = {}
        # Set of page-aligned addresses for non-idempotent pages
        self._non_idempotent_pages: set[int] = set()
        # Access logs for non-idempotent memory only
        self.non_idempotent_access_log: list[int] = []
        self.non_idempotent_write_log: list[int] = []
        self.csr = {}
        # Initialize read-only vector CSRs
        # vlenb (0xc22) = VLEN/8 = vline_bytes
        self.csr[0xc22] = params.vline_bytes.to_bytes(params.word_bytes, 'little')
        zero = bytes(params.word_bytes)
        for trap_csr in (CSR_MSTATUS, CSR_MTVEC, CSR_MEPC, CSR_MCAUSE, CSR_MTVAL):
            self.csr[trap_csr] = zero

        # Scalar memory ordering state
        self.pending_known_reads: dict[int, int] = defaultdict(int)
        self.pending_known_writes: dict[int, int] = defaultdict(int)
        # sync_ident -> writeset_ident
        self.might_touch_reads: dict[int, int] = {}
        self.might_touch_writes: dict[int, int] = {}

    def register_known_read(self, writeset_ident: int):
        self.pending_known_reads[writeset_ident] += 1

    def register_known_write(self, writeset_ident: int):
        self.pending_known_writes[writeset_ident] += 1

    def register_might_touch_read(self, sync_ident: int, writeset_ident: int):
        self.might_touch_reads[sync_ident] = writeset_ident

    def register_might_touch_write(self, sync_ident: int, writeset_ident: int):
        self.might_touch_writes[sync_ident] = writeset_ident

    async def cleanup_might_touch(self):
        """Coroutine that runs every cycle, removing completed might-touch entries."""
        while True:
            await self.clock.next_cycle
            if self.synchronizer is not None:
                for sync_ident in list(self.might_touch_reads.keys()):
                    if self.synchronizer.is_complete(sync_ident):
                        del self.might_touch_reads[sync_ident]
                for sync_ident in list(self.might_touch_writes.keys()):
                    if self.synchronizer.is_complete(sync_ident):
                        del self.might_touch_writes[sync_ident]

    def has_conflicting_writes(self, writeset_ident: int | None) -> bool:
        for ws_id, count in self.pending_known_writes.items():
            if count > 0 and ws_id != writeset_ident:
                return True
        for sync_ident, ws_id in self.might_touch_writes.items():
            if ws_id != writeset_ident:
                return True
        return False

    def has_conflicting_reads(self, writeset_ident: int | None) -> bool:
        for ws_id, count in self.pending_known_reads.items():
            if count > 0 and ws_id != writeset_ident:
                return True
        for sync_ident, ws_id in self.might_touch_reads.items():
            if ws_id != writeset_ident:
                return True
        return False

    def regs_ready(self, dst_reg, dst_freg, src_regs, src_fregs):
        dst_reg_ready = dst_reg is None or dst_reg == 0 or self._rf[dst_reg].can_write()
        dst_freg_ready = dst_freg is None or self._frf[dst_freg].can_write()
        src_regs_ready = all(not self._rf[r].updating() for r in src_regs if r != 0)
        src_fregs_ready = all(not self._frf[fr].updating() for fr in src_fregs)
        return dst_reg_ready and dst_freg_ready and src_regs_ready and src_fregs_ready

    async def wait_all_regs_ready(self, dst_reg, dst_freg, src_regs, src_fregs):
        while not self.regs_ready(dst_reg, dst_freg, src_regs, src_fregs):
            await self.clock.next_cycle

    def read_reg(self, reg_num):
        if reg_num == 0:
            return bytes([0]*8)
        return self._rf[reg_num].get_value()

    def read_freg(self, freg_num):
        return self._frf[freg_num].get_value()

    def write_reg(self, reg_num: int, value: bytes, span_id: int) -> None:
        assert isinstance(value, bytes)
        assert len(value) == 8
        self._rf[reg_num].set_value(value, span_id)

    def write_freg(self, freg_num: int, value: bytes, span_id: int) -> None:
        assert isinstance(value, bytes)
        assert len(value) == 8
        self._frf[freg_num].set_value(value, span_id)

    def write_reg_future(self, reg_num: int, future: Future, span_id: int) -> None:
        self._rf[reg_num].set_future(future, span_id)

    def write_freg_future(self, freg_num: int, future: Future, span_id: int) -> None:
        self._frf[freg_num].set_future(future, span_id)

    def register_non_idempotent_page(self, page_addr: int):
        """Register a page as non-idempotent. page_addr must be page-aligned."""
        assert page_addr % self.params.page_bytes == 0
        self._non_idempotent_pages.add(page_addr)

    def _is_non_idempotent(self, address: int) -> bool:
        """Check if address falls in a non-idempotent page."""
        page_addr = (address // self.params.page_bytes) * self.params.page_bytes
        return page_addr in self._non_idempotent_pages

    async def set_memory(self, address: int, data: bytes,
                         writeset_ident: int | None = None, known: bool = False,
                         allow_wait: bool = False):
        """Write to scalar memory."""
        if allow_wait:
            while (self.has_conflicting_reads(writeset_ident)
                   or self.has_conflicting_writes(writeset_ident)):
                await self.clock.next_cycle
        else:
            assert not self.has_conflicting_reads(writeset_ident), (
                f'set_memory: conflicting reads addr=0x{address:x} ws={writeset_ident} '
                f'known_r={dict(self.pending_known_reads)} '
                f'mt_r={dict(self.might_touch_reads)}')
            assert not self.has_conflicting_writes(writeset_ident), (
                f'set_memory: conflicting writes addr=0x{address:x} ws={writeset_ident} '
                f'known_w={dict(self.pending_known_writes)} '
                f'mt_w={dict(self.might_touch_writes)}')
        if self._is_non_idempotent(address):
            self.non_idempotent_write_log.append(address)
        for i, b in enumerate(data):
            self._memory[address + i] = b
        if known:
            assert writeset_ident is not None
            self.pending_known_writes[writeset_ident] -= 1
            assert self.pending_known_writes[writeset_ident] >= 0

    async def get_memory(self, address: int, size: int = 1,
                         writeset_ident: int | None = None,
                         known: bool = False, allow_wait: bool = False) -> bytes:
        """Read from scalar memory."""
        if allow_wait:
            logged = False
            while self.has_conflicting_writes(writeset_ident):
                if not logged:
                    logger.debug(
                        f'get_memory waiting: addr=0x{address:x} ws={writeset_ident} '
                        f'known_w={dict(self.pending_known_writes)} '
                        f'mt_w={dict(self.might_touch_writes)}')
                    logged = True
                await self.clock.next_cycle
        else:
            assert not self.has_conflicting_writes(writeset_ident), (
                f'get_memory: conflicting writes addr=0x{address:x} ws={writeset_ident} '
                f'known_w={dict(self.pending_known_writes)} '
                f'mt_w={dict(self.might_touch_writes)}')
        if self._is_non_idempotent(address):
            self.non_idempotent_access_log.append(address)
        bs = []
        for index in range(size):
            addr = address + index
            if addr not in self._memory:
                # FIXME: Make this deterministic by using a seeded RNG
                self._memory[addr] = random.randint(0, 255)
            bs.append(self._memory[addr])
        if known:
            assert writeset_ident is not None
            self.pending_known_reads[writeset_ident] -= 1
            assert self.pending_known_reads[writeset_ident] >= 0
        return bytes(bs)

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
