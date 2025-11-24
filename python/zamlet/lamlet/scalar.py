import logging

from zamlet.runner import Clock
from zamlet.params import LamletParams
from zamlet.register_file_slot import RegisterFileSlot


logger = logging.getLogger(__name__)


class ScalarState:

    def __init__(self, clock: Clock, params: LamletParams):
        self.clock = clock
        self.params = params
        self._rf = [RegisterFileSlot(clock, params, f'x{i}') for i in range(32)]
        self._frf = [RegisterFileSlot(clock, params, f'f{i}') for i in range(32)]

        self.memory = {}
        self.csr = {}

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
