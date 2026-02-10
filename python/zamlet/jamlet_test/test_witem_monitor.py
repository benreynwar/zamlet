import os
import sys
import json
import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Tuple

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, ReadOnly

from zamlet import test_utils
from zamlet.control_structures import pack_fields_to_int
from zamlet.jamlet.jamlet_params import JamletParams


logger = logging.getLogger(__name__)


class WitemType(IntEnum):
    """Witem types matching WitemEntry.scala"""
    LoadJ2JWords = 0
    StoreJ2JWords = 1
    LoadWordSrc = 2
    StoreWordSrc = 3
    LoadStride = 4
    StoreStride = 5
    LoadIdxUnord = 6
    StoreIdxUnord = 7
    LoadIdxElement = 8


class EwCode(IntEnum):
    """Element width codes matching EwCode in WitemEntry.scala"""
    Ew1 = 0
    Ew8 = 1
    Ew16 = 2
    Ew32 = 3
    Ew64 = 4


class WordOrder(IntEnum):
    """Word order matching WordOrder in WitemEntry.scala"""
    Standard = 0


@dataclass
class J2JInstr:
    """J2J instruction matching J2JInstr in KInstr.scala."""
    opcode: int = 0
    cache_slot: int = 0
    mem_word_order: int = WordOrder.Standard
    rf_word_order: int = WordOrder.Standard
    mem_ew: int = EwCode.Ew64
    rf_ew: int = EwCode.Ew64
    base_bit_addr: int = 0
    start_index: int = 0
    n_elements_idx: int = 0
    reg: int = 0

    def get_field_specs(self, params: JamletParams) -> List[Tuple[str, int]]:
        """Get field specifications for bit packing. Order matches Scala bundle."""
        return [
            ('opcode', 6),  # KInstrOpcode.width
            ('cache_slot', params.cache_slot_width),
            ('mem_word_order', 1),
            ('rf_word_order', 1),
            ('mem_ew', 3),
            ('rf_ew', 3),
            ('base_bit_addr', params.base_bit_addr_width),
            ('start_index', params.element_index_width),
            ('n_elements_idx', 4),  # KInstrParamIdx.width
            ('reg', params.rf_addr_width),
        ]

    def to_int(self, params: JamletParams) -> int:
        """Pack instruction into a 64-bit integer."""
        return pack_fields_to_int(self, self.get_field_specs(params))


async def wait_for_signal(dut, signal, value=1, timeout_cycles=100):
    """Wait for a signal to reach a value, with timeout."""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clock)
        await ReadOnly()
        if int(signal.value) == value:
            return True
    return False


class SramResponder:
    """Responds to SRAM read requests with configurable data. Handles one request per cycle."""

    def __init__(self, dut):
        self.dut = dut
        self.mem = {}  # addr -> data
        self.default_data = 0
        self.pending_resp = None  # data to send next cycle
        self._running = False

    def write(self, addr: int, data: int):
        self.mem[addr] = data

    async def run(self):
        self._running = True
        self.dut.io_sramResp_valid.value = 0

        while self._running:
            await RisingEdge(self.dut.clock)

            # Check if pending response was consumed
            resp_consumed = (self.pending_resp is not None and
                            int(self.dut.io_sramResp_ready.value) == 1)

            # Send pending response (or clear if consumed)
            if self.pending_resp is not None:
                self.dut.io_sramResp_valid.value = 1
                self.dut.io_sramResp_bits_readData.value = self.pending_resp
                if resp_consumed:
                    self.pending_resp = None
            else:
                self.dut.io_sramResp_valid.value = 0

            # Backpressure: only ready if no pending response (or it's being consumed)
            can_accept = self.pending_resp is None or resp_consumed
            self.dut.io_sramReq_ready.value = 1 if can_accept else 0

            # Check for new request (in ReadOnly to see current cycle's signals)
            await ReadOnly()
            if int(self.dut.io_sramReq_valid.value) and int(self.dut.io_sramReq_ready.value):
                addr = int(self.dut.io_sramReq_bits_addr.value)
                is_write = int(self.dut.io_sramReq_bits_isWrite.value)
                if not is_write:
                    assert self.pending_resp is None, "SRAM request before previous response sent"
                    data = self.mem.get(addr, self.default_data)
                    self.pending_resp = data
                    logger.info(f"SramResponder: read addr={addr} -> 0x{data:016x}")

    def stop(self):
        self._running = False


