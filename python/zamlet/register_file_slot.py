import logging
from typing import List, Optional

from zamlet.runner import Clock, Future
from zamlet.params import ZamletParams
from zamlet.monitor import Monitor


logger = logging.getLogger(__name__)


class RegisterFileSlot:

    def __init__(self, clock: Clock, params: ZamletParams, name: str, monitor: Monitor):
        self.clock: Clock = clock
        self.params: ZamletParams = params
        self.name: str = name
        self.monitor: Monitor = monitor
        self.value: bytes = bytes([0]*8)
        self.next_value: Optional[bytes] = None
        self.has_next_value: bool = False
        # This is a future that when it is resolved will
        # update the contents of the register file.
        self.future: Optional[Future] = None
        self.next_future: Optional[Future] = None
        self.has_next_future: bool = False
        # Span to annotate on the next update() commit (set at staging time).
        # None means no write is currently staged.
        self.next_span_id: Optional[int] = None
        # Span captured when set_future() was called, carried through
        # apply_future into next_span_id when the future resolves.
        self.pending_future_span_id: Optional[int] = None

        # Some messages don't need a response
        # We just give the header ident=0
        # And don't register them here.

    def updating(self) -> bool:
        return (self.future is not None) or ((self.has_next_future) and (self.next_future is not None)) or self.has_next_value

    def can_write(self) -> bool:
        return (not self.has_next_future) and (not self.has_next_value)

    def get_value(self) -> bytes:
        assert not self.updating()
        as_int = int.from_bytes(self.value, byteorder='little', signed=True)
        logger.debug(f'read_reg: {self.name} = 0x{as_int:016x}')
        return self.value

    def set_value(self, value: bytes, span_id: int) -> None:
        assert not self.has_next_value
        assert not self.has_next_future
        assert self.future is None
        assert isinstance(value, bytes)
        assert len(value) == 8
        self.has_next_value = True
        self.next_value = value
        self.next_span_id = span_id
        as_int = int.from_bytes(value, byteorder='little', signed=True)
        logger.debug(f'write_reg: {self.name} = 0x{as_int:016x}')

    def set_future(self, future: Future, span_id: int) -> None:
        assert not self.has_next_future
        self.has_next_future = True
        self.next_future = future
        self.pending_future_span_id = span_id

    async def apply_future(self, future: Future) -> None:
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
            self.next_span_id = self.pending_future_span_id
            logger.debug(f'write_reg: {self.name} = 0x{int_value:016x}')
        else:
            logger.debug(f'write_reg: {self.name} = 0x{int_value:016x} wont apply overwritten')

    def update(self) -> None:
        if self.has_next_value:
            old_value = self.value
            self.value = self.next_value
            self.monitor.add_event(
                self.next_span_id, 'scalar_write',
                reg=self.name,
                old=old_value.hex(), new=self.next_value.hex(),
            )
            self.next_span_id = None
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
            assert token in self.reads[reg], (
                f"{self.name} RF FINISH failed: token={token} not in reads[{reg}]={self.reads[reg]}. "
                f"Trying to finish read_regs={read_regs} write_regs={write_regs}"
            )
            self.reads[reg].remove(token)
        for reg in write_regs:
            assert self.write[reg] == token, (
                f"{self.name} RF FINISH failed: write[{reg}]={self.write[reg]} != token={token}. "
                f"Trying to finish read_regs={read_regs} write_regs={write_regs}"
            )
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
