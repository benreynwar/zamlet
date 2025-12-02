from typing import Any


class WaitingItem:

    cache_is_write = False
    cache_is_read = False
    reads_all_memory = False
    writes_all_memory = False

    def __init__(self, item: Any, instr_ident: int|None=None, rf_ident: int|None=None):
        self.item = item
        self.instr_ident = instr_ident
        self.rf_ident = rf_ident
        self.cache_slot: int|None = None

    def ready(self) -> bool:
        '''Return True when transaction is complete and witem can be finalized.'''
        raise NotImplementedError()

    async def monitor_jamlet(self, jamlet: 'Jamlet') -> None:
        '''Called each cycle by jamlet. Override to send messages, handle retries, etc.'''
        pass

    async def monitor_kamlet(self, kamlet: 'Kamlet') -> None:
        '''Called each cycle by kamlet. Override for kamlet-level monitoring.'''
        pass

    async def finalize(self, kamlet: 'Kamlet') -> None:
        '''Called when ready() returns True. Override to release RF locks, cleanup, etc.'''
        pass


class WaitingItemRequiresCache(WaitingItem):

    def __init__(self, item: Any, instr_ident: int|None=None,
                 cache_slot: int|None=None, cache_is_avail: bool=False,
                 writeset_ident: int|None=None, rf_ident: int|None=None):
        super().__init__(item, instr_ident, rf_ident)
        self.cache_slot = cache_slot
        self.cache_is_avail = cache_is_avail
        self.writeset_ident = writeset_ident
        assert self.cache_is_write or self.cache_is_read
        assert not (self.cache_is_write and self.cache_is_read)

    def set_cache_slot(self, slot):
        assert not self.cache_is_avail
        assert self.cache_slot is None
        self.cache_slot = slot

    def ready(self):
        return self.cache_is_avail
