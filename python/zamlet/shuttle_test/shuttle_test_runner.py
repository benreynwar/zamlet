"""Generic Shuttle test runner using cocotb.

This module provides a reusable test that:
1. Loads a RISC-V binary (path from SHUTTLE_TEST_BINARY env var)
2. Runs it on the Shuttle core
3. Checks results via MMIO protocol:
   - 0x60000000: expected value
   - 0x60000008: actual value
   - 0x60000010: status (1 = pass, -1 = fail)
"""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb_bus.bus import Bus
from cocotbext.axi import AxiRam
from cocotbext.axi.axi_channels import AxiWriteBus, AxiReadBus, AxiBus


# Memory map
DRAM_BASE = 0x80000000
DRAM_SIZE = 0x10000000  # 256MB
RESET_VECTOR = DRAM_BASE

# MMIO layout
MMIO_BASE = 0x60000000
MMIO_EXPECTED = MMIO_BASE + 0x00
MMIO_ACTUAL = MMIO_BASE + 0x08
MMIO_STATUS = MMIO_BASE + 0x10


def chisel_axi_bus(dut, prefix):
    """Create an AxiBus with Chisel signal naming conventions."""
    aw_signals = {
        "awid": "aw_bits_id", "awaddr": "aw_bits_addr", "awlen": "aw_bits_len",
        "awsize": "aw_bits_size", "awburst": "aw_bits_burst",
        "awvalid": "aw_valid", "awready": "aw_ready",
    }
    aw_optional = {
        "awlock": "aw_bits_lock", "awcache": "aw_bits_cache",
        "awprot": "aw_bits_prot", "awqos": "aw_bits_qos",
    }
    w_signals = {
        "wdata": "w_bits_data", "wlast": "w_bits_last",
        "wvalid": "w_valid", "wready": "w_ready",
    }
    w_optional = {"wstrb": "w_bits_strb"}
    b_signals = {"bid": "b_bits_id", "bvalid": "b_valid", "bready": "b_ready"}
    b_optional = {"bresp": "b_bits_resp"}
    ar_signals = {
        "arid": "ar_bits_id", "araddr": "ar_bits_addr", "arlen": "ar_bits_len",
        "arsize": "ar_bits_size", "arburst": "ar_bits_burst",
        "arvalid": "ar_valid", "arready": "ar_ready",
    }
    ar_optional = {
        "arlock": "ar_bits_lock", "arcache": "ar_bits_cache",
        "arprot": "ar_bits_prot", "arqos": "ar_bits_qos",
    }
    r_signals = {
        "rid": "r_bits_id", "rdata": "r_bits_data", "rlast": "r_bits_last",
        "rvalid": "r_valid", "rready": "r_ready",
    }
    r_optional = {"rresp": "r_bits_resp"}

    aw = Bus(dut, prefix, aw_signals, optional_signals=aw_optional)
    w = Bus(dut, prefix, w_signals, optional_signals=w_optional)
    b = Bus(dut, prefix, b_signals, optional_signals=b_optional)
    ar = Bus(dut, prefix, ar_signals, optional_signals=ar_optional)
    r = Bus(dut, prefix, r_signals, optional_signals=r_optional)

    aw._optional_signals = list(aw_optional.keys())
    w._optional_signals = list(w_optional.keys())
    b._optional_signals = list(b_optional.keys())
    ar._optional_signals = list(ar_optional.keys())
    r._optional_signals = list(r_optional.keys())

    write_bus = AxiWriteBus(aw=aw, w=w, b=b)
    read_bus = AxiReadBus(ar=ar, r=r)
    return AxiBus(write=write_bus, read=read_bus)


def load_binary(ram, binary_path, address):
    """Load a binary file into the AXI RAM at the specified address."""
    with open(binary_path, "rb") as f:
        data = f.read()
    ram.mem[address:address+len(data)] = data
    cocotb.log.info(f"Loaded {len(data)} bytes from {binary_path} to 0x{address:08x}")


@cocotb.test()
async def run_test(dut):
    """Run a RISC-V binary and check results via MMIO."""

    binary_path = os.environ.get("ZAMLET_TEST_BINARY")
    if not binary_path:
        raise RuntimeError("ZAMLET_TEST_BINARY environment variable not set")
    cocotb.log.info(f"Using binary: {binary_path}")

    # Start clock (100 MHz)
    clock = Clock(dut.clock, 10, unit="ns")
    cocotb.start_soon(clock.start())

    # Create AXI RAMs
    mem_bus = chisel_axi_bus(dut, "mem_axi4")
    mem_ram = AxiRam(mem_bus, dut.clock, dut.reset, size=DRAM_BASE + DRAM_SIZE)

    mmio_bus = chisel_axi_bus(dut, "mmio_axi4")
    mmio_ram = AxiRam(mmio_bus, dut.clock, dut.reset, size=0x80000000)

    # Load binary
    load_binary(mem_ram, binary_path, DRAM_BASE)

    # Set reset vector and apply reset
    dut.reset_vector.value = RESET_VECTOR
    dut.reset.value = 1
    await ClockCycles(dut.clock, 10)
    dut.reset.value = 0

    cocotb.log.info("Reset released, starting execution")

    def read_mmio_u64(addr):
        return int.from_bytes(bytes(mmio_ram.mem[addr:addr+8]), byteorder='little')

    # Wait for completion
    timeout_cycles = 10000
    for cycle in range(timeout_cycles):
        await RisingEdge(dut.clock)

        if cycle % 100 == 0:
            status = read_mmio_u64(MMIO_STATUS)

            if status == 1:
                expected = read_mmio_u64(MMIO_EXPECTED)
                actual = read_mmio_u64(MMIO_ACTUAL)
                cocotb.log.info(f"Test PASSED at cycle {cycle}")
                cocotb.log.info(f"  Expected: 0x{expected:016x}")
                cocotb.log.info(f"  Actual:   0x{actual:016x}")
                return

            elif status == 0xFFFFFFFFFFFFFFFF:
                expected = read_mmio_u64(MMIO_EXPECTED)
                actual = read_mmio_u64(MMIO_ACTUAL)
                cocotb.log.error(f"Test FAILED at cycle {cycle}")
                cocotb.log.error(f"  Expected: 0x{expected:016x}")
                cocotb.log.error(f"  Actual:   0x{actual:016x}")
                raise AssertionError(
                    f"Comparison failed: expected 0x{expected:016x}, got 0x{actual:016x}"
                )

    raise AssertionError(f"Test timed out after {timeout_cycles} cycles")
