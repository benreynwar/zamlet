"""
Waiting items for lamlet-level operations.

These track the dispatched state so IdentQuery knows which idents have been sent to kamlets.
"""

from asyncio import Future

from zamlet import addresses
from zamlet.kamlet import kinstructions
from zamlet.kamlet.cache_table import SendState
from zamlet.lamlet import ident_query


class LamletWaitingItem:
    """Base class for lamlet-level waiting items.

    Adds a dispatched flag to track whether the instruction has been sent to kamlets.

    Items that need post-response async work (e.g. emitting a downstream
    kinstr) override ``monitor_lamlet`` and ``ready``. The lamlet's
    waiting-item monitor coroutine calls ``monitor_lamlet`` each cycle and
    removes the item when ``ready`` returns True. Items that resolve purely
    via the channel-0 response path (scalar futures, indexed load/store) can
    leave these as no-ops and rely on the response handler to remove them.
    """

    def __init__(self, instr_ident: int):
        self.instr_ident = instr_ident
        self.dispatched: bool = False

    async def monitor_lamlet(self, lamlet) -> None:
        """Hook for post-response async work. Default: no-op."""
        return

    def ready(self) -> bool:
        """Return True once the item can be removed from the waiting queue.

        Default False: removal happens in the response handler for items
        that don't use the monitor loop.
        """
        return False


class LamletWaitingFuture(LamletWaitingItem):
    """Lamlet-level waiting item for read_byte.

    When a response is received with header.ident matching instr_ident,
    the future is fired.
    """

    def __init__(self, future: Future, instr_ident: int):
        super().__init__(instr_ident=instr_ident)
        self.future = future


class LamletWaitingReadRegElement(LamletWaitingItem):
    """Waiting item for vmv.x.s (read element from vector register).

    Receives a raw word from the kamlet via READ_REG_WORD_RESP,
    extracts the requested element, sign-extends to XLEN,
    and resolves the future with the scalar register value (bytes).
    """

    def __init__(self, future, instr_ident: int,
                 element_width: int, word_bytes: int, element_byte_offset: int):
        super().__init__(instr_ident=instr_ident)
        self.future = future
        self.element_width = element_width
        self.word_bytes = word_bytes
        self.element_byte_offset = element_byte_offset

    def resolve(self, word: int):
        eb = self.element_width // 8
        raw = word.to_bytes(self.word_bytes, byteorder='little', signed=False)
        element_val = int.from_bytes(
            raw[self.element_byte_offset:self.element_byte_offset + eb],
            byteorder='little', signed=True)
        result = element_val.to_bytes(self.word_bytes, byteorder='little', signed=True)
        self.future.set_result(result)


class LamletWaitingVrgatherBroadcast(LamletWaitingItem):
    """Waiting item for vrgather.vx / vrgather.vi.

    After dispatching a ReadRegWord to fetch vs2[idx], the lamlet keeps one
    of these in its waiting queue. The channel-0 response handler calls
    ``resolve`` to stash the incoming word and flag the item for pickup.
    The waiting-item monitor coroutine then calls ``monitor_lamlet``, which
    appends a VBroadcastOp kinstr to the lamlet instruction buffer (ordered
    after any already-queued kinstrs but before later ones that touch vd)
    and clears the pending-write counter on vd. ``ready()`` then returns
    True so the monitor can drop the item.
    """

    def __init__(self, instr_ident: int, vd: int, n_elements: int,
                 element_width: int, word_order: 'addresses.WordOrder',
                 mask_reg: int | None, src_byte_offset: int, span_id: int):
        super().__init__(instr_ident=instr_ident)
        self.vd = vd
        self.n_elements = n_elements
        self.element_width = element_width
        self.word_order = word_order
        self.mask_reg = mask_reg
        self.src_byte_offset = src_byte_offset
        self.span_id = span_id
        self.word_received: bool = False
        self._word: int | None = None
        self._done: bool = False

    def resolve(self, word: int) -> None:
        """Called by the channel-0 response handler. Sync: just stashes state."""
        assert not self.word_received
        self._word = word
        self.word_received = True

    async def monitor_lamlet(self, lamlet) -> None:
        if not self.word_received or self._done:
            return
        eb = self.element_width // 8
        raw = self._word.to_bytes(lamlet.params.word_bytes,
                                  byteorder='little', signed=False)
        off = self.src_byte_offset
        scalar_val = int.from_bytes(raw[off:off + eb], byteorder='little', signed=True)

        broadcast_ident = await ident_query.get_instr_ident(lamlet)
        kinstr = kinstructions.VBroadcastOp(
            dst=self.vd,
            scalar=scalar_val,
            n_elements=self.n_elements,
            element_width=self.element_width,
            word_order=self.word_order,
            instr_ident=broadcast_ident,
            mask_reg=self.mask_reg,
        )
        await lamlet.add_to_instruction_buffer(kinstr, self.span_id)
        lamlet.monitor.finalize_children(self.span_id)
        lamlet.clear_vreg_write_pending(self.vd, self.element_width)
        self._done = True

    def ready(self) -> bool:
        return self._done


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
