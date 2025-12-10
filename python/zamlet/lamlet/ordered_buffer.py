"""
Ordered buffer for indexed load/store operations.

Tracks element-by-element processing for ordered indexed operations
(vloxei/vsoxei) where memory accesses must happen in element order.

Uses a circular buffer model where slots are released when elements complete.
"""

from dataclasses import dataclass, field


@dataclass
class OrderedBuffer:
    """
    Buffer for ordered indexed loads and stores.

    For loads (scalar memory): pending stores (scalar_addr, header) when READ_MEM_WORD_REQ arrives
    For loads (VPU memory): slot released via LOAD_INDEXED_ELEMENT_RESP (no pending entry)
    For stores: pending stores (addr, data) when STORE_INDEXED_ELEMENT_RESP arrives
    """
    buffer_id: int
    n_elements: int
    is_load: bool

    next_to_dispatch: int = 0
    next_to_process: int = 0
    base_index: int = 0

    pending: dict = field(default_factory=dict)
    completed: set = field(default_factory=set)

    vpu_write_pending: bool = False

    def can_dispatch(self, capacity: int) -> bool:
        """Check if we can dispatch another element."""
        if self.next_to_dispatch >= self.n_elements:
            return False
        return self.next_to_dispatch - self.base_index < capacity

    def dispatch_complete(self) -> bool:
        """Check if all elements have been dispatched."""
        return self.next_to_dispatch >= self.n_elements

    def all_complete(self) -> bool:
        """Check if all elements have completed."""
        return self.base_index >= self.n_elements

    def add_pending(self, element_index: int, payload):
        """Record a pending request/write."""
        assert element_index not in self.pending
        self.pending[element_index] = payload

    def get_next_pending(self):
        """Get the next pending item (in element order), or None."""
        if self.next_to_process not in self.pending:
            return None
        return self.pending.pop(self.next_to_process)

    def mark_completed(self, element_index: int):
        """Mark an element as completed and advance base_index if possible."""
        self.completed.add(element_index)
        while self.base_index in self.completed:
            self.completed.remove(self.base_index)
            self.base_index += 1
