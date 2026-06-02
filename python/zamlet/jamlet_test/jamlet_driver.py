from collections import deque
from random import Random

import cocotb
from cocotb.handle import HierarchyObject
from cocotb.triggers import Event, ReadOnly, RisingEdge

from zamlet.lane_order import LaneOrder
from zamlet.message import CacheLineHeader, MessageType, SendType
from zamlet.params import ZamletParams
from zamlet.future import Future
from zamlet.test_helpers.packets import NetworkPacketSink, NetworkPacketSource
from zamlet.utils import make_seed
from zamlet.width_codes import WidthFormatCode


def _next_network_output_direction(
    this_x: int,
    this_y: int,
    target_x: int,
    target_y: int,
) -> str:
    if target_x > this_x:
        return "eo"
    if target_x < this_x:
        return "wo"
    if target_y > this_y:
        return "so"
    if target_y < this_y:
        return "no"
    raise ValueError("target is local to this jamlet")


def _check_error_wire(dut: HierarchyObject, prefix: str, name: str, description: str) -> None:
    if int(getattr(dut, f"{prefix}_{name}").value):
        raise AssertionError(description)


def check_jte_error_wires(dut: HierarchyObject, prefix: str) -> None:
    _check_error_wire(dut, prefix, "createSlotInUse", "JTE create slot already in use")
    _check_error_wire(dut, prefix, "slotToRegInvalid", "JTE slot-to-reg request for invalid slot")
    _check_error_wire(dut, prefix, "receiverUpdateInvalid", "JTE receiver update for invalid slot")
    _check_error_wire(
        dut,
        prefix,
        "receiverUpdateIdentMismatch",
        "JTE receiver update ident mismatch",
    )
    _check_error_wire(
        dut,
        prefix,
        "initiatorCommitInvalid",
        "JTE initiator commit for invalid slot",
    )


def check_jce_error_wires(dut: HierarchyObject, prefix: str) -> None:
    _check_error_wire(dut, prefix, "badRxLength", "JCE received bad cache-line packet length")
    _check_error_wire(dut, prefix, "badRxMessageType", "JCE received bad cache-line message type")


def check_local_exec_alu_error_wires(dut: HierarchyObject, prefix: str) -> None:
    _check_error_wire(dut, prefix, "unsupportedEw", "LocalExec ALU unsupported EW")
    _check_error_wire(dut, prefix, "unsupportedWf", "LocalExec ALU unsupported WF")
    _check_error_wire(
        dut,
        prefix,
        "unsupportedEwWfRatio",
        "LocalExec ALU unsupported EW/WF ratio",
    )


def check_local_exec_error_wires(dut: HierarchyObject, prefix: str) -> None:
    _check_error_wire(dut, prefix, "unsupportedOpcode", "LocalExec unsupported opcode")
    check_local_exec_alu_error_wires(dut, f"{prefix}_alu")


def check_error_wires(dut: HierarchyObject, prefix: str) -> None:
    check_jte_error_wires(dut, f"{prefix}_jte")
    check_jce_error_wires(dut, f"{prefix}_jce")
    check_local_exec_error_wires(dut, f"{prefix}_localExec")
    _check_error_wire(
        dut,
        f"{prefix}_aHoRouter",
        "badMessageType",
        "Jamlet A local packet message type is not routed",
    )


async def monitor_error_wires(dut: HierarchyObject, prefix: str) -> None:
    while True:
        await RisingEdge(dut.clock)
        await ReadOnly()
        check_error_wires(dut, prefix)


