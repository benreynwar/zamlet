import os
import sys
import logging

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, ReadOnly, ClockCycles

from zamlet import test_utils
from zamlet.instructions.encode import encode_vle, encode_vse


logger = logging.getLogger(__name__)


def initialize_inputs(dut: HierarchyObject) -> None:
    """Set all inputs to safe default values."""
    # Instruction input
    dut.io_ex_valid.value = 0
    dut.io_ex_bits_inst.value = 0
    dut.io_ex_bits_rs1Data.value = 0
    dut.io_ex_bits_vl.value = 0
    dut.io_ex_bits_vstart.value = 0
    dut.io_ex_bits_vsew.value = 0

    # TLB response
    dut.io_tlbResp_paddr.value = 0
    dut.io_tlbResp_miss.value = 0
    dut.io_tlbResp_pfLd.value = 0
    dut.io_tlbResp_pfSt.value = 0
    dut.io_tlbResp_aeLd.value = 0
    dut.io_tlbResp_aeSt.value = 0

    # Control
    dut.io_kill.value = 0

    # TLB request ready (accept TLB requests)
    dut.io_tlbReq_ready.value = 1

    # Mesh output ready
    dut.io_mesh_ready.value = 1

    # Sync port input
    dut.io_syncPortSIn_valid.value = 0
    dut.io_syncPortSIn_bits.value = 0


async def reset(dut: HierarchyObject) -> None:
    """Reset the module."""
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)


async def send_instruction(dut: HierarchyObject, inst: int, rs1_data: int,
                           vl: int, vstart: int, vsew: int) -> None:
    """Send an instruction to the Lamlet."""
    dut.io_ex_valid.value = 1
    dut.io_ex_bits_inst.value = inst
    dut.io_ex_bits_rs1Data.value = rs1_data
    dut.io_ex_bits_vl.value = vl
    dut.io_ex_bits_vstart.value = vstart
    dut.io_ex_bits_vsew.value = vsew

    # Wait for ready
    while True:
        await RisingEdge(dut.clock)
        await ReadOnly()
        if int(dut.io_ex_ready.value) == 1:
            break

    # Deassert valid after handshake
    await RisingEdge(dut.clock)
    dut.io_ex_valid.value = 0


async def wait_for_tlb_request(dut: HierarchyObject, timeout_cycles: int = 100):
    """Wait for a TLB request. Returns vaddr or None on timeout."""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clock)
        await ReadOnly()
        if int(dut.io_tlbReq_valid.value) == 1:
            vaddr = int(dut.io_tlbReq_bits_vaddr.value)
            cmd = int(dut.io_tlbReq_bits_cmd.value)
            return (vaddr, cmd)
    return None


async def respond_tlb(dut: HierarchyObject, paddr: int, miss: bool = False,
                      pf_ld: bool = False, pf_st: bool = False,
                      ae_ld: bool = False, ae_st: bool = False) -> None:
    """Respond to a TLB request (combinational response, should be set same cycle)."""
    dut.io_tlbResp_paddr.value = paddr
    dut.io_tlbResp_miss.value = 1 if miss else 0
    dut.io_tlbResp_pfLd.value = 1 if pf_ld else 0
    dut.io_tlbResp_pfSt.value = 1 if pf_st else 0
    dut.io_tlbResp_aeLd.value = 1 if ae_ld else 0
    dut.io_tlbResp_aeSt.value = 1 if ae_st else 0


async def wait_for_mesh_packet(dut: HierarchyObject, timeout_cycles: int = 100):
    """Wait for a mesh packet. Returns (is_header, data) or None on timeout."""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clock)
        await ReadOnly()
        if int(dut.io_mesh_valid.value) == 1:
            is_header = int(dut.io_mesh_bits_isHeader.value)
            data = int(dut.io_mesh_bits_data.value)
            return (is_header, data)
    return None


async def collect_mesh_packets(dut: HierarchyObject, count: int,
                               timeout_cycles: int = 200):
    """Collect a number of mesh packets."""
    packets = []
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clock)
        await ReadOnly()
        if int(dut.io_mesh_valid.value) == 1:
            is_header = int(dut.io_mesh_bits_isHeader.value)
            data = int(dut.io_mesh_bits_data.value)
            packets.append((is_header, data))
            if len(packets) >= count:
                return packets
    return packets


async def wait_for_retire(dut: HierarchyObject, timeout_cycles: int = 100):
    """Wait for retire_late signal. Returns inst or None on timeout."""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clock)
        await ReadOnly()
        if int(dut.io_com_retireLate.value) == 1:
            inst = int(dut.io_com_inst.value)
            xcpt = int(dut.io_com_xcpt.value)
            return (inst, xcpt)
    return None


class RetireMonitor:
    """Monitors retire signal and captures it when it pulses."""

    def __init__(self):
        self.retired = None
        self._task = None

    async def _monitor(self, dut: HierarchyObject):
        """Background task that monitors for retire signal."""
        while self.retired is None:
            await RisingEdge(dut.clock)
            await ReadOnly()
            if int(dut.io_com_retireLate.value) == 1:
                inst = int(dut.io_com_inst.value)
                xcpt = int(dut.io_com_xcpt.value)
                self.retired = (inst, xcpt)
                return

    def start(self, dut: HierarchyObject):
        """Start monitoring retire signal."""
        self._task = cocotb.start_soon(self._monitor(dut))

    async def wait(self, timeout_cycles: int = 100):
        """Wait for retire signal with timeout."""
        for _ in range(timeout_cycles):
            if self.retired is not None:
                return self.retired
            await ClockCycles(cocotb.top.clock, 1)
        return self.retired


