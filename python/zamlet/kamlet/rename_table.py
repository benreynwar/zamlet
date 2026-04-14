"""
Kamlet register rename table.

Each kamlet owns an independent RegisterRenameTable. Lamlet kinstructions
reference vector registers by architectural name; the kamlet renames at
dispatch, pulling a phys from its free queue for each destination and looking
up the current phys for each source. The scoreboard sees phys indices.

Arch names are split in two bands:

  - Names 0..N_ARCH_VREGS-1 are ISA arch regs (always mapped on init).
  - Names N_ARCH_VREGS..n_vregs-1 are scratch names used by compound lamlet
    ops. They start unmapped; their phys slots sit in the free queue. A
    kinstr writing a scratch arch calls `allocate_write` which maps it; a
    `FreeRegister(arch)` kinstr calls `free_register` which unmaps it and
    returns the phys to the free queue tail.
"""

from collections import deque
from typing import List

from zamlet.params import ZamletParams


class RegisterRenameTable:
    """Arch -> phys mapping plus a free queue of unmapped phys regs.

    Invariant: every phys reg in [0, n_phys) is either currently mapped by
    some arch[i] (with valid[i] True), in the real free_queue, or in
    pending_free (rotated out but not yet safe to reuse). The sum of
    (live arch mappings) + len(free_queue) + len(pending_free) == n_phys.

    With out-of-order execution, a phys rotated out of the rename table
    may still be referenced by an older, not-yet-dispatched reservation
    station entry. Such pregs go to `pending_free` (a set — drain order
    doesn't matter) instead of going straight back to `free_queue`. A
    caller drains pending pregs each cycle via `drain_pending` with a
    callback that decides whether each preg is now idle (no RF locks,
    no station references).
    """

    N_ARCH_VREGS = 32

    def __init__(self, params: ZamletParams):
        n_phys = params.n_vregs
        assert n_phys > self.N_ARCH_VREGS, \
            f"params.n_vregs={n_phys} must be > {self.N_ARCH_VREGS}"
        self.n_phys = n_phys
        # arch[i] is the phys currently mapped to arch index i. Only
        # meaningful where valid[i] is True.
        self.arch: List[int] = list(range(n_phys))
        self.valid: List[bool] = [True] * self.N_ARCH_VREGS + \
            [False] * (n_phys - self.N_ARCH_VREGS)
        self.free_queue: deque[int] = deque(range(self.N_ARCH_VREGS, n_phys))
        self.pending_free: set[int] = set()

    def is_mapped(self, arch_reg: int) -> bool:
        """Return True if arch_reg currently has a phys mapping.

        Scratch arches in [N_ARCH_VREGS, n_phys) start unmapped and become
        mapped on first write (allocate_write); FreeRegister unmaps them
        again. ISA arches in [0, N_ARCH_VREGS) are always mapped.
        """
        assert 0 <= arch_reg < self.n_phys, \
            f"arch_reg={arch_reg} out of range [0, {self.n_phys})"
        return self.valid[arch_reg]

    def lookup_read(self, arch_reg: int) -> int:
        """Return the phys reg currently mapped to arch_reg."""
        assert 0 <= arch_reg < self.n_phys, \
            f"arch_reg={arch_reg} out of range [0, {self.n_phys})"
        assert self.valid[arch_reg], \
            f"lookup_read on unmapped arch_reg={arch_reg}"
        return self.arch[arch_reg]

    def allocate_write(self, arch_reg: int) -> int:
        """Assign a fresh phys to arch_reg and return it.

        If arch_reg was previously mapped, its old phys goes to the
        pending_free set — older reservation station entries may still
        reference it. The drain_pending callback releases it to the real
        free_queue once no references remain. allocate_write only pulls
        from the real free_queue.
        """
        assert 0 <= arch_reg < self.n_phys, \
            f"arch_reg={arch_reg} out of range [0, {self.n_phys})"
        if self.valid[arch_reg]:
            old_phys = self.arch[arch_reg]
            assert old_phys not in self.free_queue, \
                f"arch[{arch_reg}]={old_phys} was already in free_queue"
            assert old_phys not in self.pending_free, \
                f"arch[{arch_reg}]={old_phys} was already in pending_free"
            self.pending_free.add(old_phys)
        assert len(self.free_queue) > 0, \
            f"free_queue is empty — cannot allocate for arch_reg={arch_reg}"
        new_phys = self.free_queue.popleft()
        self.arch[arch_reg] = new_phys
        self.valid[arch_reg] = True
        return new_phys

    def free_register(self, arch_reg: int) -> None:
        """Release the phys mapped to arch_reg and mark arch_reg unmapped.

        Invoked by the `FreeRegister` kinstruction handler. Primary use is
        releasing scratch arch indices at the end of a compound lamlet op.

        The phys goes to pending_free rather than free_queue directly —
        older station entries may still reference it. drain_pending
        releases it once idle.

        No-op when arch_reg is already unmapped: the lamlet allocates a
        worst-case batch of scratch arches up front (e.g. vloadstorestride
        allocates 8 temps for the maximum batch size) but a smaller batch
        only writes a subset of them. The unwritten arches were never
        mapped at this kamlet, so their phys never left the free queue and
        FreeRegister has nothing to undo. Letting the lamlet emit
        FreeRegister uniformly for every allocated scratch arch keeps the
        bookkeeping simple.
        """
        assert 0 <= arch_reg < self.n_phys, \
            f"arch_reg={arch_reg} out of range [0, {self.n_phys})"
        if not self.valid[arch_reg]:
            return
        phys = self.arch[arch_reg]
        assert phys not in self.free_queue, \
            f"arch[{arch_reg}]={phys} was already in free_queue"
        assert phys not in self.pending_free, \
            f"arch[{arch_reg}]={phys} was already in pending_free"
        self.valid[arch_reg] = False
        self.pending_free.add(phys)

    def release_pending(self, preg: int) -> None:
        """Move a specific preg from pending_free to free_queue. The
        caller is responsible for deciding when a preg is safe to
        release (no RF locks, no station references).
        """
        assert preg in self.pending_free, \
            f"preg={preg} not in pending_free={self.pending_free}"
        assert preg not in self.free_queue, \
            f"preg={preg} already in free_queue"
        self.pending_free.remove(preg)
        self.free_queue.append(preg)
