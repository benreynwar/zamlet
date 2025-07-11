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
async def alurs_basic_test(dut: HierarchyObject) -> None:
    """Test basic ALU Reservation Station functionality."""
    print("Starting basic AluRS test...")
    
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
    
    # Initially, should be ready for input and no output
    assert dut.io_input_ready.value == 1, "Should be ready for input initially"
    assert dut.io_output_valid.value == 0, "Should have no output initially"
    
    # Test 1: Send a fully resolved instruction
    print("Testing fully resolved instruction...")
    dut.io_input_valid.value = 1
    dut.io_input_bits_mode.value = 0  # Add
    dut.io_input_bits_src1_resolved.value = 1
    dut.io_input_bits_src1_value.value = 10
    dut.io_input_bits_src2_resolved.value = 1
    dut.io_input_bits_src2_value.value = 20
    dut.io_input_bits_accum_resolved.value = 1
    dut.io_input_bits_accum_value.value = 0
    dut.io_input_bits_mask_resolved.value = 1
    dut.io_input_bits_mask_value.value = 1
    dut.io_input_bits_dstAddr_regAddr.value = 2
    dut.io_input_bits_dstAddr_writeIdent.value = 1
    dut.io_input_bits_useLocalAccum.value = 0
    
    # Clear write inputs
    for i in range(3):  # Assuming 3 write ports
        getattr(dut, f'io_writeInputs_{i}_valid').value = 0
    
    await triggers.RisingEdge(dut.clock)
    
    # After one cycle, instruction should be dispatched
    assert dut.io_output_valid.value == 1, "Should have valid output"
    assert dut.io_output_bits_mode.value == 0, "Mode should be Add"
    assert dut.io_output_bits_src1.value == 10, "src1 should be 10"
    assert dut.io_output_bits_src2.value == 20, "src2 should be 20"
    assert dut.io_output_bits_mask.value == 1, "mask should be 1"
    
    # Clear input
    dut.io_input_valid.value = 0
    
    await triggers.RisingEdge(dut.clock)
    
    # Output should go away
    assert dut.io_output_valid.value == 0, "Output should be invalid after dispatch"
    
    print("Basic AluRS test completed successfully!")


@cocotb.test()
async def alurs_dependency_test(dut: HierarchyObject) -> None:
    """Test dependency resolution in ALU Reservation Station."""
    print("Starting AluRS dependency resolution test...")
    
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
    
    # Test: Send instruction with unresolved dependency
    print("Testing unresolved dependency...")
    dut.io_input_valid.value = 1
    dut.io_input_bits_mode.value = 0  # Add
    dut.io_input_bits_src1_resolved.value = 0  # Unresolved
    dut.io_input_bits_src1_value.value = (1 << 3) | 2  # writeIdent=1, regAddr=2
    dut.io_input_bits_src2_resolved.value = 1
    dut.io_input_bits_src2_value.value = 20
    dut.io_input_bits_accum_resolved.value = 1
    dut.io_input_bits_accum_value.value = 0
    dut.io_input_bits_mask_resolved.value = 1
    dut.io_input_bits_mask_value.value = 1
    dut.io_input_bits_dstAddr_regAddr.value = 3
    dut.io_input_bits_dstAddr_writeIdent.value = 2
    dut.io_input_bits_useLocalAccum.value = 0
    
    # Clear write inputs
    for i in range(3):
        getattr(dut, f'io_writeInputs_{i}_valid').value = 0
    
    await triggers.RisingEdge(dut.clock)
    
    # Should accept instruction but not dispatch it yet
    assert dut.io_output_valid.value == 0, "Should not dispatch unresolved instruction"
    
    # Clear input
    dut.io_input_valid.value = 0
    
    # Now provide the write result to resolve dependency
    print("Resolving dependency...")
    dut.io_writeInputs_0_valid.value = 1
    dut.io_writeInputs_0_value.value = 15  # The resolved value
    dut.io_writeInputs_0_address_regAddr.value = 2
    dut.io_writeInputs_0_address_writeIdent.value = 1
    
    await triggers.RisingEdge(dut.clock)
    
    # Now instruction should be dispatched
    assert dut.io_output_valid.value == 1, "Should dispatch resolved instruction"
    assert dut.io_output_bits_src1.value == 15, "src1 should be resolved to 15"
    assert dut.io_output_bits_src2.value == 20, "src2 should still be 20"
    
    print("AluRS dependency resolution test completed successfully!")


def test_alurs_basic(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = 'AluRS'
    module = 'fmvpu.new_lane.test_alurs_basic'
    
    test_params = {
        'seed': seed,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_alurs_basic(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Find the lane config file
        config_file = os.path.join(os.path.dirname(this_dir), '..', '..', 'configs', 'lane_default.json')
        config_file = os.path.abspath(config_file)
        
        # Generate AluRS with lane parameters
        filenames = generate_rtl.generate('AluRS', working_dir, [config_file])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, 'alurs_verilog.sv')
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_alurs_basic(concat_filename, seed)


if __name__ == '__main__':
    test_utils.configure_logging_pre_sim('INFO')
    
    if len(sys.argv) >= 2:
        # Called from Bazel with verilog_file
        verilog_file = sys.argv[1]
        test_alurs_basic(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_alurs_basic()