"""Deque-backed driver for KamletMeshWithMemlets cocotb tests."""

import logging
from random import Random

import cocotb
from cocotb.handle import HierarchyObject
from cocotb.triggers import ReadOnly, RisingEdge

from zamlet.addresses import Ordering
from zamlet.message import (
    Header,
    KamletTlbReqHeader,
    KamletTlbRespHeader,
    MessageType,
    SendType,
)
from zamlet.params import ZamletParams
from zamlet.cocotb.axi_memory import Axi4Signals
from zamlet import kamlet_network
from zamlet.kamlet_test.ordered_kamlet_memory import (
    OrderedKamletAxiMemory,
    OrderedKamletMemory,
)
from zamlet.lane_order import vw_index_to_j_coords
from zamlet.test_helpers.packets import NetworkPacketSink, NetworkPacketSource
from zamlet.width_codes import wf_code


logger = logging.getLogger(__name__)


class KamletMeshWithMemletsDriver:
    def __init__(self, dut: HierarchyObject, params: ZamletParams):
        self.dut = dut
        self.params = params
        self.memory = OrderedKamletMemory(params)

        self.n_kamlet_a_in = [
            NetworkPacketSource(dut, dut.clock, f"io_nKamletAIn_{kx}_0")
            for kx in range(params.k_cols)
        ]
        self.n_kamlet_a_out = [
            NetworkPacketSink(dut, dut.clock, f"io_nKamletAOut_{kx}_0", params)
            for kx in range(params.k_cols)
        ]
        self.n_kamlet_b_in = [
            NetworkPacketSource(dut, dut.clock, f"io_nKamletBIn_{kx}_0")
            for kx in range(params.k_cols)
        ]
        self.n_kamlet_b_out = [
            NetworkPacketSink(dut, dut.clock, f"io_nKamletBOut_{kx}_0", params)
            for kx in range(params.k_cols)
        ]

        n_channels = params.n_a_channels + params.n_b_channels
        self.n_jnet_in = {
            (kx, jx, ch): NetworkPacketSource(
                dut, dut.clock, f"io_nChannelsIn_{kx}_{jx}_{ch}")
            for kx in range(params.k_cols)
            for jx in range(params.j_cols)
            for ch in range(n_channels)
        }
        self.n_jnet_out = {
            (kx, jx, ch): NetworkPacketSink(
                dut, dut.clock, f"io_nChannelsOut_{kx}_{jx}_{ch}", params)
            for kx in range(params.k_cols)
            for jx in range(params.j_cols)
            for ch in range(n_channels)
        }

    def configure_coords(self) -> None:
        self.dut.io_knetOffsetX.value = self.params.k_cols // 2
        self.dut.io_knetOffsetY.value = 1
        self.dut.io_lamletKnetX.value = self.params.k_cols // 2
        self.dut.io_lamletKnetY.value = 0

    def initialize_inputs(self) -> None:
        self.configure_coords()

        for source in [
            *self.n_kamlet_a_in,
            *self.n_kamlet_b_in,
            *self.n_jnet_in.values(),
        ]:
            source.valid.value = 0

        for sink in [
            *self.n_kamlet_a_out,
            *self.n_kamlet_b_out,
            *self.n_jnet_out.values(),
        ]:
            sink.ready.value = 0

        for name in ('nSyncN', 'nSyncNE', 'nSyncNW'):
            for kx in range(self.params.k_cols):
                getattr(self.dut, f'io_{name}_{kx}_in_valid').value = 0
                getattr(self.dut, f'io_{name}_{kx}_in_bits').value = 0

    def start(self, rng: Random) -> None:
        self._start_axi_memories()
        for source in self.n_kamlet_a_in:
            source.start(rng)
        for sink in self.n_kamlet_a_out:
            sink.start(rng)
        for source in self.n_kamlet_b_in:
            source.start(rng)
        for sink in self.n_kamlet_b_out:
            sink.start(rng)
        for source in self.n_jnet_in.values():
            source.start(rng)
        for sink in self.n_jnet_out.values():
            sink.start(rng)
        self.start_tlb_responder()

    def _start_axi_memories(self) -> None:
        for idx in range(self.params.k_in_l):
            signals = Axi4Signals.from_prefix(self.dut, f'io_axi_{idx}')
            memory = OrderedKamletAxiMemory(
                signals, self.dut.clock, self.params, self.memory, idx)
            memory.start()

    def log_debug_state(self) -> None:
        logger.debug(
            'driver queues nKamletAIn=%s nKamletBIn=%s nKamletAOut=%s nKamletBOut=%s',
            [len(source.queue) for source in self.n_kamlet_a_in],
            [len(source.queue) for source in self.n_kamlet_b_in],
            [len(sink.packet_queue) for sink in self.n_kamlet_a_out],
            [len(sink.packet_queue) for sink in self.n_kamlet_b_out],
        )

    def _rf_word_handle(self, kx: int, ky: int, jy: int, jx: int, rf_addr: int):
        kamlet = getattr(self.dut.mesh, f"kamlets_{kx}_{ky}")
        jamlet = getattr(kamlet, f"jamlets_{jy}_{jx}")
        return getattr(
            jamlet.rfSlice,
            f"mem_{rf_addr}",
        )

    def read_rf_elements(
        self,
        rf_addr: int,
        ordering: Ordering,
        n_elements: int,
    ) -> list[int]:
        assert 8 <= ordering.ew <= self.params.word_width
        assert ordering.ew % 8 == 0
        assert self.params.word_width % ordering.ew == 0
        elements_per_word = self.params.word_width // ordering.ew
        element_mask = (1 << ordering.ew) - 1
        elements = []
        for element_index in range(n_elements):
            vw_index = element_index % self.params.j_in_l
            element_in_lane = element_index // self.params.j_in_l
            rf_word_offset = element_in_lane // elements_per_word
            element_in_word = element_in_lane % elements_per_word
            global_jx, global_jy = vw_index_to_j_coords(
                self.params, ordering.word_order, vw_index)
            kx = global_jx // self.params.j_cols
            ky = global_jy // self.params.j_rows
            local_jx = global_jx % self.params.j_cols
            local_jy = global_jy % self.params.j_rows
            word = int(self._rf_word_handle(
                kx, ky, local_jy, local_jx, rf_addr + rf_word_offset).value)
            elements.append(
                (word >> (element_in_word * ordering.ew)) & element_mask)
        return elements

    async def wait_for_rf_elements(
        self,
        rf_addr: int,
        ordering: Ordering,
        expected: list[int],
        timeout_cycles: int,
    ) -> list[int]:
        for _ in range(timeout_cycles):
            await RisingEdge(self.dut.clock)
            await ReadOnly()
            actual = self.read_rf_elements(rf_addr, ordering, len(expected))
            if actual == expected:
                return actual
        logger.error(
            'RF mismatch rf_addr=%d expected=%s actual=%s',
            rf_addr,
            [f'0x{element:x}' for element in expected],
            [f'0x{element:x}' for element in actual],
        )
        self.log_debug_state()
        assert False, f'RF elements did not match: {actual}'

    async def reset(self) -> None:
        self.dut.reset.value = 1
        await RisingEdge(self.dut.clock)
        await RisingEdge(self.dut.clock)
        self.dut.reset.value = 0
        await RisingEdge(self.dut.clock)
        await RisingEdge(self.dut.clock)
        await RisingEdge(self.dut.clock)

    def enqueue_instructions(self, encoded_kinstrs: list[int]) -> None:
        params = self.params
        header_field_widths = dict(params.abstract_base_header_fields)
        max_packet_body_words = (1 << header_field_widths['length']) - 1
        assert encoded_kinstrs
        source_x, source_y = kamlet_network.lamlet_kcoord(params)
        target_x, target_y = kamlet_network.kamlet_kcoord(params, params.k_in_l - 1)
        for start in range(0, len(encoded_kinstrs), max_packet_body_words):
            chunk = encoded_kinstrs[start:start + max_packet_body_words]
            header = Header(
                target_x=target_x,
                target_y=target_y,
                source_x=source_x,
                source_y=source_y,
                length=len(chunk),
                message_type=MessageType.INSTRUCTIONS,
                send_type=SendType.BROADCAST,
            )
            logger.debug(
                'enqueue instructions source=(%d,%d) target=(%d,%d) length=%d words=%s',
                source_x,
                source_y,
                target_x,
                target_y,
                len(chunk),
                [f'0x{word:016x}' for word in chunk],
            )
            self.n_kamlet_b_in[0].enqueue_packet(
                header.encode(params),
                chunk,
            )

    def start_tlb_responder(self) -> 'KamletMeshTlbResponder':
        responder = KamletMeshTlbResponder(self)
        responder.start()
        return responder


