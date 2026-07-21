from collections import deque
from dataclasses import dataclass
from enum import IntEnum
from random import Random

import cocotb
from cocotb.handle import HierarchyObject
from cocotb.triggers import Event, ReadOnly

from zamlet.test_utils import rising_edge
from zamlet.utils import make_seed


class TagState(IntEnum):
    EMPTY = 0
    EMPTY_IN_QUEUE = 1
    RESERVED_CLEAN = 2
    RESERVED_DIRTY = 3
    FILLING_CLEAN = 4
    FILLING_DIRTY = 5
    PRESENT_CLEAN = 6
    PRESENT_DIRTY = 7
    EVICTING = 8


@dataclass(frozen=True)
class ClaimReq:
    tag: int
    will_write: bool
    do_claim: bool
    claim_if_pending_fill: bool


@dataclass(frozen=True)
class ClaimResp:
    has_slot: int
    slot: int
    state: int
    did_claim: int


@dataclass(frozen=True)
class AllocReq:
    tag: int
    will_write: bool


@dataclass(frozen=True)
class AllocResp:
    slot: int
    state: int


@dataclass(frozen=True)
class FillReq:
    slot: int
    tag: int


@dataclass(frozen=True)
class WritebackReq:
    slot: int
    tag: int


@dataclass(frozen=True)
class ReleaseReq:
    slot: int
    done: Event


@dataclass(frozen=True)
class LifecycleErrors:
    alloc_bad_state: int
    alloc_bad_uses: int
    alloc_recently_used: int
    fill_bad_state: int
    writeback_complete_bad_state: int
    writeback_complete_queue_not_ready: int
    release_underflow: int


@dataclass(frozen=True)
class LifecycleDriverProbabilities:
    alloc_req_valid: float = 1.0
    alloc_resp_ready: float = 1.0
    claim_req_valid: float = 1.0
    release_valid: float = 1.0
    fill_req_ready: float = 1.0
    writeback_req_ready: float = 1.0


