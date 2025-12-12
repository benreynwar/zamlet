"""
Waiting items for lamlet-level operations.

These track the dispatched state so IdentQuery knows which idents have been sent to kamlets.
"""

from asyncio import Future

from zamlet.kamlet.cache_table import SendState


class LamletWaitingItem:
    """Base class for lamlet-level waiting items.

    Adds a dispatched flag to track whether the instruction has been sent to kamlets.
    """

    def __init__(self, instr_ident: int):
        self.instr_ident = instr_ident
        self.dispatched: bool = False


class LamletWaitingFuture(LamletWaitingItem):
    """Lamlet-level waiting item for read_byte.

    When a response is received with header.ident matching instr_ident,
    the future is fired.
    """

    def __init__(self, future: Future, instr_ident: int):
        super().__init__(instr_ident=instr_ident)
        self.future = future


class LamletWaitingLoadIndexedElement(LamletWaitingItem):
    """Per-element waiting item for ordered indexed load."""

    def __init__(self, instr_ident: int, buffer_id: int, element_index: int):
        super().__init__(instr_ident=instr_ident)
        self.buffer_id = buffer_id
        self.element_index = element_index


class LamletWaitingStoreIndexedElement(LamletWaitingItem):
    """Per-element waiting item for ordered indexed store.

    For VPU writes, an element may span multiple words (up to element_bytes tags).
    transaction_states tracks each tag's state.
    """

    def __init__(self, instr_ident: int, buffer_id: int, element_index: int, element_bytes: int):
        super().__init__(instr_ident=instr_ident)
        self.buffer_id = buffer_id
        self.element_index = element_index
        self.transaction_states: list[SendState] = [SendState.COMPLETE] * element_bytes

    def all_complete(self) -> bool:
        return all(s == SendState.COMPLETE for s in self.transaction_states)
