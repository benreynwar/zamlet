from collections import deque
from dataclasses import dataclass, field
from random import Random

import cocotb
from cocotb.handle import HierarchyObject
from cocotb.triggers import ReadOnly, RisingEdge
from zamlet.kamlet.kinstructions import (
    PackedLoadIndexedUnordered,
    PackedStoreIndexedUnordered,
)
from zamlet.lane_order import LaneOrder
from zamlet.test_helpers.streams import ValidReadySink, ValidReadySource
from zamlet.utils import make_seed
from zamlet.width_codes import WidthFormatCode


KTE_OP_JTE_TRANSFER = 1
KTE_OP_CACHE_WAIT_LOCAL = 0
KCE_CACHE_SLOT_FETCHING = 2
KCE_CACHE_SLOT_PRESENT_CLEAN = 4


@dataclass
class JteEntry:
    instr_ident: int
    data_reg: int


@dataclass
class JteInput:
    instr_ident: int
    mode: int
    base_addr: int
    start_index: int
    end_index: int
    data_reg: int
    index_reg: int
    mask_reg: int
    mask_enabled: bool


@dataclass
class KteJamletState:
    jte_entries: dict[int, JteEntry] = field(default_factory=dict)
    jte_inputs: dict[int, JteInput] = field(default_factory=dict)
    requested_inputs: set[int] = field(default_factory=set)
    completed_inputs: set[int] = field(default_factory=set)
    cleared_entries: set[int] = field(default_factory=set)
    clear_counts: dict[int, int] = field(default_factory=dict)


class KteJamletModel:
    """Passive model for one Jamlet-facing KTE interface."""

    def __init__(
        self,
        dut: HierarchyObject,
        index: int,
        te_depth: int,
        input_request_probability: float = 0.5,
    ):
        self.dut = dut
        self.index = index
        self.te_depth = te_depth
        self.input_request_probability = input_request_probability
        self.state = KteJamletState()
        self.input_req = ValidReadySource(
            dut, dut.clock, f"io_jteInputReq_{index}")
        self.input_resp = ValidReadySink(
            dut, dut.clock, f"io_jteInputResp_{index}")
        self._transfer_complete_queue = deque()

    def start(self, rng: Random) -> None:
        self.input_req.start(rng=rng)
        self.input_resp.start(rng=rng)
        cocotb.start_soon(self._monitor_create())
        cocotb.start_soon(self._monitor_clear())
        cocotb.start_soon(self._queue_input_req(make_seed(rng)))
        cocotb.start_soon(self._record_input_resp())
        cocotb.start_soon(self._drive_transfer_complete(make_seed(rng)))

    async def _monitor_create(self) -> None:
        while True:
            await RisingEdge(self.dut.clock)
            await ReadOnly()
            if int(getattr(self.dut, f"io_jteCreate_{self.index}_valid").value):
                te_index = int(getattr(
                    self.dut, f"io_jteCreate_{self.index}_bits_teIndex").value)
                instr_ident = int(getattr(
                    self.dut, f"io_jteCreate_{self.index}_bits_instrIdent").value)
                data_reg = int(getattr(
                    self.dut, f"io_jteCreate_{self.index}_bits_dataReg").value)
                self.state.jte_entries[te_index] = JteEntry(
                    instr_ident=instr_ident,
                    data_reg=data_reg,
                )

    async def _monitor_clear(self) -> None:
        while True:
            await RisingEdge(self.dut.clock)
            await ReadOnly()
            if int(getattr(self.dut, f"io_jteClear_{self.index}_valid").value):
                te_index = int(getattr(
                    self.dut, f"io_jteClear_{self.index}_bits").value)
                self.state.cleared_entries.add(te_index)
                self.state.clear_counts[te_index] = (
                    self.state.clear_counts.get(te_index, 0) + 1)
                self.state.jte_entries.pop(te_index, None)
                self.state.jte_inputs.pop(te_index, None)
                self.state.requested_inputs.discard(te_index)
                self.state.completed_inputs.discard(te_index)

    async def _queue_input_req(self, seed: int) -> None:
        rng = Random(seed)

        while True:
            await RisingEdge(self.dut.clock)
            candidates = [
                te_index
                for te_index in sorted(self.state.jte_entries)
                if te_index not in self.state.requested_inputs
                and te_index not in self.state.jte_inputs
            ]
            if candidates and rng.random() < self.input_request_probability:
                te_index = rng.choice(candidates)
                self.state.requested_inputs.add(te_index)
                self.input_req.append(te_index)

    async def _record_input_resp(self) -> None:
        while True:
            await RisingEdge(self.dut.clock)
            while self.input_resp.queue:
                resp = self.input_resp.pop()
                te_index = resp["teIndex"]
                self.state.jte_inputs[te_index] = JteInput(
                    instr_ident=resp["instrIdent"],
                    mode=resp["mode"],
                    base_addr=resp["baseAddr"],
                    start_index=resp["startIndex"],
                    end_index=resp["endIndex"],
                    data_reg=resp["dataReg"],
                    index_reg=resp["indexReg"],
                    mask_reg=resp["maskReg"],
                    mask_enabled=bool(resp["maskEnabled"]),
                )
                if te_index not in self.state.completed_inputs:
                    self._transfer_complete_queue.append(te_index)

    async def _drive_transfer_complete(self, seed: int) -> None:
        rng = Random(seed)
        complete_signals = [
            getattr(self.dut, f"io_transferComplete_{self.index}_{te_index}")
            for te_index in range(self.te_depth)
        ]

        while True:
            for signal in complete_signals:
                signal.value = 0

            if self._transfer_complete_queue and rng.random() < 0.5:
                te_index = self._transfer_complete_queue.popleft()
                self.state.completed_inputs.add(te_index)
                complete_signals[te_index].value = 1

            await RisingEdge(self.dut.clock)


