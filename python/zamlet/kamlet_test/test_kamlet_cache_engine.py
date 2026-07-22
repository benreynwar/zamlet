import json

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from zamlet import test_utils
from zamlet.params import ZamletParams
from zamlet.test_utils import next_drive_phase


def load_params(test_params: dict) -> ZamletParams:
    with open(test_params["params_file"]) as f:
        return ZamletParams.from_dict(json.load(f))


def initialize_inputs(dut: HierarchyObject, params: ZamletParams) -> None:
    """Tie off the KCE top-level inputs for a build/simulation smoke test."""
    dut.io_knetX.value = 0
    dut.io_knetY.value = 0
    dut.io_memletKnetX.value = 0
    dut.io_memletKnetY.value = 0
    dut.io_packetIn_valid.value = 0
    dut.io_packetIn_bits_isHeader.value = 0
    dut.io_packetIn_bits_data.value = 0
    dut.io_packetOut_ready.value = 0
    dut.io_kteReleaseSlot_valid.value = 0
    dut.io_kteReleaseSlot_bits_slot.value = 0
    dut.io_kteSlotStatusReq_valid.value = 0
    dut.io_kteSlotStatusReq_bits.value = 0
    dut.io_kteInstrStartedResp_valid.value = 0
    dut.io_kteInstrStartedNotify_valid.value = 0
    dut.io_rsAllocSlotReq_valid.value = 0
    dut.io_rsAllocSlotReq_bits_cacheLineAddr.value = 0
    dut.io_rsAllocSlotReq_bits_willWrite.value = 0
    dut.io_rsAllocSlotResp_ready.value = 0

    for lane in range(params.j_in_k):
        for prefix, suffix in (
            ("jteCacheLineReq", "valid"),
            ("jteCacheLineResp", "ready"),
            ("jteReplay", "ready"),
            ("jteCacheLineRelease", "valid"),
            ("jceFetchDone", "valid"),
        ):
            getattr(dut, f"io_{prefix}_{lane}_{suffix}").value = 0


@cocotb.test()
async def smoke_build_and_reset(dut: HierarchyObject) -> None:
    """Minimal smoke test: build, load, reset, and run a few idle cycles."""
    test_params = test_utils.get_test_params()
    params = load_params(test_params)
    initialize_inputs(dut, params)
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    dut.reset.value = 1
    await next_drive_phase(dut.clock)
    await next_drive_phase(dut.clock)
    dut.reset.value = 0

    for _ in range(5):
        await next_drive_phase(dut.clock)