class WitemInfoResponder:
    """Responds to witemInfo requests with configurable kinstr/params."""

    def __init__(self, dut):
        self.dut = dut
        self.responses = {}  # ident -> (kinstr, base_addr, n_elements)
        self._running = False
        self.pending_resp = None

    def set_response(self, ident: int, kinstr: int, base_addr: int = 0,
                     n_elements: int = 1):
        self.responses[ident] = (kinstr, base_addr, n_elements)

    async def run(self):
        self._running = True
        self.dut.io_witemInfoResp_valid.value = 0

        while self._running:
            await RisingEdge(self.dut.clock)

            resp_consumed = (self.pending_resp is not None and
                            int(self.dut.io_witemInfoResp_ready.value) == 1)

            if self.pending_resp is not None:
                kinstr, base_addr, n_elements = self.pending_resp
                self.dut.io_witemInfoResp_valid.value = 1
                self.dut.io_witemInfoResp_bits_kinstr.value = kinstr
                self.dut.io_witemInfoResp_bits_baseAddr.value = base_addr
                self.dut.io_witemInfoResp_bits_nElements.value = n_elements
                if resp_consumed:
                    self.pending_resp = None
            else:
                self.dut.io_witemInfoResp_valid.value = 0

            can_accept = self.pending_resp is None or resp_consumed
            self.dut.io_witemInfoReq_ready.value = 1 if can_accept else 0

            await ReadOnly()
            if int(self.dut.io_witemInfoReq_valid.value) and int(self.dut.io_witemInfoReq_ready.value):
                ident = int(self.dut.io_witemInfoReq_bits_instrIdent.value)
                if ident in self.responses:
                    assert self.pending_resp is None
                    self.pending_resp = self.responses[ident]
                    logger.info(f"WitemInfoResponder: req ident={ident}")

    def stop(self):
        self._running = False


class TlbResponder:
    """Responds to TLB requests."""

    def __init__(self, dut):
        self.dut = dut
        self.translations = {}  # vaddr -> paddr
        self.default_paddr = 0
        self._running = False
        self.pending_resp = None

    def set_translation(self, vaddr: int, paddr: int):
        self.translations[vaddr] = paddr

    async def run(self):
        self._running = True
        self.dut.io_tlbResp_valid.value = 0

        while self._running:
            await RisingEdge(self.dut.clock)

            resp_consumed = (self.pending_resp is not None and
                            int(self.dut.io_tlbResp_ready.value) == 1)

            if self.pending_resp is not None:
                self.dut.io_tlbResp_valid.value = 1
                # TODO: set tlbResp bits when we know the format
                if resp_consumed:
                    self.pending_resp = None
            else:
                self.dut.io_tlbResp_valid.value = 0

            can_accept = self.pending_resp is None or resp_consumed
            self.dut.io_tlbReq_ready.value = 1 if can_accept else 0

            await ReadOnly()
            if int(self.dut.io_tlbReq_valid.value) and int(self.dut.io_tlbReq_ready.value):
                assert self.pending_resp is None
                self.pending_resp = self.default_paddr
                logger.info("TlbResponder: req")

    def stop(self):
        self._running = False


