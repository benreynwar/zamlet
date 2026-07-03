from collections import deque
from random import Random

import cocotb
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge

from zamlet.lane_order import LaneOrder
from zamlet.params import ZamletParams
from zamlet.test_helpers.streams import ValidMonitor, ValidReadySink, ValidReadySource

JTE_STATE_INITIAL = 0


class ScalarResponder:
    def __init__(
        self,
        dut: HierarchyObject,
        req_prefix: str,
        resp_prefix: str,
        mapping,
        expected_requests: deque[object] | None = None,
    ):
        self.dut = dut
        self.clock = dut.clock
        self.req_prefix = req_prefix
        self.mapping = mapping
        self.expected_requests = expected_requests
        self.req = ValidReadySink(dut, dut.clock, req_prefix, max_queue_depth=2)
        self.resp = ValidReadySource(dut, dut.clock, resp_prefix)

    def start(self, rng: Random) -> list:
        tasks = []
        tasks.extend(self.req.start(rng=rng))
        tasks.extend(self.resp.start(rng=rng))
        tasks.append(cocotb.start_soon(self.route()))
        return tasks

    def check_expected(self, addr: int) -> None:
        if self.expected_requests is None:
            return
        assert self.expected_requests, f"{self.req_prefix} unexpected request address {addr}"
        expected_request = self.expected_requests.popleft()
        if isinstance(expected_request, tuple):
            expected_instr_index, expected_instr, expected_addr = expected_request
            expected_context = (
                f"\nexpected instruction index: {expected_instr_index}"
                f"\nexpected instruction: {expected_instr}"
            )
        else:
            expected_addr = expected_request
            expected_context = ""
        assert addr == expected_addr, (
            f"{self.req_prefix} request mismatch\n"
            f"actual:   {addr}\n"
            f"expected: {expected_addr}"
            f"{expected_context}"
        )

    def lookup(self, addr: int):
        if isinstance(self.mapping, list):
            assert 0 <= addr < len(self.mapping), (
                f"{self.req_prefix} requested out-of-range RF address {addr}"
            )
        else:
            assert addr in self.mapping, f"{self.req_prefix} requested unmapped address {addr}"
        return self.mapping[addr]

    async def route(self) -> None:
        while True:
            if self.req.queue:
                addr = self.req.pop()
                self.check_expected(addr)
                self.resp.append(self.lookup(addr))
            await RisingEdge(self.clock)


class TlbResponder(ScalarResponder):
    def check_expected(self, req: dict[str, int]) -> None:
        super().check_expected(req["virtualStripeAddr"])

    def lookup(self, req: dict[str, int]) -> dict[str, int]:
        mapped = super().lookup(req["virtualStripeAddr"])
        return {
            "status": 0,
            "teIndex": req["teIndex"],
            "byteIndex": req["byteIndex"],
            "translation_stripeAddr": mapped["stripeAddr"],
            "translation_ordering_wf": mapped["ordering_wf"],
            "translation_ordering_laneOrder": mapped["ordering_laneOrder"],
        }

    async def route(self) -> None:
        while True:
            if self.req.queue:
                req = self.req.pop()
                self.check_expected(req)
                self.resp.append(self.lookup(req))
            await RisingEdge(self.clock)


class JteInitiatorDriver:
    def __init__(
        self,
        dut: HierarchyObject,
        params: ZamletParams,
        this_x: int,
        this_y: int,
        lane_index: int,
    ):
        self.dut = dut
        self.params = params
        self.clock = dut.clock
        self.input = ValidReadySource(dut, dut.clock, "io_input")
        self.packet = ValidReadySink(dut, dut.clock, "io_packet")
        self.commit = ValidMonitor(dut, dut.clock, "io_commit")

        dut.io_x.value = this_x
        dut.io_y.value = this_y
        dut.io_laneIndex.value = lane_index

    def start(
        self,
        rng: Random,
        content: list[int],
        tlb_table: dict[int, dict[str, int]],
        index_requests_expected: deque[object],
        tlb_requests_expected: deque[object],
    ) -> list:
        tasks = []
        tasks.extend(self.input.start(rng=rng, p_valid=0.5))
        tasks.extend(ScalarResponder(
            self.dut, "io_rfIndexReq", "io_rfIndexResp", content, index_requests_expected
        ).start(rng))
        tasks.extend(ScalarResponder(
            self.dut, "io_rfDataReq", "io_rfDataResp", content
        ).start(rng))
        tasks.extend(ScalarResponder(
            self.dut, "io_rfMaskReq", "io_rfMaskResp", content
        ).start(rng))
        tasks.extend(TlbResponder(
            self.dut, "io_tlbReq", "io_tlbResp", tlb_table, tlb_requests_expected
        ).start(rng))
        tasks.extend(self.packet.start(rng=rng, p_ready=0.5))
        tasks.extend(self.commit.start())
        return tasks

    def enqueue_instruction(self, instr) -> None:
        item = {
            "teIndex": 0,
            "instrIdent": 0,
            "mode": instr.mode,
            "baseAddr": instr.base_addr,
            "stride": 0,
            "startIndex": instr.start_index,
            "endIndex": instr.end_index,
            "dataReg": instr.data_reg,
            "indexReg": instr.index_reg,
            "maskReg": instr.mask_reg,
            "maskEnabled": int(instr.mask_enabled),
            "rfLaneOrder": LaneOrder.MOORE,
            "rfDataWF": instr.reg_wf,
            "rfDataEW": instr.data_ew,
            "rfIndexEW": instr.index_ew,
        }
        for i in range(self.params.word_bytes):
            item[f"initiator_{i}"] = JTE_STATE_INITIAL
        self.input.append(item)

    def enqueue_instructions(self, instrs) -> None:
        for instr in instrs:
            self.enqueue_instruction(instr)
