import logging
from typing import List

from zamlet.runner import Future


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
        self.has_next_future = False

        # Some messages don't need a response
        # We just give the header ident=0
        # And don't register them here.

    def updating(self):
        return (self.future is not None) or ((self.has_next_future) and (self.next_future is not None)) or self.has_next_value

    def can_write(self):
        return (not self.has_next_future) and (not self.has_next_value)

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


class KamletRegisterFile:

    def __init__(self, n_regs: int, name: str = ""):
        self.name = name
        self.reads: List[List[int]] = [[] for i in range(n_regs)]
        self.write: List[int|None] = [None for i in range(n_regs)]
        self._next_token = 0

    def get_token(self) -> int:
        token = self._next_token
        self._next_token += 1
        return token

    def can_read(self, reg: int) -> bool:
        value = self.write[reg] is None
        #logger.info(f'Can read {self.name} is {value}')
        return value

    def finish(self, token: int, write_regs: List[int]|None = None, read_regs: List[int]|None = None) -> None:
        if read_regs is None:
            read_regs = []
        if write_regs is None:
            write_regs = []
        for reg in read_regs:
            assert token in self.reads[reg]
            self.reads[reg].remove(token)
        for reg in write_regs:
            assert self.write[reg] == token
            self.write[reg] = None
        logger.debug(f'{self.name} RF FINISH token={token} read_regs={read_regs} write_regs={write_regs}')

    def start(self, read_regs: List[int]|None=None, write_regs: List[int]|None=None) -> int:
        token = self.get_token()
        if read_regs is None:
            read_regs = []
        if write_regs is None:
            write_regs = []
        for reg in read_regs:
            assert self.can_read(reg), f"Cannot read reg {reg}, write lock held by {self.write[reg]}"
            self.reads[reg].append(token)
        for reg in write_regs:
            if not self.can_write(reg):
                logger.error(f'LOCK VIOLATION: Cannot write reg {reg}, write={self.write[reg]}, reads={self.reads[reg]}')
            assert self.can_write(reg), f"Cannot write reg {reg}, write={self.write[reg]}, reads={self.reads[reg]}"
            self.write[reg] = token
        logger.debug(f'{self.name} RF START token={token} read_regs={read_regs} write_regs={write_regs}')
        return token

    def start_read(self, reg: int) -> int:
        assert self.can_read(reg)
        token = self.get_token()
        self.reads[reg].append(token)
        #logger.info(f'Staring a read of {self.name} token={token}')
        return token

    def start_reads(self, regs: List[int]) -> int:
        token = self.get_token()
        for reg in regs:
            assert self.can_read(reg)
            self.reads[reg].append(token)
        return token

    def finish_read(self, reg: int, token: int) -> None:
        assert token in self.reads[reg]
        self.reads[reg].remove(token)
        #logger.info(f'Finishing a read of {self.name} token={token}')

    def finish_reads(self, regs: List[int], token: int) -> None:
        for reg in regs:
            assert token in self.reads[reg]
            self.reads[reg].remove(token)

    def can_write(self, reg: int, token: int|None=None) -> bool:
        if self.write[reg] is None:
            value = not self.reads[reg]
        else:
            value = self.write[reg] == token
        return value

    def start_write(self, reg: int) -> int:
        assert self.can_write(reg)
        token = self.get_token()
        self.write[reg] = token
        #logger.info(f'Staring a write of {self.name} token={token}')
        return token

    def start_writes(self, regs: List[int]) -> int:
        token = self.get_token()
        for reg in regs:
            assert self.can_write(reg)
            self.write[reg] = token
        return token

    def finish_write(self, reg: int, token: int) -> None:
        assert self.write[reg] == token
        self.write[reg] = None
        #logger.info(f'Finishing a write of {self.name} token={token}')

    def finish_writes(self, regs: List[int], token: int) -> None:
        for reg in regs:
            self.finish_write(reg, token)