async def basic_vle_test(dut: HierarchyObject) -> None:
    """Test a basic vector load instruction flow.

    1. Send vle32.v v0, (a0) with a0 = 0x1000
    2. Wait for TLB request
    3. Respond with successful translation
    4. Wait for mesh packet output
    5. Verify retire
    """
    logger.info("Starting basic_vle_test")

    # Create vle32.v v0, (x10)
    inst = encode_vle(vd=0, rs1=10, width=32, vm=1)
    rs1_data = 0x1000  # Base address
    vl = 16
    vstart = 0
    vsew = 2  # SEW=32 (log2(32/8) = 2)

    logger.info(f"Sending vle32.v v0, (0x{rs1_data:x}), vl={vl}")

    # Start monitoring retire signal (it's a one-cycle pulse we might miss otherwise)
    retire_monitor = RetireMonitor()
    retire_monitor.start(dut)

    # Send instruction (this will handshake)
    cocotb.start_soon(send_instruction(dut, inst, rs1_data, vl, vstart, vsew))

    # Wait a cycle for instruction to be accepted
    await ClockCycles(dut.clock, 2)

    # Wait for TLB request
    tlb_req = await wait_for_tlb_request(dut, timeout_cycles=50)
    assert tlb_req is not None, "TLB request not received"
    vaddr, cmd = tlb_req
    logger.info(f"TLB request: vaddr=0x{vaddr:x}, cmd={cmd}")
    assert vaddr == rs1_data, f"Expected vaddr 0x{rs1_data:x}, got 0x{vaddr:x}"
    assert cmd == 0, f"Expected read command (0), got {cmd}"

    # Exit ReadOnly phase before setting TLB response
    await RisingEdge(dut.clock)

    # Respond with successful translation (identity map for simplicity)
    # The TLB response is registered in IssueUnit, so hold it for several cycles
    await respond_tlb(dut, paddr=rs1_data)
    for _ in range(5):
        await RisingEdge(dut.clock)
        await respond_tlb(dut, paddr=rs1_data)

    # Wait for mesh output (header + instruction)
    logger.info("Waiting for mesh packets...")
    packets = await collect_mesh_packets(dut, count=2, timeout_cycles=100)

    assert len(packets) >= 1, f"Expected at least 1 mesh packet, got {len(packets)}"
    logger.info(f"Received {len(packets)} mesh packets")

    for i, (is_header, data) in enumerate(packets):
        logger.info(f"  Packet {i}: is_header={is_header}, data=0x{data:016x}")

    # First packet should be header
    assert packets[0][0] == 1, "First packet should be header"

    # Wait for retire (should already be captured by monitor)
    retire = await retire_monitor.wait(timeout_cycles=50)
    assert retire is not None, "Retire signal not received"
    ret_inst, xcpt = retire
    logger.info(f"Retired: inst=0x{ret_inst:08x}, xcpt={xcpt}")
    assert xcpt == 0, "Unexpected exception"

    logger.info("basic_vle_test PASSED")


async def basic_vse_test(dut: HierarchyObject) -> None:
    """Test a basic vector store instruction flow."""
    logger.info("Starting basic_vse_test")

    # Create vse32.v v0, (x10)
    inst = encode_vse(vs3=0, rs1=10, width=32, vm=1)
    rs1_data = 0x2000
    vl = 8
    vstart = 0
    vsew = 2

    logger.info(f"Sending vse32.v v0, (0x{rs1_data:x}), vl={vl}")

    # Start monitoring retire signal
    retire_monitor = RetireMonitor()
    retire_monitor.start(dut)

    cocotb.start_soon(send_instruction(dut, inst, rs1_data, vl, vstart, vsew))

    await ClockCycles(dut.clock, 2)

    # Wait for TLB request
    tlb_req = await wait_for_tlb_request(dut, timeout_cycles=50)
    assert tlb_req is not None, "TLB request not received"
    vaddr, cmd = tlb_req
    logger.info(f"TLB request: vaddr=0x{vaddr:x}, cmd={cmd}")
    assert cmd == 1, f"Expected write command (1), got {cmd}"

    # Exit ReadOnly phase before setting TLB response
    await RisingEdge(dut.clock)

    # Respond with successful translation
    # The TLB response is registered in IssueUnit, so hold it for several cycles
    await respond_tlb(dut, paddr=rs1_data)
    for _ in range(5):
        await RisingEdge(dut.clock)
        await respond_tlb(dut, paddr=rs1_data)

    # Wait for mesh packets
    packets = await collect_mesh_packets(dut, count=2, timeout_cycles=100)
    assert len(packets) >= 1, f"Expected mesh packets, got {len(packets)}"
    logger.info(f"Received {len(packets)} mesh packets")

    # Wait for retire (should already be captured by monitor)
    retire = await retire_monitor.wait(timeout_cycles=50)
    assert retire is not None, "Retire signal not received"
    ret_inst, xcpt = retire
    assert xcpt == 0, "Unexpected exception"

    logger.info("basic_vse_test PASSED")


@cocotb.test()
async def lamlet_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")

    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    # Initialize and reset
    initialize_inputs(dut)
    await reset(dut)

    # Run tests
    await basic_vle_test(dut)

    # Reset between tests (wait for clock edge to exit ReadOnly phase)
    await RisingEdge(dut.clock)
    initialize_inputs(dut)
    await reset(dut)

    await basic_vse_test(dut)

    logger.info("All lamlet tests PASSED")


def test_lamlet(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]

    toplevel = "Lamlet"
    module = "zamlet.lamlet_test.test_lamlet"

    test_params = {
        "seed": seed,
    }

    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")

    if len(sys.argv) >= 2:
        verilog_file = os.path.abspath(sys.argv[1])
        test_lamlet(verilog_file)
    else:
        print("Usage: python test_lamlet.py <verilog_file>")
        sys.exit(1)
