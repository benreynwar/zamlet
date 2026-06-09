import json
import logging
from collections import defaultdict, deque
from random import Random

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import Event, ReadOnly, RisingEdge

from zamlet import test_utils
from zamlet.future import Future
from zamlet.lane_order import LaneOrder
from zamlet.message import (
    KamletTlbReqHeader,
    KamletTlbRespHeader,
    MessageType,
    SendType,
)
from zamlet.params import ZamletParams
from zamlet.test_helpers.streams import ValidReadySink, ValidReadySource
from zamlet.width_codes import WidthFormatCode

TLB_STATUS_HIT = 0
TLB_STATUS_SOFT_DROP = 1
TLB_STATUS_HARD_DROP = 2
TEST_TIMEOUT_NS = 1_000
logger = logging.getLogger(__name__)


def load_params(test_params: dict) -> ZamletParams:
    with open(test_params["params_file"]) as f:
        return ZamletParams.from_dict(json.load(f))


def random_tlb_keys(rng: Random, params: ZamletParams, count: int):
    keys = [
        (j_in_k, te_index, byte_index)
        for j_in_k in range(params.j_in_k)
        for te_index in range(params.witem_table_depth)
        for byte_index in range(params.word_bytes)
    ]
    rng.shuffle(keys)
    assert count <= len(keys)
    return keys[:count]


class KamletTlbDriver:
    def __init__(self, dut: HierarchyObject, params: ZamletParams):
        self.dut = dut
        self.params = params
        self.tlb_req = [
            ValidReadySource(dut, dut.clock, f"io_tlbReq_{j}")
            for j in range(params.j_in_k)
        ]
        self.tlb_resp = [
            ValidReadySink(dut, dut.clock, f"io_tlbResp_{j}")
            for j in range(params.j_in_k)
        ]
        self.packet_out = ValidReadySink(dut, dut.clock, "io_packetOut")
        self.packet_in = ValidReadySource(dut, dut.clock, "io_packetIn")
        self.network = TlbNetworkModel(self)
        self.tlb_resp_waiters = defaultdict(deque)

    def start(self, rng: Random) -> list:
        self.dut.io_localOrderingUpdate_valid.value = 0
        tasks = []
        for source in self.tlb_req:
            tasks.extend(source.start(rng=rng))
        for sink in self.tlb_resp:
            tasks.extend(sink.start(rng=rng))
        tasks.extend(self.packet_out.start(rng=rng))
        tasks.extend(self.packet_in.start(rng=rng))
        tasks.extend(self.network.start())
        tasks.append(cocotb.start_soon(self.route_tlb_resps()))
        return tasks

    async def reset(self) -> None:
        self.dut.reset.value = 1
        await RisingEdge(self.dut.clock)
        await RisingEdge(self.dut.clock)
        self.dut.reset.value = 0

    async def wait_for_packet_word(self) -> dict[str, int]:
        while True:
            if self.packet_out.queue:
                return self.packet_out.pop()
            await RisingEdge(self.dut.clock)

    async def wait_for_tlb_resp(self, j_in_k: int) -> dict[str, int]:
        while True:
            if self.tlb_resp[j_in_k].queue:
                return self.tlb_resp[j_in_k].pop()
            await RisingEdge(self.dut.clock)

    async def route_tlb_resps(self) -> None:
        while True:
            for j_in_k, sink in enumerate(self.tlb_resp):
                if sink.queue:
                    resp = sink.pop()
                    key = (j_in_k, resp["teIndex"], resp["byteIndex"])
                    logger.info("tlbResp j=%d te=%d byte=%d status=%d", *key, resp["status"])
                    assert self.tlb_resp_waiters[key], f"unexpected tlbResp {key}"
                    self.tlb_resp_waiters[key].popleft().set_result(resp)
            await RisingEdge(self.dut.clock)

    async def available(
        self,
        j_in_k: int,
        te_index: int,
        byte_index: int,
    ) -> None:
        valid = getattr(self.dut, f"io_tlbAvailable_{j_in_k}_valid")
        te = getattr(self.dut, f"io_tlbAvailable_{j_in_k}_bits_teIndex")
        byte = getattr(self.dut, f"io_tlbAvailable_{j_in_k}_bits_byteIndex")
        while True:
            await ReadOnly()
            if (
                int(valid.value)
                and int(te.value) == te_index
                and int(byte.value) == byte_index
            ):
                logger.info(
                    "tlbAvailable j=%d te=%d byte=%d",
                    j_in_k,
                    te_index,
                    byte_index,
                )
                await RisingEdge(self.dut.clock)
                return
            await RisingEdge(self.dut.clock)

    async def request_and_wait_for_translation(
        self,
        j_in_k: int,
        virtual_stripe: int,
        te_index: int = 0,
        byte_index: int = 0,
    ) -> dict[str, int]:
        available = cocotb.start_soon(self.available(j_in_k, te_index, byte_index))
        try:
            resp = await self.request(j_in_k, virtual_stripe, te_index, byte_index)
            if resp["status"] == TLB_STATUS_HIT:
                return resp
            assert resp["status"] == TLB_STATUS_SOFT_DROP
            await available
            retry_resp = await self.request(j_in_k, virtual_stripe, te_index, byte_index)
            assert retry_resp["status"] == TLB_STATUS_HIT
            return retry_resp
        finally:
            if not available.done():
                available.cancel()

    async def request_once(
        self,
        j_in_k: int,
        virtual_stripe: int,
        te_index: int,
        byte_index: int,
    ) -> dict[str, int]:
        while True:
            available = cocotb.start_soon(self.available(j_in_k, te_index, byte_index))
            try:
                logger.info(
                    "tlbReq j=%d te=%d byte=%d stripe=0x%x",
                    j_in_k,
                    te_index,
                    byte_index,
                    virtual_stripe,
                )
                resp = await self.request(j_in_k, virtual_stripe, te_index, byte_index)
                assert resp["teIndex"] == te_index
                assert resp["byteIndex"] == byte_index

                if resp["status"] == TLB_STATUS_HIT:
                    logger.info(
                        "tlbReq hit j=%d te=%d byte=%d stripe=0x%x",
                        j_in_k,
                        te_index,
                        byte_index,
                        virtual_stripe,
                    )
                    return resp

                if resp["status"] == TLB_STATUS_SOFT_DROP:
                    logger.info(
                        "tlbReq soft-drop j=%d te=%d byte=%d stripe=0x%x",
                        j_in_k,
                        te_index,
                        byte_index,
                        virtual_stripe,
                    )
                    await available
                else:
                    assert resp["status"] == TLB_STATUS_HARD_DROP
                    logger.info(
                        "tlbReq hard-drop j=%d te=%d byte=%d stripe=0x%x",
                        j_in_k,
                        te_index,
                        byte_index,
                        virtual_stripe,
                    )
            finally:
                if not available.done():
                    available.cancel()

    async def request_and_wait(
        self,
        j_in_k: int,
        virtual_stripe: int,
        te_index: int = 0,
        byte_index: int = 0,
    ) -> dict[str, int]:
        return await self.request_and_wait_for_translation(
            j_in_k,
            virtual_stripe,
            te_index,
            byte_index,
        )

    def request(
        self,
        j_in_k: int,
        virtual_stripe: int,
        te_index: int = 0,
        byte_index: int = 0,
    ) -> Future:
        future = Future(Event())
        self.tlb_resp_waiters[(j_in_k, te_index, byte_index)].append(future)
        self.tlb_req[j_in_k].append({
            "virtualStripeAddr": virtual_stripe,
            "teIndex": te_index,
            "byteIndex": byte_index,
        })
        return future


