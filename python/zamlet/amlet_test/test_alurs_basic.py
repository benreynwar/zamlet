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
async def alurs_basic_test(dut: HierarchyObject) -> None:
    """Test basic ALURS functionality."""
    print("Starting basic ALURS test...")
    
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
    
    
    # Test 1: Send a fully resolved instruction
    print("Testing fully resolved instruction without mask...")
    dut.io_input_valid.value = 1
    dut.io_input_bits_mode.value = 1  # Add
    dut.io_input_bits_src1_resolved.value = 1
    dut.io_input_bits_src1_value.value = 10
    dut.io_input_bits_src2_resolved.value = 1
    dut.io_input_bits_src2_value.value = 20
    dut.io_input_bits_mask_resolved.value = 1
    dut.io_input_bits_mask_value.value = 0
    dut.io_input_bits_dst_addr.value = 2
    dut.io_input_bits_dst_ident.value = 1
    
    # Clear write inputs
    for i in range(4):  # nWriteBacks from amlet config
        getattr(dut, f'io_writeBacks_writes_{i}_valid').value = 0
        getattr(dut, f'io_writeBacks_masks_{i}_valid').value = 0

    await triggers.ReadOnly()
    # Initially, should be ready for input and no output
    assert dut.io_input_ready.value == 1, "Should be ready for input initially"
    assert dut.io_output_valid.value == 0, "Should have no output initially"
    
    await triggers.RisingEdge(dut.clock)
    dut.io_input_valid.value = 0
    await triggers.ReadOnly()
    
    # After one cycle, instruction should be dispatched
    assert dut.io_output_valid.value == 1, "Should have valid output"
    assert dut.io_output_bits_mode.value == 1, "Mode should be Add"
    assert dut.io_output_bits_src1.value == 10, "src1 should be 10"
    assert dut.io_output_bits_src2.value == 20, "src2 should be 20"
    
    # Clear input
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    # Output should go away
    assert dut.io_output_valid.value == 0, "Output should be invalid after dispatch"
    
    print("Basic ALURS test completed successfully!")


@cocotb.test()
async def alurs_dependency_test(dut: HierarchyObject) -> None:
    """Test dependency resolution in ALURS."""
    print("Starting ALURS dependency resolution test...")
    
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
    dut.io_input_bits_mode.value = 1  # Add
    dut.io_input_bits_src1_resolved.value = 0  # Unresolved
    dut.io_input_bits_src1_addr.value = 2
    dut.io_input_bits_src1_ident.value = 1
    dut.io_input_bits_src2_resolved.value = 1
    dut.io_input_bits_src2_value.value = 20
    dut.io_input_bits_mask_resolved.value = 1
    dut.io_input_bits_mask_value.value = 0
    dut.io_input_bits_dst_addr.value = 3
    dut.io_input_bits_dst_ident.value = 2
    
    # Clear write inputs
    for i in range(4):
        getattr(dut, f'io_writeBacks_writes_{i}_valid').value = 0
        getattr(dut, f'io_writeBacks_masks_{i}_valid').value = 0
    
    await triggers.RisingEdge(dut.clock)
    
    
    # Clear input
    dut.io_input_valid.value = 0
    
    # Now provide the write result to resolve dependency
    print("Resolving dependency...")
    dut.io_writeBacks_writes_0_valid.value = 1
    dut.io_writeBacks_writes_0_value.value = 15  # The resolved value
    dut.io_writeBacks_writes_0_address_addr.value = 2
    dut.io_writeBacks_writes_0_address_ident.value = 1

    # Should accept instruction but not dispatch it yet
    await triggers.ReadOnly()
    assert dut.io_output_valid.value == 0, "Should not dispatch unresolved instruction"
    
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    
    # Now instruction should be dispatched
    assert dut.io_output_valid.value == 1, "Should dispatch resolved instruction"
    assert dut.io_output_bits_src1.value == 15, "src1 should be resolved to 15"
    assert dut.io_output_bits_src2.value == 20, "src2 should still be 20"
    
    print("ALURS dependency resolution test completed successfully!")


def test_alurs_basic(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = 'ALURS'
    module = 'zamlet.amlet_test.test_alurs_basic'
    
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
        
        # Find the amlet config file
        config_file = os.path.join(os.path.dirname(this_dir), '..', '..', 'configs', 'amlet_default.json')
        config_file = os.path.abspath(config_file)
        
        # Generate ALURS with amlet parameters
        filenames = generate_rtl.generate('ALURS', working_dir, [config_file])
        
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
