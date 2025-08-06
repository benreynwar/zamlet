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

from zamlet import generate_rtl
from zamlet import test_utils

this_dir = os.path.abspath(os.path.dirname(__file__))


@cocotb.test()
async def alu_basic_test(dut: HierarchyObject) -> None:
    """Test basic ALU functionality."""
    print("Starting basic ALU test...")
    
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
    
    # Test 1: Addition operation
    print("Testing addition operation...")
    dut.io_instr_valid.value = 1
    dut.io_instr_bits_mode.value = 1  # Add
    dut.io_instr_bits_src1.value = 10
    dut.io_instr_bits_src2.value = 20
    dut.io_instr_bits_dst_addr.value = 2
    dut.io_instr_bits_dst_ident.value = 1
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    # Check result (latency=1, so result should be available immediately)
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 30, f"Addition result should be 30, got {dut.io_result_value.value}"
    assert dut.io_result_address_addr.value == 2, "Destination address should be 2"
    assert dut.io_result_address_ident.value == 1, "Destination ident should be 1"
    assert dut.io_result_force.value == 0, "Force should be false"
    
    print("Addition test passed!")
    await triggers.RisingEdge(dut.clock)
    
    # Test 2: Subtraction operation
    print("Testing subtraction operation...")
    dut.io_instr_bits_mode.value = 3  # Sub
    dut.io_instr_bits_src1.value = 50
    dut.io_instr_bits_src2.value = 15
    dut.io_instr_bits_dst_addr.value = 3
    dut.io_instr_bits_dst_ident.value = 2
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    # Check result
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 35, f"Subtraction result should be 35, got {dut.io_result_value.value}"
    assert dut.io_result_address_addr.value == 3, "Destination address should be 3"
    assert dut.io_result_address_ident.value == 2, "Destination ident should be 2"
    
    print("Subtraction test passed!")
    await triggers.RisingEdge(dut.clock)
    
    # Test 3: Multiplication operation
    print("Testing multiplication operation...")
    dut.io_instr_bits_mode.value = 5  # Mult
    dut.io_instr_bits_src1.value = 6
    dut.io_instr_bits_src2.value = 7
    dut.io_instr_bits_dst_addr.value = 4
    dut.io_instr_bits_dst_ident.value = 3
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    # Check result
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 42, f"Multiplication result should be 42, got {dut.io_result_value.value}"
    assert dut.io_result_address_addr.value == 4, "Destination address should be 4"
    assert dut.io_result_address_ident.value == 3, "Destination ident should be 3"
    
    print("Multiplication test passed!")
    await triggers.RisingEdge(dut.clock)
    
    # Test 4: Logical AND operation
    print("Testing logical AND operation...")
    dut.io_instr_bits_mode.value = 12  # And
    dut.io_instr_bits_src1.value = 0b11110000
    dut.io_instr_bits_src2.value = 0b10101010
    dut.io_instr_bits_dst_addr.value = 5
    dut.io_instr_bits_dst_ident.value = 1
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    # Check result
    assert dut.io_result_valid.value == 1, "Result should be valid"
    expected_and = 0b11110000 & 0b10101010  # 0b10100000 = 160
    assert dut.io_result_value.value == expected_and, f"AND result should be {expected_and}, got {dut.io_result_value.value}"
    
    print("Logical AND test passed!")
    await triggers.RisingEdge(dut.clock)
    
    # Test 5: No instruction (invalid)
    print("Testing no instruction...")
    dut.io_instr_valid.value = 0
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    # Check that no result is produced
    assert dut.io_result_valid.value == 0, "Result should not be valid when no instruction"
    
    print("No instruction test passed!")
    
    print("All ALU tests completed successfully!")


@cocotb.test()
async def alu_comparison_test(dut: HierarchyObject) -> None:
    """Test ALU comparison operations."""
    print("Starting ALU comparison test...")
    
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
    
    # Test 1: Equality (true case)
    print("Testing equality (true case)...")
    dut.io_instr_valid.value = 1
    dut.io_instr_bits_mode.value = 8  # Eq
    dut.io_instr_bits_src1.value = 42
    dut.io_instr_bits_src2.value = 42
    dut.io_instr_bits_dst_addr.value = 1
    dut.io_instr_bits_dst_ident.value = 1
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 1, f"Equality should be true (1), got {dut.io_result_value.value}"
    
    await triggers.RisingEdge(dut.clock)
    # Test 2: Equality (false case)
    print("Testing equality (false case)...")
    dut.io_instr_bits_src1.value = 42
    dut.io_instr_bits_src2.value = 43
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 0, f"Equality should be false (0), got {dut.io_result_value.value}"
    
    await triggers.RisingEdge(dut.clock)
    # Test 3: Greater than or equal (true case)
    print("Testing greater than or equal (true case)...")
    dut.io_instr_bits_mode.value = 9  # Gte
    dut.io_instr_bits_src1.value = 50
    dut.io_instr_bits_src2.value = 30
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 1, f"GTE should be true (1), got {dut.io_result_value.value}"
    
    await triggers.RisingEdge(dut.clock)
    # Test 4: Greater than or equal (false case)
    print("Testing greater than or equal (false case)...")
    dut.io_instr_bits_src1.value = 20
    dut.io_instr_bits_src2.value = 30
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    assert dut.io_result_valid.value == 1, "Result should be valid"
    assert dut.io_result_value.value == 0, f"GTE should be false (0), got {dut.io_result_value.value}"
    
    print("ALU comparison tests completed successfully!")


def test_alu_basic(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = 'ALU'
    module = 'zamlet.amlet_test.test_alu_basic'
    
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
        
        # Find the amlet config file
        config_file = os.path.join(os.path.dirname(this_dir), '..', '..', 'configs', 'amlet_default.json')
        config_file = os.path.abspath(config_file)
        
        # Generate ALU with amlet parameters
        filenames = generate_rtl.generate('ALU', working_dir, [config_file])
        
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
