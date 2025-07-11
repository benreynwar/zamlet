# WARNING: This file was created by Claude Code with negligible human oversight.
# It is not a test that should be trusted.

import os
import sys
import tempfile
from typing import Optional

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from fmvpu import generate_rtl
from fmvpu import test_utils

this_dir = os.path.abspath(os.path.dirname(__file__))


@cocotb.test()
async def alu_basic_operations_test(dut: HierarchyObject) -> None:
    """Test basic ALU operations: Add, Sub, Mult, MultAcc."""
    print("Starting basic ALU operations test...")
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    
    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    
    # Test Add operation (mode 0)
    print("Testing Add operation...")
    dut.io_instr_valid.value = 1
    dut.io_instr_mode.value = 0  # Add
    dut.io_instr_src1.value = 10
    dut.io_instr_src2.value = 20
    dut.io_instr_accum.value = 0
    dut.io_instr_dstAddr_regAddr.value = 2
    dut.io_instr_dstAddr_writeIdent.value = 1
    dut.io_instr_useLocalAccum.value = 0
    
    await triggers.RisingEdge(dut.clock)
    
    # Check result
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 30, f"Add result should be 30, got {dut.io_result_value.value}"
    assert dut.io_result_address_regAddr.value == 2, "Result address should match"
    
    # Test Sub operation (mode 2)
    print("Testing Sub operation...")
    dut.io_instr_mode.value = 2  # Sub
    dut.io_instr_src1.value = 50
    dut.io_instr_src2.value = 30
    dut.io_instr_dstAddr_regAddr.value = 3
    
    await triggers.RisingEdge(dut.clock)
    
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 20, f"Sub result should be 20, got {dut.io_result_value.value}"
    
    # Test Mult operation (mode 4)
    print("Testing Mult operation...")
    dut.io_instr_mode.value = 4  # Mult
    dut.io_instr_src1.value = 6
    dut.io_instr_src2.value = 7
    dut.io_instr_dstAddr_regAddr.value = 4
    
    await triggers.RisingEdge(dut.clock)
    
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 42, f"Mult result should be 42, got {dut.io_result_value.value}"
    
    print("Basic ALU operations test completed successfully!")


@cocotb.test()
async def alu_multacc_test(dut: HierarchyObject) -> None:
    """Test MultAcc operation with local accumulator."""
    print("Starting MultAcc with local accumulator test...")
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    
    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    
    # First MultAcc operation - uses external accumulator
    print("Testing first MultAcc (external accumulator)...")
    dut.io_instr_valid.value = 1
    dut.io_instr_mode.value = 5  # MultAcc
    dut.io_instr_src1.value = 3
    dut.io_instr_src2.value = 4
    dut.io_instr_accum.value = 10  # External accumulator value
    dut.io_instr_dstAddr_regAddr.value = 1  # Write to accumulator register
    dut.io_instr_dstAddr_writeIdent.value = 1
    dut.io_instr_useLocalAccum.value = 0  # Use external accumulator
    
    await triggers.RisingEdge(dut.clock)
    
    # Check result: 10 + (3 * 4) = 22
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 22, f"MultAcc result should be 22, got {dut.io_result_value.value}"
    
    # Second MultAcc operation - should use local accumulator
    print("Testing second MultAcc (local accumulator)...")
    dut.io_instr_src1.value = 2
    dut.io_instr_src2.value = 5
    dut.io_instr_accum.value = 999  # This should be ignored
    dut.io_instr_dstAddr_writeIdent.value = 2
    dut.io_instr_useLocalAccum.value = 1  # Use local accumulator
    
    await triggers.RisingEdge(dut.clock)
    
    # Check result: 22 + (2 * 5) = 32 (using local accumulator value)
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 32, f"MultAcc result should be 32, got {dut.io_result_value.value}"
    
    # Third MultAcc operation - continue using local accumulator
    print("Testing third MultAcc (local accumulator)...")
    dut.io_instr_src1.value = 1
    dut.io_instr_src2.value = 8
    dut.io_instr_accum.value = 777  # This should be ignored
    dut.io_instr_dstAddr_writeIdent.value = 3
    dut.io_instr_useLocalAccum.value = 1  # Use local accumulator
    
    await triggers.RisingEdge(dut.clock)
    
    # Check result: 32 + (1 * 8) = 40 (using local accumulator value)
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 40, f"MultAcc result should be 40, got {dut.io_result_value.value}"
    
    print("MultAcc with local accumulator test completed successfully!")


def test_alu_basic(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = 'ALU'
    module = 'fmvpu.new_lane.test_alu_basic'
    
    test_params = {
        'seed': seed,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_alu_basic(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Find the lane config file
        config_file = os.path.join(os.path.dirname(this_dir), '..', '..', 'configs', 'lane_default.json')
        config_file = os.path.abspath(config_file)
        
        # Generate ALU with lane parameters (latency = 1)
        filenames = generate_rtl.generate('ALU', working_dir, [config_file, '1'])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, 'alu_verilog.sv')
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_alu_basic(concat_filename, seed)


if __name__ == '__main__':
    test_utils.configure_logging_pre_sim('INFO')
    
    if len(sys.argv) >= 2:
        # Called from Bazel with verilog_file
        verilog_file = sys.argv[1]
        test_alu_basic(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_alu_basic()