class TlbNetworkModel:
    def __init__(self, driver: KamletTlbDriver):
        self.driver = driver
        self.params = driver.params
        self.request_count_by_stripe: dict[int, int] = {}
        self.requests: list[tuple[int, int]] = []

    def start(self) -> list:
        return [cocotb.start_soon(self.run())]

    def physical_stripe(self, virtual_stripe: int) -> int:
        return virtual_stripe + 0x100

    def send_response(self, req_header: KamletTlbReqHeader, physical_stripe: int) -> None:
        resp_header = KamletTlbRespHeader(
            target_x=req_header.source_x,
            target_y=req_header.source_y,
            source_x=req_header.target_x,
            source_y=req_header.target_y,
            length=1,
            message_type=MessageType.TLB_RESP,
            send_type=SendType.SINGLE,
            tlb_req_slot=req_header.tlb_req_slot,
            ordering_wf=WidthFormatCode.WF64,
            ordering_lane_order=LaneOrder.ROW_MAJOR,
        )
        self.driver.packet_in.append({
            "isHeader": 1,
            "data": resp_header.encode(self.params),
        })
        self.driver.packet_in.append({
            "isHeader": 0,
            "data": physical_stripe,
        })

    async def run(self) -> None:
        while True:
            req_header_word = await self.driver.wait_for_packet_word()
            req_data_word = await self.driver.wait_for_packet_word()
            assert req_header_word["isHeader"] == 1
            assert req_data_word["isHeader"] == 0
            req_header = KamletTlbReqHeader.decode(
                req_header_word["data"], self.params)
            assert req_header.message_type == MessageType.TLB_REQ
            assert req_header.send_type == SendType.SINGLE
            assert req_header.length == 1
            virtual_stripe = req_data_word["data"]
            logger.info(
                "packetOut tlbReq slot=%d stripe=0x%x",
                req_header.tlb_req_slot,
                virtual_stripe,
            )
            self.requests.append((req_header.tlb_req_slot, virtual_stripe))
            self.request_count_by_stripe[virtual_stripe] = (
                self.request_count_by_stripe.get(virtual_stripe, 0) + 1)
            self.send_response(req_header, self.physical_stripe(virtual_stripe))
            logger.info(
                "packetIn tlbResp slot=%d stripe=0x%x physical=0x%x",
                req_header.tlb_req_slot,
                virtual_stripe,
                self.physical_stripe(virtual_stripe),
            )


