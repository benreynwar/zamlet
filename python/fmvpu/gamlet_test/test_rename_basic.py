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
async def rename_basic_test(dut: HierarchyObject) -> None:
    """Test basic Rename functionality."""
    print("Starting basic Rename test...")
    
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
    
    # Test 1: Basic input/output flow with no stalls
    print("Testing basic rename operation...")
    
    # Set up a simple instruction - just pass through with valid=0 initially
    dut.io_input_valid.value = 0
    dut.io_input_bits_control_mode.value = 0
    dut.io_input_bits_predicate_mode.value = 0
    dut.io_input_bits_alu_mode.value = 0
    dut.io_input_bits_aluLite_mode.value = 0
    dut.io_input_bits_loadStore_mode.value = 0
    dut.io_input_bits_packet_mode.value = 0
    
    # Clear all notices
    for i in range(2):  # nFamlets = 2 from default config
        for j in range(4):  # 4 bWrites per NoticeBus
            getattr(dut, f'io_notices_{i}_bWrites_{j}_valid').value = 0
        getattr(dut, f'io_notices_{i}_aWrites_0_valid').value = 0
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    # Output should be invalid when input is invalid
    assert dut.io_output_valid.value == 0, "Output should be invalid when input is invalid"
    
    await triggers.RisingEdge(dut.clock)
    # Test 2: Enable input with a simple instruction
    print("Testing with valid input...")
    dut.io_input_valid.value = 1
    
    # Set up control instruction (simple increment mode)
    dut.io_input_bits_control_mode.value = 3  # Incr mode
    dut.io_input_bits_control_dst.value = 1  # destination register
    
    # Register for two stages (input and output buffers)
    await triggers.RisingEdge(dut.clock)
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    # Output should be valid (assuming no stalls for this simple case)
    print(f"Output valid: {dut.io_output_valid.value}")
    print(f"Output control mode: {dut.io_output_bits_control_mode.value}")
    
    # The rename module should pass through the instruction with renamed registers
    assert dut.io_output_valid.value == 1, "Output should be valid when input is valid"
    assert dut.io_output_bits_control_mode.value == 3, "Control mode should pass through"
    assert dut.io_output_bits_control_dst.value == 16, f"Expected dst was 16, seen is {int(dut.io_output_bits_control_dst.value)}"
    
    print("Rename basic test completed successfully!")


def test_rename_basic(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = 'Rename'
    module = 'fmvpu.gamlet_test.test_rename_basic'
    
    test_params = {
        'seed': seed,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_rename_basic(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Find the gamlet config file
        config_file = os.path.join(os.path.dirname(this_dir), '..', '..', 'configs', 'gamlet_default.json')
        config_file = os.path.abspath(config_file)
        
        # Generate Rename with gamlet parameters
        filenames = generate_rtl.generate('Rename', working_dir, [config_file])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, 'rename_verilog.sv')
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_rename_basic(concat_filename, seed)


if __name__ == '__main__':
    test_utils.configure_logging_pre_sim('INFO')
    
    if len(sys.argv) >= 2:
        # Called from Bazel with verilog_file
        verilog_file = sys.argv[1]
        test_rename_basic(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_rename_basic()