class KamletMeshTlbResponder:
    def __init__(self, driver: KamletMeshWithMemletsDriver):
        self.driver = driver
        self.params = driver.params
        self.requests: list[tuple[int, int]] = []

    def start(self) -> None:
        for kx in range(self.params.k_cols):
            cocotb.start_soon(self.run(kx))

    async def run(self, kx: int) -> None:
        sink = self.driver.n_kamlet_b_out[kx]
        while True:
            while sink.packet_queue:
                self.handle_packet(kx, sink.packet_queue.popleft())
            await RisingEdge(self.driver.dut.clock)

    def handle_packet(self, kx: int, packet: list[object]) -> None:
        assert len(packet) == 2
        req_header = packet[0]
        assert isinstance(req_header, KamletTlbReqHeader)
        assert req_header.message_type == MessageType.TLB_REQ
        logical_stripe_addr = packet[1]
        assert isinstance(logical_stripe_addr, int)

        mapping = self.driver.memory.translate_logical_stripe(logical_stripe_addr)
        physical_stripe_addr = (
            (mapping.physical_stripe_addr // self.params.cache_slot_words_per_jamlet)
            << self.params.log2_page_words_per_jamlet
        ) | (mapping.physical_stripe_addr % self.params.cache_slot_words_per_jamlet)
        self.requests.append((req_header.tlb_req_slot, logical_stripe_addr))
        logger.debug(
            'tlb req kx=%d slot=%d logical_stripe=0x%x physical_stripe=0x%x',
            kx,
            req_header.tlb_req_slot,
            logical_stripe_addr,
            physical_stripe_addr,
        )

        resp_header = KamletTlbRespHeader(
            target_x=req_header.source_x,
            target_y=req_header.source_y,
            source_x=req_header.target_x,
            source_y=req_header.target_y,
            length=1,
            message_type=MessageType.TLB_RESP,
            send_type=SendType.SINGLE,
            tlb_req_slot=req_header.tlb_req_slot,
            ordering_wf=wf_code(mapping.ordering.ew),
            ordering_lane_order=mapping.ordering.word_order,
        )
        self.driver.n_kamlet_a_in[kx].enqueue_packet(
            resp_header.encode(self.params),
            [physical_stripe_addr],
        )
