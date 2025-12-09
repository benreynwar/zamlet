'''
Ordered Element Buffer

A bounded buffer for tracking elements in ordered indexed operations.
Used by both lamlet (scalar memory) and jamlet (VPU memory) to ensure
correct ordering when multiple elements may write to overlapping addresses.

For ordered stores (vsoxei): higher element indices win on address conflicts.
For ordered loads (vloxei): ensures scalar memory reads happen in element order.

The buffer is reused across iterations. Each iteration:
- Uses min_element_index to ignore already-processed elements
- Tracks new elements, evicting highest when full
- Records min_untracked for sync
- After apply phase, updates min_element_index from min_untracked
'''

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class BufferedElement:
    """A single buffered element for ordered operations."""
    element_index: int
    address: int
    data: Optional[bytes]  # None for loads until data is read
    header: Any  # Original request header for sending response


class OrderedElementBuffer:
    """
    A bounded buffer for ordered indexed operations.

    Tracks incoming elements and evicts higher-indexed elements when full.
    After sync, elements are processed in order (lowest index first).

    The buffer slot is reused across iterations - call prepare_next_iteration()
    after each apply phase to update min_element_index.

    Attributes:
        instr_ident: The instruction identifier
        capacity: Maximum number of elements to track
        min_element_index: Ignore elements below this (updated each iteration)
        elements: Dict mapping element_index to BufferedElement
        min_untracked: Lowest index that couldn't be tracked (None if all fit)
    """

    def __init__(self, instr_ident: int, capacity: int):
        self.instr_ident = instr_ident
        self.capacity = capacity
        self.min_element_index = 0
        self.elements: Dict[int, BufferedElement] = {}
        self.min_untracked: Optional[int] = None

    def add_element(self, element_index: int, address: int, data: Optional[bytes],
                    header: Any) -> bool:
        """
        Add an element to the buffer.

        Elements with index < min_element_index are ignored (already processed).
        If buffer is full, evicts the highest-indexed element if the new element
        has a lower index. Updates min_untracked to track evicted elements.

        Returns True if element was added, False if ignored or rejected.
        """
        # Ignore already-processed elements
        if element_index < self.min_element_index:
            return False

        elem = BufferedElement(
            element_index=element_index,
            address=address,
            data=data,
            header=header,
        )

        if len(self.elements) < self.capacity:
            self.elements[element_index] = elem
            return True

        # Buffer full - find highest index currently tracked
        max_idx = max(self.elements.keys())

        if element_index < max_idx:
            # New element has lower index - evict highest
            evicted = self.elements.pop(max_idx)
            if self.min_untracked is None or evicted.element_index < self.min_untracked:
                self.min_untracked = evicted.element_index
            self.elements[element_index] = elem
            return True
        else:
            # New element has highest index - reject it
            if self.min_untracked is None or element_index < self.min_untracked:
                self.min_untracked = element_index
            return False

    def get_elements_in_order(self) -> List[BufferedElement]:
        """Return all buffered elements sorted by element_index ascending."""
        return sorted(self.elements.values(), key=lambda e: e.element_index)

    def prepare_next_iteration(self) -> None:
        """Prepare for next iteration after apply phase.

        Updates min_element_index from min_untracked and clears elements.
        """
        if self.min_untracked is not None:
            self.min_element_index = self.min_untracked
        self.elements.clear()
        self.min_untracked = None

    def is_complete(self) -> bool:
        """Returns True if all elements fit (no more iterations needed)."""
        return self.min_untracked is None

    def reset(self) -> None:
        """Fully reset the buffer for reuse with a new operation."""
        self.instr_ident = 0
        self.min_element_index = 0
        self.elements.clear()
        self.min_untracked = None

    def __len__(self) -> int:
        return len(self.elements)
