import os
import sys
import tempfile
from typing import Optional
import logging
from random import Random
import json

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, Timer, ReadOnly

from zamlet import generate_rtl
from zamlet import test_utils


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def basic_fifo_test(dut: HierarchyObject, max_val: int) -> None:
    """Test basic FIFO operations without dropping"""
    val1 = max_val
    val2 = max_val // 3

    # Initialize signals
    dut.io_i_valid.value = 0
    dut.io_i_bits.value = 0
    dut.io_drop.value = 0
    dut.io_o_ready.value = 0

    # Reset
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)

    # Check initial state
    assert dut.io_i_ready.value == 1, "FIFO should be ready when empty"
    assert dut.io_o_valid.value == 0, "FIFO should not have valid output when empty"

    # Write first item
    dut.io_i_valid.value = 1
    dut.io_i_bits.value = val1
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0
    await ReadOnly()

    # Check output valid and count
    assert dut.io_o_valid.value == 1, "Output should be valid after write"
    assert dut.io_o_bits.value == val1, "Output should match input"
    assert dut.io_count.value == 0, "Count should be 0 for newly written item"

    await RisingEdge(dut.clock)
    # Write second item (count should increment for first item)
    dut.io_i_valid.value = 1
    dut.io_i_bits.value = val2
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0

    # First item should still be at output but count incremented
    await ReadOnly()
    assert dut.io_o_bits.value == val1, "First item should still be at output"
    assert dut.io_count.value == 1, "Count should increment when second item written"

    # Read first item
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 1
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 0

    # Second item should now be at output
    await ReadOnly()
    assert dut.io_o_bits.value == val2, "Second item should be at output"
    assert dut.io_count.value == 0, "Count should be 0 for second item"


async def dropping_test(dut: HierarchyObject, max_val: int) -> None:
    """Test dropping functionality"""
    dropped_val = max_val
    normal_val = max_val // 2

    # Reset
    await RisingEdge(dut.clock)
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)

    # Write and drop an item
    dut.io_i_valid.value = 1
    dut.io_i_bits.value = dropped_val
    dut.io_drop.value = 1
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0
    dut.io_drop.value = 0

    # FIFO should still be empty
    await ReadOnly()
    assert dut.io_o_valid.value == 0, "FIFO should be empty after drop"

    # Write a normal item
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 1
    dut.io_i_bits.value = normal_val
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0

    # Should be available at output
    await ReadOnly()
    assert dut.io_o_valid.value == 1, "Output should be valid"
    assert dut.io_o_bits.value == normal_val, "Output should match normal write"
    assert dut.io_count.value == 0, "Count should be 0 for newly written item"

    # Test dropping an item after we have one in the FIFO
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 1
    dut.io_i_bits.value = dropped_val
    dut.io_drop.value = 1
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0
    dut.io_drop.value = 0

    # The existing item should still be at output but count should increment
    await ReadOnly()
    assert dut.io_o_valid.value == 1, "Output should still be valid"
    assert dut.io_o_bits.value == normal_val, "Same item should still be at output"
    assert dut.io_count.value == 1, "Count should increment due to dropped item"


async def count_tracking_test(dut: HierarchyObject, max_val: int) -> None:
    """Test that counts properly track consumed inputs"""
    val1 = max_val // 4
    val2 = max_val // 2
    val3 = max_val

    # Reset
    await RisingEdge(dut.clock)
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)

    # Write item 1
    dut.io_i_valid.value = 1
    dut.io_i_bits.value = val1
    await RisingEdge(dut.clock)

    # Write item 2
    dut.io_i_bits.value = val2
    await RisingEdge(dut.clock)

    # Write item 3
    dut.io_i_bits.value = val3
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0

    # Item 1 should be at output with count = 2 (items 2 and 3 consumed after it)
    await ReadOnly()
    assert dut.io_o_bits.value == val1, "Item 1 should be at output"
    assert dut.io_count.value == 2, "Count should be 2 for item 1"

    # Read item 1
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 1
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 0

    # Item 2 should be at output with count = 1 (item 3 consumed after it)
    await ReadOnly()
    assert dut.io_o_bits.value == val2, "Item 2 should be at output"
    assert dut.io_count.value == 1, "Count should be 1 for item 2"

    # Read item 2
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 1
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 0

    # Item 3 should be at output with count = 0
    await ReadOnly()
    assert dut.io_o_bits.value == val3, "Item 3 should be at output"
    assert dut.io_count.value == 0, "Count should be 0 for item 3"


async def simultaneous_read_write_test(dut: HierarchyObject, max_val: int) -> None:
    """Test simultaneous read and write operations"""
    val1 = max_val // 3
    val2 = max_val // 2

    # Reset and fill FIFO with one item
    await RisingEdge(dut.clock)
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)

    # Write first item
    dut.io_i_valid.value = 1
    dut.io_i_bits.value = val1
    await RisingEdge(dut.clock)

    # Simultaneous read and write
    dut.io_i_bits.value = val2
    dut.io_o_ready.value = 1
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0
    dut.io_o_ready.value = 0

    # Second item should be at output
    await ReadOnly()
    assert dut.io_o_valid.value == 1, "FIFO should not be empty"
    assert dut.io_o_bits.value == val2, "Second item should be at output"
    assert dut.io_count.value == 0, "Count should be 0 for second item"


async def backpressure_test(dut: HierarchyObject, max_val: int, depth: int) -> None:
    """Test backpressure behavior when FIFO is full"""
    # Reset
    await RisingEdge(dut.clock)
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)

    # Fill FIFO to capacity
    dut.io_i_valid.value = 1
    for i in range(depth):
        dut.io_i_bits.value = i % (max_val + 1)
        await RisingEdge(dut.clock)

    # FIFO should now be full and not ready
    await ReadOnly()
    assert dut.io_i_ready.value == 0, "FIFO should not be ready when full"

    # Try to write another item (should be rejected)
    await RisingEdge(dut.clock)
    dut.io_i_bits.value = max_val
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0

    # First item should still be at output
    await ReadOnly()
    assert dut.io_o_bits.value == 0, "First item should still be at output"

    # Read one item to make space
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 1
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 0

    # FIFO should be ready again
    await ReadOnly()
    assert dut.io_i_ready.value == 1, "FIFO should be ready after read"


@cocotb.test()
async def counting_fifo_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")

    # Load config to get width and depth
    test_params = test_utils.get_test_params()
    with open(test_params['params_file']) as f:
        config = json.load(f)

    width = config["width"]
    depth = config["depth"]
    max_val = (1 << width) - 1
    logger.info(f"Config: width={width}, depth={depth}, max_val={max_val}")

    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    # Run tests
    await basic_fifo_test(dut, max_val)
    await dropping_test(dut, max_val)
    await count_tracking_test(dut, max_val)
    await simultaneous_read_write_test(dut, max_val)
    await backpressure_test(dut, max_val, depth)


def test_counting_fifo(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "DroppingFifo"
    module = "zamlet.utils_test.test_dropping_fifo"
    
    test_params = {
        "seed": seed,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_counting_fifo(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Generate DroppingFifo with 8-bit data, depth 4, 4-bit counter
        filenames = generate_rtl.generate("DroppingFifo", working_dir, ["8", "4", "4"])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, "counting_fifo_verilog.sv")
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_counting_fifo(concat_filename, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        verilog_file = os.path.abspath(sys.argv[1])
        test_counting_fifo(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_counting_fifo()