async def tlb_requester(
    driver: KamletTlbDriver,
    j_in_k: int,
    virtual_stripe: int,
    te_index: int,
    byte_index: int,
) -> dict[str, int]:
    resp = await driver.request_once(
        j_in_k,
        virtual_stripe,
        te_index,
        byte_index,
    )
    assert resp["translation_stripeAddr"] == driver.network.physical_stripe(virtual_stripe)
    assert resp["translation_ordering_wf"] == WidthFormatCode.WF64
    assert resp["translation_ordering_laneOrder"] == LaneOrder.ROW_MAJOR
    return resp


@cocotb.test(timeout_time=TEST_TIMEOUT_NS, timeout_unit="ns")
async def tlb_round_trip_routes_response_to_requesting_jamlet(
    dut: HierarchyObject,
) -> None:
    test_utils.configure_logging_sim()
    test_params = test_utils.get_test_params()
    params = load_params(test_params)
    rng = Random(test_params["seed"])
    driver = KamletTlbDriver(dut, params)
    driver.start(rng)
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    await driver.reset()

    j_in_k = min(1, params.j_in_k - 1)
    virtual_stripe = 0x12
    resp = await driver.request_and_wait(j_in_k, virtual_stripe)
    assert len(driver.network.requests) == 1
    assert driver.network.requests[0][1] == virtual_stripe
    assert resp["translation_stripeAddr"] == driver.network.physical_stripe(virtual_stripe)
    assert resp["translation_ordering_wf"] == WidthFormatCode.WF64
    assert resp["translation_ordering_laneOrder"] == LaneOrder.ROW_MAJOR


@cocotb.test(timeout_time=TEST_TIMEOUT_NS, timeout_unit="ns")
async def repeated_stripe_hits_in_tlb_cache(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim()
    test_params = test_utils.get_test_params()
    params = load_params(test_params)
    rng = Random(test_params["seed"])
    driver = KamletTlbDriver(dut, params)
    driver.start(rng)
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    await driver.reset()

    virtual_stripe = 0x21
    first = await driver.request_and_wait(0, virtual_stripe)
    second_j = min(1, params.j_in_k - 1)
    second = await driver.request_and_wait(second_j, virtual_stripe)

    expected = driver.network.physical_stripe(virtual_stripe)
    assert first["translation_stripeAddr"] == expected
    assert second["translation_stripeAddr"] == expected
    assert driver.network.request_count_by_stripe == {virtual_stripe: 1}


@cocotb.test(timeout_time=TEST_TIMEOUT_NS, timeout_unit="ns")
async def many_requests_small_working_set_uses_one_network_request_per_stripe(
    dut: HierarchyObject,
) -> None:
    test_utils.configure_logging_sim()
    test_params = test_utils.get_test_params()
    params = load_params(test_params)
    rng = Random(test_params["seed"])
    driver = KamletTlbDriver(dut, params)
    driver.start(rng)
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    await driver.reset()

    n_stripes = min(params.tlb_req_table_depth, params.tlb_cache_table_depth)
    stripes = [0x30 + index for index in range(n_stripes)]
    tasks = []
    keys = random_tlb_keys(rng, params, n_stripes * 4)
    for index, (j_in_k, te_index, byte_index) in enumerate(keys):
        virtual_stripe = stripes[index % len(stripes)]
        tasks.append(cocotb.start_soon(tlb_requester(
            driver,
            j_in_k,
            virtual_stripe,
            te_index,
            byte_index,
        )))

    for task in tasks:
        await task

    assert driver.network.request_count_by_stripe == {
        stripe: 1 for stripe in stripes
    }


@cocotb.test(timeout_time=TEST_TIMEOUT_NS, timeout_unit="ns")
async def many_requests_large_working_set_returns_correct_translation(
    dut: HierarchyObject,
) -> None:
    test_utils.configure_logging_sim()
    test_params = test_utils.get_test_params()
    params = load_params(test_params)
    rng = Random(test_params["seed"])
    driver = KamletTlbDriver(dut, params)
    driver.start(rng)
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    await driver.reset()

    n_stripes = max(params.tlb_req_table_depth, params.tlb_cache_table_depth) + 8
    stripes = [0x80 + index for index in range(n_stripes)]
    n_requesters = min(
        n_stripes,
        params.j_in_k * params.witem_table_depth * params.word_bytes,
    )
    tasks = []
    keys = random_tlb_keys(rng, params, n_requesters)
    for index, (j_in_k, te_index, byte_index) in enumerate(keys):
        virtual_stripe = stripes[index % len(stripes)]
        tasks.append(cocotb.start_soon(tlb_requester(
            driver,
            j_in_k,
            virtual_stripe,
            te_index,
            byte_index,
        )))

    for task in tasks:
        await task