class RfResponder:
    """Responds to register file read requests."""

    def __init__(self, dut, prefix: str):
        """prefix is 'mask', 'index', or 'data'"""
        self.dut = dut
        self.prefix = prefix
        self.mem = {}  # addr -> data
        self.default_data = 0
        self._running = False
        self.pending_resp = None

    def write(self, addr: int, data: int):
        self.mem[addr] = data

    async def run(self):
        self._running = True
        getattr(self.dut, f'io_{self.prefix}RfResp_valid').value = 0

        while self._running:
            await RisingEdge(self.dut.clock)

            req_valid = getattr(self.dut, f'io_{self.prefix}RfReq_valid')
            req_ready = getattr(self.dut, f'io_{self.prefix}RfReq_ready')
            req_addr = getattr(self.dut, f'io_{self.prefix}RfReq_bits_addr')
            req_is_write = getattr(self.dut, f'io_{self.prefix}RfReq_bits_isWrite')
            resp_valid = getattr(self.dut, f'io_{self.prefix}RfResp_valid')
            resp_ready = getattr(self.dut, f'io_{self.prefix}RfResp_ready')
            resp_data = getattr(self.dut, f'io_{self.prefix}RfResp_bits_readData')

            resp_consumed = (self.pending_resp is not None and
                            int(resp_ready.value) == 1)

            if self.pending_resp is not None:
                resp_valid.value = 1
                resp_data.value = self.pending_resp
                if resp_consumed:
                    self.pending_resp = None
            else:
                resp_valid.value = 0

            can_accept = self.pending_resp is None or resp_consumed
            req_ready.value = 1 if can_accept else 0

            await ReadOnly()
            if int(req_valid.value) and int(req_ready.value):
                addr = int(req_addr.value)
                is_write = int(req_is_write.value)
                if not is_write:
                    assert self.pending_resp is None
                    data = self.mem.get(addr, self.default_data)
                    self.pending_resp = data
                    logger.info(f"RfResponder({self.prefix}): read addr={addr} -> 0x{data:016x}")

    def stop(self):
        self._running = False


class PacketOutCollector:
    """Collects packets from packetOut."""

    def __init__(self, dut):
        self.dut = dut
        self.packets = []  # list of {'header': int, 'data': [int]}
        self._running = False
        self._current_packet = None

    async def run(self):
        self._running = True

        while self._running:
            await RisingEdge(self.dut.clock)
            await ReadOnly()

            if int(self.dut.io_packetOut_valid.value) and int(self.dut.io_packetOut_ready.value):
                data = int(self.dut.io_packetOut_bits_data.value)
                is_header = int(self.dut.io_packetOut_bits_isHeader.value)

                if is_header:
                    if self._current_packet is not None:
                        self.packets.append(self._current_packet)
                    self._current_packet = {'header': data, 'data': []}
                    logger.info(f"PacketOutCollector: header=0x{data:016x}")
                else:
                    if self._current_packet is not None:
                        self._current_packet['data'].append(data)
                        logger.info(f"PacketOutCollector: data=0x{data:016x}")

    def stop(self):
        self._running = False
        if self._current_packet is not None:
            self.packets.append(self._current_packet)

    async def wait_for_packet(self, timeout_cycles=100):
        for _ in range(timeout_cycles):
            if self.packets:
                return self.packets.pop(0)
            # Also check if current packet has data (complete but not finalized)
            if self._current_packet is not None and self._current_packet['data']:
                packet = self._current_packet
                self._current_packet = None
                return packet
            await RisingEdge(self.dut.clock)
        return None


