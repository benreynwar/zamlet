"""Basic Shuttle core test using cocotb and cocotbext-axi."""

import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb_bus.bus import Bus
from cocotbext.axi import AxiRam
from cocotbext.axi.axi_channels import (
    AxiAWBus, AxiWBus, AxiBBus, AxiARBus, AxiRBus,
    AxiWriteBus, AxiReadBus, AxiBus
)


# Memory addresses from the Shuttle memory map
DRAM_BASE = 0x80000000
DRAM_SIZE = 0x10000000  # 256MB
RESET_VECTOR = DRAM_BASE

# Test markers
TEST_DATA_ADDR = 0x80001000
# MMIO layout at 0x60000000:
#   +0x00: expected value (what we wrote)
#   +0x08: actual value (what we read back)
#   +0x10: status (1 = success, -1 = failure)
MMIO_BASE = 0x60000000
MMIO_EXPECTED = MMIO_BASE + 0x00
MMIO_ACTUAL = MMIO_BASE + 0x08
MMIO_STATUS = MMIO_BASE + 0x10


def chisel_axi_bus(dut, prefix):
    """Create an AxiBus with Chisel signal naming conventions.

    Chisel uses: prefix_aw_bits_addr, prefix_aw_valid, prefix_aw_ready
    Standard AXI uses: prefix_awaddr, prefix_awvalid, prefix_awready
    """
    # AW channel signal mapping (attribute_name -> chisel_signal_suffix)
    aw_signals = {
        "awid": "aw_bits_id",
        "awaddr": "aw_bits_addr",
        "awlen": "aw_bits_len",
        "awsize": "aw_bits_size",
        "awburst": "aw_bits_burst",
        "awvalid": "aw_valid",
        "awready": "aw_ready",
    }
    aw_optional = {
        "awlock": "aw_bits_lock",
        "awcache": "aw_bits_cache",
        "awprot": "aw_bits_prot",
        "awqos": "aw_bits_qos",
    }

    # W channel
    w_signals = {
        "wdata": "w_bits_data",
        "wlast": "w_bits_last",
        "wvalid": "w_valid",
        "wready": "w_ready",
    }
    w_optional = {
        "wstrb": "w_bits_strb",
    }

    # B channel
    b_signals = {
        "bid": "b_bits_id",
        "bvalid": "b_valid",
        "bready": "b_ready",
    }
    b_optional = {
        "bresp": "b_bits_resp",
    }

    # AR channel
    ar_signals = {
        "arid": "ar_bits_id",
        "araddr": "ar_bits_addr",
        "arlen": "ar_bits_len",
        "arsize": "ar_bits_size",
        "arburst": "ar_bits_burst",
        "arvalid": "ar_valid",
        "arready": "ar_ready",
    }
    ar_optional = {
        "arlock": "ar_bits_lock",
        "arcache": "ar_bits_cache",
        "arprot": "ar_bits_prot",
        "arqos": "ar_bits_qos",
    }

    # R channel
    r_signals = {
        "rid": "r_bits_id",
        "rdata": "r_bits_data",
        "rlast": "r_bits_last",
        "rvalid": "r_valid",
        "rready": "r_ready",
    }
    r_optional = {
        "rresp": "r_bits_resp",
    }

    # Create channel buses with custom signal mappings
    aw = Bus(dut, prefix, aw_signals, optional_signals=aw_optional)
    w = Bus(dut, prefix, w_signals, optional_signals=w_optional)
    b = Bus(dut, prefix, b_signals, optional_signals=b_optional)
    ar = Bus(dut, prefix, ar_signals, optional_signals=ar_optional)
    r = Bus(dut, prefix, r_signals, optional_signals=r_optional)

    # cocotbext-axi expects _optional_signals attribute on bus objects
    aw._optional_signals = list(aw_optional.keys())
    w._optional_signals = list(w_optional.keys())
    b._optional_signals = list(b_optional.keys())
    ar._optional_signals = list(ar_optional.keys())
    r._optional_signals = list(r_optional.keys())

    # Wrap in the cocotbext-axi bus hierarchy
    write_bus = AxiWriteBus(aw=aw, w=w, b=b)
    read_bus = AxiReadBus(ar=ar, r=r)
    return AxiBus(write=write_bus, read=read_bus)


def load_binary(ram, binary_path, address):
    """Load a binary file into the AXI RAM at the specified address."""
    with open(binary_path, "rb") as f:
        data = f.read()
    # Write directly to the sparse memory at the absolute address
    ram.mem[address:address+len(data)] = data
    cocotb.log.info(f"Loaded {len(data)} bytes from {binary_path} to 0x{address:08x}")


@cocotb.test()
async def test_simple_program(dut):
    """Test that Shuttle can execute a simple program."""

    # Start clock (100 MHz)
    clock = Clock(dut.clock, 10, unit="ns")
    cocotb.start_soon(clock.start())

    # Create AXI RAM for memory interface with Chisel signal naming
    # Size must cover full address range (sparse dict, only allocates 4KB blocks on write)
    mem_bus = chisel_axi_bus(dut, "mem_axi4")
    mem_ram = AxiRam(mem_bus, dut.clock, dut.reset, size=DRAM_BASE + DRAM_SIZE)

    # Create AXI RAM for MMIO interface - used for done marker (uncached)
    mmio_bus = chisel_axi_bus(dut, "mmio_axi4")
    mmio_ram = AxiRam(mmio_bus, dut.clock, dut.reset, size=0x80000000)

    # Load test binary
    binary_path = os.path.join(os.path.dirname(__file__), "test_simple.bin")
    if not os.path.exists(binary_path):
        # Try runfiles path
        binary_path = "python/zamlet/shuttle_test/test_simple.bin"
    load_binary(mem_ram, binary_path, DRAM_BASE)

    # Set reset vector
    dut.reset_vector.value = RESET_VECTOR

    # Apply reset
    dut.reset.value = 1
    await ClockCycles(dut.clock, 10)
    dut.reset.value = 0

    cocotb.log.info("Reset released, starting execution")

    def read_mmio_u64(addr):
        """Read a 64-bit value from MMIO RAM."""
        return int.from_bytes(bytes(mmio_ram.mem[addr:addr+8]), byteorder='little')

    # Wait for done marker (with timeout)
    timeout_cycles = 10000
    for cycle in range(timeout_cycles):
        await RisingEdge(dut.clock)

        # Check status every 100 cycles
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
