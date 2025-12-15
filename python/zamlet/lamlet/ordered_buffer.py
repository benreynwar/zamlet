"""
Ordered buffer for indexed load/store operations.

Tracks element-by-element processing for ordered indexed operations
(vloxei/vsoxei) where memory accesses must happen in element order.

Uses per-element state machine with a circular buffer of fixed capacity.
"""

from dataclasses import dataclass
from enum import Enum


from zamlet.addresses import GlobalAddress


class ElementState(str, Enum):
    DISPATCHED = "DISPATCHED"      # Sent to kamlet, waiting for addr/data to arrive
    READY = "READY"                # Have addr/data, waiting for turn (element order)
    IN_FLIGHT = "IN_FLIGHT"        # VPU writes sent, waiting for RESPs
    COMPLETE = "COMPLETE"          # Done


@dataclass
class ElementEntry:
    state: ElementState
    instr_ident: int
    addr: GlobalAddress | None = None
    data: bytes | None = None      # Stores only
    tag: int | None = None         # Tag from request (loads)


class OrderedBuffer:
    """
    Circular buffer for ordered indexed loads and stores.

    State transitions:
    - Load (scalar): DISPATCHED -> READY -> COMPLETE
    - Load (VPU): DISPATCHED -> COMPLETE (handled by kamlet)
    - Store (scalar): DISPATCHED -> READY -> COMPLETE
    - Store (VPU): DISPATCHED -> READY -> IN_FLIGHT -> COMPLETE
    """

    def __init__(self, buffer_id: int, n_elements: int, is_load: bool, capacity: int,
                 data_ew: int):
        self.buffer_id = buffer_id
        self.n_elements = n_elements
        self.is_load = is_load
        self.capacity = capacity
        self.data_ew = data_ew

        # next_to_dispatch: next element index to send to kamlet
        # next_to_process: next element index to process in order (for scalar reads/writes)
        # base_index: oldest non-complete element (for circular buffer cleanup)
        self.next_to_dispatch = 0
        self.next_to_process = 0
        self.base_index = 0

        # First element that faulted (None if no fault)
        self.faulted_element: int | None = None

        self.elements: list[ElementEntry | None] = [None] * capacity

    def _slot(self, element_index: int) -> int:
        return element_index % self.capacity

    def get_entry(self, element_index: int) -> ElementEntry | None:
        """Get the entry for an element index."""
        return self.elements[self._slot(element_index)]

    def can_dispatch(self) -> bool:
        """Check if we can dispatch another element."""
        if self.next_to_dispatch >= self.n_elements:
            return False
        return self.next_to_dispatch - self.base_index < self.capacity

    def all_complete(self) -> bool:
        """Check if all elements have completed."""
        return self.base_index >= self.n_elements

    def add_dispatched(self, instr_ident: int):
        """Record that the next element has been dispatched. Returns element_index."""
        element_index = self.next_to_dispatch
        slot = self._slot(element_index)
        assert self.elements[slot] is None
        self.elements[slot] = ElementEntry(state=ElementState.DISPATCHED, instr_ident=instr_ident)
        self.next_to_dispatch += 1
        return element_index

    def complete_element(self, element_index: int):
        """Mark element as complete and clean up circular buffer."""
        slot = self._slot(element_index)
        entry = self.elements[slot]
        assert entry is not None
        entry.state = ElementState.COMPLETE
        entry.addr = None
        entry.data = None

        # Advance next_to_process past any completed elements
        while self.next_to_process < self.n_elements:
            next_slot = self._slot(self.next_to_process)
            next_entry = self.elements[next_slot]
            if next_entry is None or next_entry.state != ElementState.COMPLETE:
                break
            self.next_to_process += 1

        # Clean up completed elements from the base
        while self.base_index < self.n_elements:
            base_slot = self._slot(self.base_index)
            base_entry = self.elements[base_slot]
            if base_entry is None or base_entry.state != ElementState.COMPLETE:
                break
            self.elements[base_slot] = None
            self.base_index += 1