def initialize_inputs(dut: HierarchyObject) -> None:
    """Set all inputs to safe default values."""
    # Position
    dut.io_thisX.value = 0
    dut.io_thisY.value = 0

    # Witem lifecycle (Valid inputs - active low valid)
    dut.io_witemCreate_valid.value = 0
    dut.io_witemCreate_bits_instrIdent.value = 0
    dut.io_witemCreate_bits_witemType.value = 0
    dut.io_witemCreate_bits_cacheIsAvail.value = 0

    dut.io_witemCacheAvail_valid.value = 0
    dut.io_witemCacheAvail_bits.value = 0

    dut.io_witemRemove_valid.value = 0
    dut.io_witemRemove_bits.value = 0

    # State updates (Valid inputs)
    dut.io_witemSrcUpdate_valid.value = 0
    dut.io_witemDstUpdate_valid.value = 0

    # Sync inputs (Valid inputs)
    dut.io_witemFaultSync_valid.value = 0
    dut.io_witemCompletionSync_valid.value = 0

    # Response interfaces (Decoupled - set ready/valid)
    dut.io_witemInfoReq_ready.value = 1
    dut.io_witemInfoResp_valid.value = 0
    dut.io_witemInfoResp_bits_kinstr.value = 0
    dut.io_witemInfoResp_bits_baseAddr.value = 0
    dut.io_witemInfoResp_bits_nElements.value = 0

    dut.io_tlbReq_ready.value = 1
    dut.io_tlbResp_valid.value = 0

    dut.io_sramReq_ready.value = 1
    dut.io_sramResp_valid.value = 0

    dut.io_maskRfReq_ready.value = 1
    dut.io_maskRfResp_valid.value = 0

    dut.io_indexRfReq_ready.value = 1
    dut.io_indexRfResp_valid.value = 0

    dut.io_dataRfReq_ready.value = 1
    dut.io_dataRfResp_valid.value = 0

    dut.io_packetOut_ready.value = 1


async def reset(dut: HierarchyObject) -> None:
    """Reset the module."""
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)


async def create_witem(dut: HierarchyObject, ident: int, witem_type: WitemType,
                       cache_avail: bool = True) -> None:
    """Create a witem entry."""
    dut.io_witemCreate_valid.value = 1
    dut.io_witemCreate_bits_instrIdent.value = ident
    dut.io_witemCreate_bits_witemType.value = int(witem_type)
    dut.io_witemCreate_bits_cacheIsAvail.value = 1 if cache_avail else 0
    await RisingEdge(dut.clock)
    dut.io_witemCreate_valid.value = 0


async def basic_create_test(dut: HierarchyObject) -> None:
    """Test creating a single witem entry."""
    await create_witem(dut, ident=1, witem_type=WitemType.LoadJ2JWords)

    # Wait a few cycles
    for _ in range(5):
        await RisingEdge(dut.clock)

    # Check no errors
    await ReadOnly()
    assert dut.io_err_noFreeSlot.value == 0, "Unexpected noFreeSlot error"
    assert dut.io_err_priorityOverflow.value == 0, "Unexpected priorityOverflow error"

    logger.info("basic_create_test passed")


async def witem_info_handshake_test(dut: HierarchyObject, params: JamletParams) -> None:
    """Test the witemInfoReq/Resp handshake after creating an entry."""
    test_ident = 42

    # Create a witem entry
    await create_witem(dut, ident=test_ident, witem_type=WitemType.LoadJ2JWords)

    # Wait for witemInfoReq to be valid (returns in ReadOnly phase)
    found = await wait_for_signal(dut, dut.io_witemInfoReq_valid, value=1, timeout_cycles=20)
    assert found, "witemInfoReq never became valid"

    # Check the request has correct ident (already in ReadOnly from wait_for_signal)
    req_ident = int(dut.io_witemInfoReq_bits_instrIdent.value)
    assert req_ident == test_ident, f"Expected ident {test_ident}, got {req_ident}"
    logger.info(f"witemInfoReq received with ident={req_ident}")

    # Create a proper J2JInstr for LoadJ2JWords
    kinstr = J2JInstr(
        cache_slot=0,
        mem_word_order=WordOrder.Standard,
        rf_word_order=WordOrder.Standard,
        mem_ew=EwCode.Ew64,
        rf_ew=EwCode.Ew64,
        base_bit_addr=0,
        start_index=0,
        n_elements_idx=0,
        reg=0,
    )
    kinstr_packed = kinstr.to_int(params)
    logger.info(f"Packed kinstr: 0x{kinstr_packed:016x}")

    # Respond with witemInfoResp
    await RisingEdge(dut.clock)
    dut.io_witemInfoResp_valid.value = 1
    dut.io_witemInfoResp_bits_kinstr.value = kinstr_packed
    dut.io_witemInfoResp_bits_baseAddr.value = 0
    dut.io_witemInfoResp_bits_nElements.value = 1

    # Wait for response to be consumed
    found = await wait_for_signal(dut, dut.io_witemInfoResp_ready, value=1, timeout_cycles=10)
    assert found, "witemInfoResp_ready never became high"

    await RisingEdge(dut.clock)
    dut.io_witemInfoResp_valid.value = 0

    logger.info("witem_info_handshake_test passed")


