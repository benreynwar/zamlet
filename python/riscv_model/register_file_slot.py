import logging

from runner import Future


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


class KamletRegisterFileSlot:

    def __init__(self, name):
        self.name = name
        self.reads = []
        self.write = None
        self._next_token = 0

    def get_token(self):
        token = self._next_token
        self._next_token += 1
        return token

    def can_read(self):
        value = self.write is None
        #logger.info(f'Can read {self.name} is {value}')
        return value

    def start_read(self):
        assert self.can_read()
        token = self.get_token()
        self.reads.append(token)
        #logger.info(f'Staring a read of {self.name} token={token}')
        return token

    def finish_read(self, token):
        assert token in self.reads
        self.reads.remove(token)
        #logger.info(f'Finishing a read of {self.name} token={token}')

    def can_write(self):
        value = self.write is None and not self.reads
        #logger.info(f'Can write {self.name} is {value}')
        return value

    def start_write(self):
        assert self.can_write()
        token = self.get_token()
        self.write = token
        #logger.info(f'Staring a write of {self.name} token={token}')
        return token

    def finish_write(self, token):
        assert self.write == token
        self.write = None
        #logger.info(f'Finishing a write of {self.name} token={token}')

