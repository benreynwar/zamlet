import logging
import random

from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.register_file_slot import RegisterFileSlot


logger = logging.getLogger(__name__)


class ScalarState:

    def __init__(self, clock: Clock, params: ZamletParams):
        self.clock = clock
        self.params = params
        self._rf = [RegisterFileSlot(clock, params, f'x{i}') for i in range(32)]
        self._frf = [RegisterFileSlot(clock, params, f'f{i}') for i in range(32)]

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

    def register_non_idempotent_page(self, page_addr: int):
        """Register a page as non-idempotent. page_addr must be page-aligned."""
        assert page_addr % self.params.page_bytes == 0
        self._non_idempotent_pages.add(page_addr)

    def _is_non_idempotent(self, address: int) -> bool:
        """Check if address falls in a non-idempotent page."""
        page_addr = (address // self.params.page_bytes) * self.params.page_bytes
        return page_addr in self._non_idempotent_pages

    def set_memory(self, address: int, data: bytes):
        """Write to scalar memory."""
        if self._is_non_idempotent(address):
            self.non_idempotent_write_log.append(address)
        for i, b in enumerate(data):
            self._memory[address + i] = b

    def get_memory(self, address: int, size: int = 1) -> bytes:
        """Read from scalar memory."""
        if self._is_non_idempotent(address):
            self.non_idempotent_access_log.append(address)
        bs = []
        for index in range(size):
            addr = address + index
            if addr not in self._memory:
                # FIXME: Make this deterministic by using a seeded RNG
                self._memory[addr] = random.randint(0, 255)
            bs.append(self._memory[addr])
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