class KteDriver:
    """Small strict driver for KTE pipeline-cleaner tests."""

    def __init__(
        self,
        dut: HierarchyObject,
        j_in_k: int = 2,
        te_depth: int = 8,
        sync_result_probability: float = 0.5,
    ):
        self.dut = dut
        self.j_in_k = j_in_k
        self.te_depth = te_depth
        self.sync_result_probability = sync_result_probability
        self.issue = ValidReadySource(dut, dut.clock, "io_rsIssue")
        self.sync_results = deque()
        self.claim_reqs = deque()
        self.local_replays = deque()
        self.cache_slot_releases = deque()
        self._claim_resp_queue = deque()
        self._slot_available_queue = deque()
        self.jamlets = [
            KteJamletModel(dut, j, te_depth=te_depth)
            for j in range(j_in_k)
        ]

    def start(self, rng: Random) -> None:
        self.issue.start(rng=rng)
        for jamlet in self.jamlets:
            jamlet.start(rng)
        cocotb.start_soon(self._monitor_sync_local_event())
        cocotb.start_soon(self._drive_sync_result(make_seed(rng)))
        cocotb.start_soon(self._monitor_claim_req())
        cocotb.start_soon(self._drive_claim_resp())
        cocotb.start_soon(self._monitor_local_replay())
        cocotb.start_soon(self._monitor_cache_slot_release())
        cocotb.start_soon(self._drive_slot_available())

    def append_issue(self, issue: dict[str, int]) -> None:
        self.issue.append(issue)

    def append_indexed_transfer(
        self,
        params,
        instr_ident: int,
        sync_ident: int,
        is_store: bool = False,
        base_addr: int = 0x1000,
        start_index: int = 0,
        end_index: int = 8,
        data_reg: int = 3,
        index_reg: int = 4,
        mask_reg: int = 0,
        mask_enabled: bool = False,
    ) -> None:
        kinstr_cls = (
            PackedStoreIndexedUnordered
            if is_store else PackedLoadIndexedUnordered
        )
        kinstr = kinstr_cls(
            reg=data_reg,
            index_reg=index_reg,
            sync_ident=sync_ident,
            mask_reg=mask_reg,
            mask_enabled=mask_enabled,
            instr_ident=instr_ident,
        )
        self.append_issue({
            "opType": KTE_OP_JTE_TRANSFER,
            "kinstr_kinstr": kinstr.encode(params),
            "kinstr_ordering_wf": WidthFormatCode.WF64,
            "kinstr_ordering_laneOrder": LaneOrder.ROW_MAJOR,
            "kinstr_cacheSlot": 0,
            "kinstr_sramWordOffset": 0,
            "kinstr_param0": base_addr,
            "kinstr_param1": start_index,
            "kinstr_param2": end_index,
            "cacheLineAddr": 0,
            "willWrite": int(is_store),
        })

    def append_cache_wait_local(
        self,
        kinstr: int,
        cache_line_addr: int,
        will_write: bool = False,
        ordering_wf: int = WidthFormatCode.WF64,
        ordering_lane_order: LaneOrder = LaneOrder.ROW_MAJOR,
    ) -> None:
        self.append_issue({
            "opType": KTE_OP_CACHE_WAIT_LOCAL,
            "kinstr_kinstr": kinstr,
            "kinstr_ordering_wf": ordering_wf,
            "kinstr_ordering_laneOrder": ordering_lane_order,
            "kinstr_cacheSlot": 0,
            "kinstr_sramWordOffset": 0,
            "kinstr_param0": 0,
            "kinstr_param1": 0,
            "kinstr_param2": 0,
            "cacheLineAddr": cache_line_addr,
            "willWrite": int(will_write),
        })

    def append_claim_resp(
        self,
        has_slot: bool,
        slot: int,
        state: int,
        did_claim: bool | None = None,
    ) -> None:
        self._claim_resp_queue.append({
            "hasSlot": int(has_slot),
            "slot": slot,
            "state": state,
            "didClaim": int(has_slot if did_claim is None else did_claim),
        })

    def pulse_slot_available(self, slot: int) -> None:
        self._slot_available_queue.append(slot)

    def set_defaults(self) -> None:
        """Drive all KTE inputs to idle values."""
        self.dut.io_conflictCacheLineAddr.value = 0
        self.dut.io_localReplay_ready.value = 0
        self.dut.io_rfRelease_ready.value = 0

        self.dut.io_syncResult_valid.value = 0

        self.dut.io_kceClaimSlotReq_ready.value = 0
        self.dut.io_kceClaimSlotResp_valid.value = 0
        self.dut.io_kceAllocSlotReq_ready.value = 0
        self.dut.io_kceAllocSlotResp_valid.value = 0
        self.dut.io_kceSlotIsAvailable_valid.value = 0

        for j in range(self.j_in_k):
            for te_index in range(self.te_depth):
                getattr(self.dut, f"io_transferComplete_{j}_{te_index}").value = 0

    async def reset(self) -> None:
        self.set_defaults()
        self.dut.reset.value = 1
        await RisingEdge(self.dut.clock)
        await RisingEdge(self.dut.clock)
        self.dut.reset.value = 0

    async def idle(self, cycles: int) -> None:
        for _ in range(cycles):
            await RisingEdge(self.dut.clock)

    async def wait_for_jte_clear(self, te_index: int, timeout_cycles: int) -> None:
        for _ in range(timeout_cycles):
            if all(
                te_index in jamlet.state.cleared_entries
                for jamlet in self.jamlets
            ):
                return
            await RisingEdge(self.dut.clock)
        raise AssertionError(f"timed out waiting for JTE clear teIndex={te_index}")

    async def wait_for_total_jte_clears(
        self, expected_clears: int, timeout_cycles: int
    ) -> None:
        for _ in range(timeout_cycles):
            if all(
                sum(jamlet.state.clear_counts.values()) >= expected_clears
                for jamlet in self.jamlets
            ):
                return
            await RisingEdge(self.dut.clock)
        counts = [jamlet.state.clear_counts for jamlet in self.jamlets]
        raise AssertionError(
            f"timed out waiting for {expected_clears} JTE clears; counts={counts}")

    async def wait_for_sync_local_event(
        self, sync_ident: int, timeout_cycles: int
    ) -> None:
        for _ in range(timeout_cycles):
            for event in self.sync_results:
                if event["syncIdent"] == sync_ident:
                    return
            await RisingEdge(self.dut.clock)
        raise AssertionError(
            f"timed out waiting for syncLocalEvent sync_ident={sync_ident}")

    async def wait_for_claim_req(self, timeout_cycles: int) -> dict[str, int]:
        for _ in range(timeout_cycles):
            if self.claim_reqs:
                return self.claim_reqs.popleft()
            await RisingEdge(self.dut.clock)
        raise AssertionError("timed out waiting for kceClaimSlotReq")

    async def wait_for_local_replay(self, timeout_cycles: int) -> dict[str, int]:
        for _ in range(timeout_cycles):
            if self.local_replays:
                return self.local_replays.popleft()
            await RisingEdge(self.dut.clock)
        raise AssertionError("timed out waiting for localReplay")

    async def wait_for_cache_slot_release(
        self, slot: int, timeout_cycles: int
    ) -> None:
        for _ in range(timeout_cycles):
            while self.cache_slot_releases:
                released_slot = self.cache_slot_releases.popleft()
                if released_slot == slot:
                    return
            await RisingEdge(self.dut.clock)
        raise AssertionError(f"timed out waiting for cache slot release slot={slot}")

    async def _monitor_sync_local_event(self) -> None:
        while True:
            await RisingEdge(self.dut.clock)
            await ReadOnly()
            if int(self.dut.io_syncLocalEvent_valid.value):
                self.sync_results.append({
                    "syncIdent": int(self.dut.io_syncLocalEvent_bits_syncIdent.value),
                    "value": int(self.dut.io_syncLocalEvent_bits_value.value),
                    "includeActiveMask": int(
                        self.dut.io_syncLocalEvent_bits_includeActiveMask.value),
                })

    async def _drive_sync_result(self, seed: int) -> None:
        rng = Random(seed)
        self.dut.io_syncResult_valid.value = 0

        while True:
            if self.sync_results and rng.random() < self.sync_result_probability:
                result = self.sync_results.popleft()
                self.dut.io_syncResult_valid.value = 1
                self.dut.io_syncResult_bits_syncIdent.value = result["syncIdent"]
                self.dut.io_syncResult_bits_value.value = result["value"]
                self.dut.io_syncResult_bits_includeActiveMask.value = (
                    result["includeActiveMask"])
            else:
                self.dut.io_syncResult_valid.value = 0

            await RisingEdge(self.dut.clock)

    async def _monitor_claim_req(self) -> None:
        self.dut.io_kceClaimSlotReq_ready.value = 1
        while True:
            await RisingEdge(self.dut.clock)
            await ReadOnly()
            if (
                int(self.dut.io_kceClaimSlotReq_valid.value)
                and int(self.dut.io_kceClaimSlotReq_ready.value)
            ):
                self.claim_reqs.append({
                    "cacheLineAddr": int(
                        self.dut.io_kceClaimSlotReq_bits_cacheLineAddr.value),
                    "willWrite": int(
                        self.dut.io_kceClaimSlotReq_bits_willWrite.value),
                    "claimIfFetching": int(
                        self.dut.io_kceClaimSlotReq_bits_claimIfFetching.value),
                })

    async def _drive_claim_resp(self) -> None:
        self.dut.io_kceClaimSlotResp_valid.value = 0
        while True:
            if self._claim_resp_queue:
                resp = self._claim_resp_queue[0]
                self.dut.io_kceClaimSlotResp_valid.value = 1
                self.dut.io_kceClaimSlotResp_bits_hasSlot.value = resp["hasSlot"]
                self.dut.io_kceClaimSlotResp_bits_slot.value = resp["slot"]
                self.dut.io_kceClaimSlotResp_bits_state.value = resp["state"]
                self.dut.io_kceClaimSlotResp_bits_didClaim.value = resp["didClaim"]
                await RisingEdge(self.dut.clock)
                if int(self.dut.io_kceClaimSlotResp_ready.value):
                    self._claim_resp_queue.popleft()
            else:
                self.dut.io_kceClaimSlotResp_valid.value = 0
                await RisingEdge(self.dut.clock)

    async def _monitor_local_replay(self) -> None:
        self.dut.io_localReplay_ready.value = 1
        while True:
            await RisingEdge(self.dut.clock)
            await ReadOnly()
            if (
                int(self.dut.io_localReplay_valid.value)
                and int(self.dut.io_localReplay_ready.value)
            ):
                self.local_replays.append({
                    "kinstr": int(self.dut.io_localReplay_bits_kinstr.value),
                    "cacheSlot": int(self.dut.io_localReplay_bits_cacheSlot.value),
                })

    async def _monitor_cache_slot_release(self) -> None:
        while True:
            await RisingEdge(self.dut.clock)
            await ReadOnly()
            if int(self.dut.io_kceReleaseSlot_valid.value):
                self.cache_slot_releases.append(
                    int(self.dut.io_kceReleaseSlot_bits_slot.value))

    async def _drive_slot_available(self) -> None:
        self.dut.io_kceSlotIsAvailable_valid.value = 0
        while True:
            if self._slot_available_queue:
                self.dut.io_kceSlotIsAvailable_valid.value = 1
                self.dut.io_kceSlotIsAvailable_bits.value = (
                    self._slot_available_queue.popleft())
            else:
                self.dut.io_kceSlotIsAvailable_valid.value = 0
            await RisingEdge(self.dut.clock)