class JamletDriver:
    def __init__(
        self,
        dut: HierarchyObject,
        params: ZamletParams,
        this_x: int,
        this_y: int,
        memlet_x: int,
        memlet_y: int,
        seed: int,
    ):
        self.dut = dut
        self.params = params
        self.rng = Random(seed)
        self.this_x = this_x
        self.this_y = this_y
        self.memlet_x = memlet_x
        self.memlet_y = memlet_y
        self.cache_response_futures = deque()
        self.b_out_direction = _next_network_output_direction(
            this_x, this_y, memlet_x, memlet_y)
        self.a_west_in = NetworkPacketSource(dut, dut.clock, "io_aChannels_wi_0")
        self.b_out = NetworkPacketSink(
            dut, dut.clock, f"io_bChannels_{self.b_out_direction}_0", params)
        self.set_defaults()

    def _prefix(self, kind: str, direction: str, channel: int = 0) -> str:
        return f"io_{kind}Channels_{direction}_{channel}"

    def set_defaults(self) -> None:
        for kind in ("a", "b"):
            for direction in ("ni", "si", "ei", "wi"):
                getattr(self.dut, f"{self._prefix(kind, direction)}_valid").value = 0
            for direction in ("no", "so", "eo", "wo"):
                getattr(self.dut, f"{self._prefix(kind, direction)}_ready").value = 1

        self.dut.io_jteCreate_valid.value = 0
        self.dut.io_jteCreate_bits_slot.value = 0
        self.dut.io_jteCreate_bits_instrIdent.value = 0
        self.dut.io_jteCreate_bits_dataReg.value = 0
        self.dut.io_jteClear_valid.value = 0
        self.dut.io_jteClear_bits.value = 0
        self.dut.io_jteInputReq_ready.value = 1
        self.dut.io_jteInputResp_valid.value = 0
        self.dut.io_tlbReq_ready.value = 1
        self.dut.io_tlbResp_valid.value = 0
        self.dut.io_orderingReq_ready.value = 1
        self.dut.io_orderingResp_valid.value = 0
        self.dut.io_cacheLineReq_ready.value = 1
        self.dut.io_cacheLineResp_valid.value = 0
        self.dut.io_immediateKinstr_valid.value = 0
        self.dut.io_immediateKinstr_bits_kinstr.value = 0
        self.dut.io_immediateKinstr_bits_ordering_wf.value = WidthFormatCode.WF64
        self.dut.io_immediateKinstr_bits_ordering_laneOrder.value = LaneOrder.ROW_MAJOR
        self.dut.io_immediateKinstr_bits_cacheSlot.value = 0
        self.dut.io_immediateKinstr_bits_sramWordOffset.value = 0
        self.dut.io_immediateKinstr_bits_param0.value = 0
        self.dut.io_immediateKinstr_bits_param1.value = 0
        self.dut.io_immediateKinstr_bits_param2.value = 0
        self.dut.io_sendCacheLine_valid.value = 0
        self.dut.io_sendCacheLine_bits_slot.value = 0

        self.dut.reset.value = 0
        self.dut.io_thisX.value = self.this_x
        self.dut.io_thisY.value = self.this_y
        self.dut.io_memletX.value = self.memlet_x
        self.dut.io_memletY.value = self.memlet_y
        for i in range(LaneOrder.count()):
            getattr(self.dut, f"io_laneIndices_{i}").value = 0

    def start(self, p_valid: float = 1.0, p_ready: float = 1.0) -> None:
        self.a_west_in.start(seed=make_seed(self.rng), p_valid=p_valid)
        self.b_out.start(seed=make_seed(self.rng), p_ready=p_ready)
        cocotb.start_soon(self._cache_response_monitor())
        cocotb.start_soon(monitor_error_wires(self.dut, "io_errors"))

    async def reset(self) -> None:
        await RisingEdge(self.dut.clock)
        self.dut.reset.value = 1
        await RisingEdge(self.dut.clock)
        self.dut.reset.value = 0
        await RisingEdge(self.dut.clock)
        await RisingEdge(self.dut.clock)

    async def send_read_line_resp(self, slot: int, words: list[int]) -> None:
        assert len(words) == self.params.cache_slot_words_per_jamlet
        response = self.get_cache_response_future()

        header = CacheLineHeader(
            target_x=self.this_x,
            target_y=self.this_y,
            source_x=self.memlet_x,
            source_y=self.memlet_y,
            length=self.params.cache_slot_words_per_jamlet,
            message_type=MessageType.READ_LINE_RESP,
            send_type=SendType.SINGLE,
            slot=slot,
        ).encode(self.params)
        self.a_west_in.enqueue_packet([(header, True)] + [(word, False) for word in words])

        actual_slot = await response
        assert actual_slot == slot

    async def send_cache_line(self, slot: int) -> list[int]:
        packet_future = self.b_out.get_packet_future()

        await RisingEdge(self.dut.clock)
        self.dut.io_sendCacheLine_valid.value = 1
        self.dut.io_sendCacheLine_bits_slot.value = slot
        await RisingEdge(self.dut.clock)
        self.dut.io_sendCacheLine_valid.value = 0

        packet = await packet_future
        header = packet[0]
        assert isinstance(header, CacheLineHeader)
        assert header.target_x == self.memlet_x
        assert header.target_y == self.memlet_y
        assert header.source_x == self.this_x
        assert header.source_y == self.this_y
        assert header.message_type == MessageType.WRITE_LINE_DATA
        assert header.send_type == SendType.SINGLE
        assert header.length == self.params.cache_slot_words_per_jamlet
        assert header.slot == slot
        return packet[1:]

    def get_cache_response_future(self) -> Future:
        future = Future(Event())
        self.cache_response_futures.append(future)
        return future

    async def _cache_response_monitor(self) -> None:
        while True:
            await RisingEdge(self.dut.clock)
            await ReadOnly()
            if int(self.dut.io_cacheResponse_valid.value):
                assert self.cache_response_futures, "unexpected cacheResponse"
                self.cache_response_futures.popleft().set_result(
                    int(self.dut.io_cacheResponse_bits.value))

    def status(self) -> str:
        return (
            f"coords this=({self.this_x},{self.this_y}) "
            f"memlet=({self.memlet_x},{self.memlet_y}) "
            f"b_out={self.b_out_direction} "
            f"a_west_in={len(self.a_west_in.queue)} "
            f"cache_response_futures={len(self.cache_response_futures)} "
            f"b_packets={len(self.b_out.packet_queue)}"
        )
