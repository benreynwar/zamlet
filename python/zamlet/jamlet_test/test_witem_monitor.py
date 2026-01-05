import os
import sys
import json
import logging
from enum import IntEnum

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, ReadOnly

from zamlet import test_utils


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


async def wait_for_signal(dut, signal, value=1, timeout_cycles=100):
    """Wait for a signal to reach a value, with timeout."""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clock)
        await ReadOnly()
        if int(signal.value) == value:
            return True
    return False


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
    dut.io_witemInfoResp_bits_strideBytes.value = 0
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


async def witem_info_handshake_test(dut: HierarchyObject) -> None:
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

    # Respond with witemInfoResp (minimal valid response for LoadJ2JWords)
    await RisingEdge(dut.clock)
    dut.io_witemInfoResp_valid.value = 1
    dut.io_witemInfoResp_bits_kinstr.value = 0  # Minimal kinstr
    dut.io_witemInfoResp_bits_baseAddr.value = 0
    dut.io_witemInfoResp_bits_strideBytes.value = 0
    dut.io_witemInfoResp_bits_nElements.value = 1

    # Wait for response to be consumed
    found = await wait_for_signal(dut, dut.io_witemInfoResp_ready, value=1, timeout_cycles=10)
    assert found, "witemInfoResp_ready never became high"

    await RisingEdge(dut.clock)
    dut.io_witemInfoResp_valid.value = 0

    logger.info("witem_info_handshake_test passed")


@cocotb.test()
async def witem_monitor_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")

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

    await witem_info_handshake_test(dut)


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