class TagTableDriver:
    def __init__(self, dut: HierarchyObject):
        self.dut = dut
        self.clock = dut.clock

        self.alloc_reqs = deque()
        self.alloc_resps = deque()
        self.claim_reqs = deque()
        self.claim_resps = deque()
        self.fill_completes = deque()
        self.release_reqs = deque()
        self.writeback_completes = deque()
        self.errors = deque()
        self.fill_complete_events = {}

        self.probabilities = LifecycleDriverProbabilities()
        self.started = False

    def start(
        self,
        rng: Random,
        probabilities: LifecycleDriverProbabilities | None = None,
    ) -> None:
        if self.started:
            raise RuntimeError("TagTableDriver already started")
        self.started = True
        self.probabilities = probabilities or LifecycleDriverProbabilities()
        cocotb.start_soon(self.drive_alloc_req(make_seed(rng)))
        cocotb.start_soon(self.monitor_alloc_resp(make_seed(rng)))
        cocotb.start_soon(self.drive_claim_req(make_seed(rng)))
        cocotb.start_soon(self.monitor_claim_resp(make_seed(rng)))
        cocotb.start_soon(self.monitor_fill_req(make_seed(rng)))
        cocotb.start_soon(self.drive_fill_complete())
        cocotb.start_soon(self.drive_release(make_seed(rng)))
        cocotb.start_soon(self.monitor_writeback_req(make_seed(rng)))
        cocotb.start_soon(self.drive_writeback_complete())
        cocotb.start_soon(self.monitor_errors())

    async def reset(self) -> None:
        self.dut.reset.value = 1
        self.dut.io_allocReq_valid.value = 0
        self.dut.io_allocReq_bits_tag.value = 0
        self.dut.io_allocReq_bits_willWrite.value = 0
        self.dut.io_allocResp_ready.value = 0
        self.dut.io_claimReq_valid.value = 0
        self.dut.io_claimReq_bits_tag.value = 0
        self.dut.io_claimReq_bits_willWrite.value = 0
        self.dut.io_claimReq_bits_doClaim.value = 0
        self.dut.io_claimReq_bits_claimIfPendingFill.value = 0
        self.dut.io_fillReq_ready.value = 0
        self.dut.io_fillComplete_valid.value = 0
        self.dut.io_fillComplete_bits_slot.value = 0
        self.dut.io_release_valid.value = 0
        self.dut.io_release_bits.value = 0
        self.dut.io_writebackReq_ready.value = 1
        self.dut.io_writebackComplete_valid.value = 0
        self.dut.io_writebackComplete_bits.value = 0
        await rising_edge(self.clock)
        await rising_edge(self.clock)
        self.dut.reset.value = 0

    async def wait_for_allocated_slot(self) -> int:
        resp = await self.wait_for_alloc_resp()
        return resp.slot

    async def wait_for_alloc_resp(self) -> AllocResp:
        while True:
            if self.alloc_resps:
                return self.alloc_resps.popleft()
            await rising_edge(self.clock)

    async def wait_for_claim_resp(self) -> ClaimResp:
        while True:
            if self.claim_resps:
                return self.claim_resps.popleft()
            await rising_edge(self.clock)

    async def wait_for_fill_complete(self, slot: int) -> None:
        event = self.fill_complete_events.setdefault(slot, Event())
        await event.wait()

    async def wait_for_fill_drained(self) -> None:
        while True:
            if not self.fill_completes:
                return
            await rising_edge(self.clock)

    async def alloc(self, tag: int, will_write: bool = False) -> AllocResp:
        self.alloc_reqs.append(AllocReq(tag=tag, will_write=will_write))
        return await self.wait_for_alloc_resp()

    async def claim(
        self,
        tag: int,
        will_write: bool = False,
        claim_if_pending_fill: bool = False,
    ) -> ClaimResp:
        self.claim_reqs.append(ClaimReq(
            tag=tag,
            will_write=will_write,
            do_claim=True,
            claim_if_pending_fill=claim_if_pending_fill,
        ))
        return await self.wait_for_claim_resp()

    async def release(self, slot: int) -> None:
        done = Event()
        self.release_reqs.append(ReleaseReq(slot=slot, done=done))
        await done.wait()

    async def drive_alloc_req(self, seed: int) -> None:
        rng = Random(seed)
        active_req = None
        while True:
            if active_req is None and self.alloc_reqs:
                if rng.random() < self.probabilities.alloc_req_valid:
                    active_req = self.alloc_reqs.popleft()
            if active_req is not None:
                self.dut.io_allocReq_valid.value = 1
                self.dut.io_allocReq_bits_tag.value = active_req.tag
                self.dut.io_allocReq_bits_willWrite.value = int(active_req.will_write)
            else:
                self.dut.io_allocReq_valid.value = 0
            await ReadOnly()
            fire = bool(
                int(self.dut.io_allocReq_valid.value)
                and int(self.dut.io_allocReq_ready.value)
            )
            await rising_edge(self.clock)
            if fire:
                active_req = None

    async def monitor_alloc_resp(self, seed: int) -> None:
        rng = Random(seed)
        while True:
            self.dut.io_allocResp_ready.value = int(
                rng.random() < self.probabilities.alloc_resp_ready
            )
            await ReadOnly()
            if (
                int(self.dut.io_allocResp_valid.value)
                and int(self.dut.io_allocResp_ready.value)
            ):
                slot = int(self.dut.io_allocResp_bits_slot.value)
                self.fill_complete_events[slot] = Event()
                self.alloc_resps.append(AllocResp(
                    slot=slot,
                    state=int(self.dut.io_allocResp_bits_state.value),
                ))
            await rising_edge(self.clock)

    async def drive_claim_req(self, seed: int) -> None:
        rng = Random(seed)
        active_req = None
        while True:
            if active_req is None and self.claim_reqs:
                if rng.random() < self.probabilities.claim_req_valid:
                    active_req = self.claim_reqs.popleft()
            if active_req is not None:
                self.dut.io_claimReq_valid.value = 1
                self.dut.io_claimReq_bits_tag.value = active_req.tag
                self.dut.io_claimReq_bits_willWrite.value = int(active_req.will_write)
                self.dut.io_claimReq_bits_doClaim.value = int(active_req.do_claim)
                self.dut.io_claimReq_bits_claimIfPendingFill.value = int(
                    active_req.claim_if_pending_fill
                )
            else:
                self.dut.io_claimReq_valid.value = 0
            await rising_edge(self.clock)
            if active_req is not None:
                active_req = None

    async def monitor_claim_resp(self, seed: int) -> None:
        while True:
            await ReadOnly()
            if int(self.dut.io_claimResp_valid.value):
                self.claim_resps.append(ClaimResp(
                    has_slot=int(self.dut.io_claimResp_bits_hasSlot.value),
                    slot=int(self.dut.io_claimResp_bits_slot.value),
                    state=int(self.dut.io_claimResp_bits_state.value),
                    did_claim=int(self.dut.io_claimResp_bits_didClaim.value),
                ))
            await rising_edge(self.clock)

    async def monitor_fill_req(self, seed: int) -> None:
        rng = Random(seed)
        while True:
            self.dut.io_fillReq_ready.value = int(
                rng.random() < self.probabilities.fill_req_ready
            )
            await ReadOnly()
            if (
                int(self.dut.io_fillReq_valid.value)
                and int(self.dut.io_fillReq_ready.value)
            ):
                req = FillReq(
                    slot=int(self.dut.io_fillReq_bits_slot.value),
                    tag=int(self.dut.io_fillReq_bits_tag.value),
                )
                cocotb.start_soon(
                    self.complete_fill_after_delay(req, rng.randrange(8))
                )
            await rising_edge(self.clock)

    async def complete_fill_after_delay(self, req: FillReq, delay: int) -> None:
        for _ in range(delay):
            await rising_edge(self.clock)
        self.fill_completes.append(req.slot)

    async def drive_fill_complete(self) -> None:
        active_slot = None
        while True:
            if active_slot is None and self.fill_completes:
                active_slot = self.fill_completes.popleft()
            if active_slot is not None:
                self.dut.io_fillComplete_valid.value = 1
                self.dut.io_fillComplete_bits_slot.value = active_slot
            else:
                self.dut.io_fillComplete_valid.value = 0
            await rising_edge(self.clock)
            if active_slot is not None:
                event = self.fill_complete_events.setdefault(active_slot, Event())
                event.set()
                active_slot = None

    async def monitor_writeback_req(self, seed: int) -> None:
        rng = Random(seed)
        while True:
            self.dut.io_writebackReq_ready.value = int(
                rng.random() < self.probabilities.writeback_req_ready
            )
            await ReadOnly()
            if (
                int(self.dut.io_writebackReq_valid.value)
                and int(self.dut.io_writebackReq_ready.value)
            ):
                req = WritebackReq(
                    slot=int(self.dut.io_writebackReq_bits_slot.value),
                    tag=int(self.dut.io_writebackReq_bits_tag.value),
                )
                cocotb.start_soon(
                    self.complete_writeback_after_delay(req, rng.randrange(8))
                )
            await rising_edge(self.clock)

    async def complete_writeback_after_delay(
        self,
        req: WritebackReq,
        delay: int,
    ) -> None:
        for _ in range(delay):
            await rising_edge(self.clock)
        self.writeback_completes.append(req.slot)

    async def drive_writeback_complete(self) -> None:
        active_slot = None
        while True:
            if active_slot is None and self.writeback_completes:
                active_slot = self.writeback_completes.popleft()
            if active_slot is not None:
                self.dut.io_writebackComplete_valid.value = 1
                self.dut.io_writebackComplete_bits.value = active_slot
            else:
                self.dut.io_writebackComplete_valid.value = 0
            await rising_edge(self.clock)
            active_slot = None

    async def drive_release(self, seed: int) -> None:
        rng = Random(seed)
        active_req = None
        while True:
            if active_req is None and self.release_reqs:
                if rng.random() < self.probabilities.release_valid:
                    active_req = self.release_reqs.popleft()
            if active_req is not None:
                self.dut.io_release_valid.value = 1
                self.dut.io_release_bits.value = active_req.slot
            else:
                self.dut.io_release_valid.value = 0
            await rising_edge(self.clock)
            if active_req is not None:
                active_req.done.set()
                active_req = None

    async def monitor_errors(self) -> None:
        while True:
            await ReadOnly()
            self.errors.append(LifecycleErrors(
                alloc_bad_state=int(
                    self.dut.io_errors_allocBadState.value
                ),
                alloc_bad_uses=int(
                    self.dut.io_errors_allocBadUses.value
                ),
                alloc_recently_used=int(
                    self.dut.io_errors_allocRecentlyUsed.value
                ),
                fill_bad_state=int(self.dut.io_errors_fillBadState.value),
                writeback_complete_bad_state=int(
                    self.dut.io_errors_writebackCompleteBadState.value
                ),
                writeback_complete_queue_not_ready=int(
                    self.dut.io_errors_writebackCompleteQueueNotReady.value
                ),
                release_underflow=int(
                    self.dut.io_errors_releaseUnderflow.value
                ),
            ))
            await rising_edge(self.clock)

    async def check_errors(self) -> None:
        while True:
            await ReadOnly()
            assert int(self.dut.io_errors_allocBadState.value) == 0
            assert int(self.dut.io_errors_allocBadUses.value) == 0
            assert int(self.dut.io_errors_allocRecentlyUsed.value) == 0
            assert int(self.dut.io_errors_fillBadState.value) == 0
            assert int(self.dut.io_errors_writebackCompleteBadState.value) == 0
            assert int(self.dut.io_errors_writebackCompleteQueueNotReady.value) == 0
            assert int(self.dut.io_errors_releaseUnderflow.value) == 0
            await rising_edge(self.clock)