async def load_j2j_packet_test(dut: HierarchyObject, params: JamletParams) -> None:
    """Test LoadJ2JWords flow through sramReq/sramResp to packetOut."""
    test_ident = 100
    test_data = 0xDEADBEEF_CAFEBABE

    # Create J2JInstr for LoadJ2JWords (64-bit elements, 1 element)
    kinstr = J2JInstr(
        cache_slot=0,
        mem_word_order=WordOrder.Standard,
        rf_word_order=WordOrder.Standard,
        mem_ew=EwCode.Ew64,
        rf_ew=EwCode.Ew64,
        base_bit_addr=0,
        start_index=0,
        n_elements_idx=0,
        reg=0,
    )
    kinstr_packed = kinstr.to_int(params)

    # Start responders
    sram = SramResponder(dut)
    sram.write(0, test_data)
    cocotb.start_soon(sram.run())

    witem_info = WitemInfoResponder(dut)
    witem_info.set_response(test_ident, kinstr_packed, base_addr=0, n_elements=1)
    cocotb.start_soon(witem_info.run())

    packet_out = PacketOutCollector(dut)
    cocotb.start_soon(packet_out.run())

    # Create a witem entry - responders handle the rest automatically
    await create_witem(dut, ident=test_ident, witem_type=WitemType.LoadJ2JWords)

    # Wait for packet to be collected
    packet = await packet_out.wait_for_packet(timeout_cycles=100)
    assert packet is not None, "No packet received"

    logger.info(f"Received packet: header=0x{packet['header']:016x}, data={[hex(d) for d in packet['data']]}")

    # Verify packet contents
    assert len(packet['data']) == 1, f"Expected 1 data word, got {len(packet['data'])}"
    assert packet['data'][0] == test_data, \
        f"Expected data 0x{test_data:016x}, got 0x{packet['data'][0]:016x}"

    sram.stop()
    witem_info.stop()
    packet_out.stop()
    logger.info("load_j2j_packet_test passed")


@cocotb.test()
async def witem_monitor_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")

    # Load params
    test_params = test_utils.get_test_params()
    with open(test_params['params_file']) as f:
        params = JamletParams.from_dict(json.load(f))

    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    # Initialize and reset
    initialize_inputs(dut)
    await reset(dut)

    # Run tests
    await basic_create_test(dut)

    # Reset for next test (need RisingEdge to exit ReadOnly phase)
    await RisingEdge(dut.clock)
    initialize_inputs(dut)
    await reset(dut)

    await witem_info_handshake_test(dut, params)

    # Reset for next test
    await RisingEdge(dut.clock)
    initialize_inputs(dut)
    await reset(dut)

    await load_j2j_packet_test(dut, params)


def test_witem_monitor(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]

    toplevel = "WitemMonitor"
    module = "zamlet.jamlet_test.test_witem_monitor"

    test_params = {
        "seed": seed,
        "params_file": params_file,
    }

    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")

    if len(sys.argv) >= 3:
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_witem_monitor(verilog_file, config_file)
    else:
        print("Usage: python test_witem_monitor.py <verilog_file> <config_file>")
        sys.exit(1)
