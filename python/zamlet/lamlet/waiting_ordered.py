"""
Waiting items for ordered indexed load/store operations at the lamlet level.

These are per-element waiting items that map an element's instr_ident back to the
buffer_id and element_index, so responses can update the correct buffer slot.
"""

from zamlet.waiting_item import WaitingItem


class LamletWaitingLoadIndexedElement(WaitingItem):
    """Per-element waiting item for ordered indexed load."""

    def __init__(self, instr_ident: int, buffer_id: int, element_index: int):
        super().__init__(item=None, instr_ident=instr_ident)
        self.buffer_id = buffer_id
        self.element_index = element_index

    def ready(self) -> bool:
        return False


class LamletWaitingStoreIndexedElement(WaitingItem):
    """Per-element waiting item for ordered indexed store."""

    def __init__(self, instr_ident: int, buffer_id: int, element_index: int):
        super().__init__(item=None, instr_ident=instr_ident)
        self.buffer_id = buffer_id
        self.element_index = element_index

    def ready(self) -> bool:
        return False
