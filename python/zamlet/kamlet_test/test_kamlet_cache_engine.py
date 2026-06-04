import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge


def _set_if_present(dut: HierarchyObject, name: str, value: int) -> None:
    try:
        getattr(dut, name).value = value
    except AttributeError:
        pass


def initialize_inputs(dut: HierarchyObject) -> None:
    """Tie off the KCE top-level inputs for a build/simulation smoke test."""
    for name in (
        "io_knetX",
        "io_knetY",
        "io_memletKnetX",
        "io_memletKnetY",
        "io_packetIn_valid",
        "io_packetIn_bits_isHeader",
        "io_packetIn_bits_data",
        "io_packetOut_ready",
        "io_kteClaimSlotReq_valid",
        "io_kteReleaseSlot_valid",
        "io_kteAllocSlotReq_valid",
        "io_kteClaimSlotResp_ready",
        "io_kteAllocSlotResp_ready",
        "io_rsClaimSlotReq_valid",
    ):
        _set_if_present(dut, name, 0)

    for lane in range(16):
        for prefix, suffix in (
            ("jteCacheLineReq", "valid"),
            ("jteCacheLineResp", "ready"),
            ("jteReplay", "ready"),
            ("jteCacheLineRelease", "valid"),
            ("jceFetchDone", "valid"),
        ):
            _set_if_present(dut, f"io_{prefix}_{lane}_{suffix}", 0)


@cocotb.test()
async def smoke_build_and_reset(dut: HierarchyObject) -> None:
    """Minimal smoke test: build, load, reset, and run a few idle cycles."""
    initialize_inputs(dut)
    cocotb.start_soon(Clock(dut.clock, 1, "ns").start())

    dut.reset.value = 1
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    dut.reset.value = 0

    for _ in range(5):
        await RisingEdge(dut.clock)
