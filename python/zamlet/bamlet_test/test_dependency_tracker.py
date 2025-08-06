import os
import sys
import tempfile
from typing import Optional
import logging
import json

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb.triggers import RisingEdge, ReadOnly

from zamlet import generate_rtl
from zamlet import test_utils
from zamlet.bamlet.bamlet_params import BamletParams
from zamlet.amlet.instruction import VLIWInstruction
from zamlet.amlet.control_instruction import ControlInstruction, ControlModes
from zamlet.amlet.alu_instruction import ALUInstruction, ALUModes
from zamlet.amlet.predicate_instruction import PredicateInstruction, PredicateModes
from zamlet.amlet.packet_instruction import PacketInstruction, PacketModes
from zamlet.amlet.alu_lite_instruction import ALULiteInstruction, ALULiteModes
from zamlet.amlet.ldst_instruction import LoadStoreInstruction, LoadStoreModes


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def wait_for_buffers(dut: HierarchyObject) -> None:
    """Wait for data to propagate through input and output buffers"""
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)


async def basic_dependency_test(dut: HierarchyObject, params: BamletParams) -> None:
    """Test basic dependency tracking functionality"""
    # Initialize signals
    dut.io_i_valid.value = 0
    dut.io_o_ready.value = 0
    
    # Reset
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)
    
    # Check initial state - should be ready to accept input
    await ReadOnly()
    assert dut.io_i_ready.value == 1, "DependencyTracker should be ready when empty"
    assert dut.io_o_valid.value == 0, "Output should not be valid when empty"
    
    # Set up a simple VLIW instruction with only control instruction
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 1
    dut.io_i_bits_control_mode.value = ControlModes.LOOP_IMMEDIATE.value
    dut.io_i_bits_control_level.value = 0
    # All other instruction modes should be None/Null by default
    dut.io_i_bits_alu_mode.value = ALUModes.NONE.value
    dut.io_i_bits_predicate_mode.value = PredicateModes.NONE.value
    dut.io_i_bits_packet_mode.value = PacketModes.NONE.value
    dut.io_i_bits_aluLite_mode.value = ALULiteModes.NONE.value
    dut.io_i_bits_loadStore_mode.value = LoadStoreModes.NONE.value
    
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0
    
    await wait_for_buffers(dut)
    
    # Check that output becomes valid
    await ReadOnly()
    assert dut.io_o_valid.value == 1, "Output should be valid after input"
    
    # Check that control instruction is passed through correctly
    assert dut.io_o_bits_control_mode.value == ControlModes.LOOP_IMMEDIATE.value, "Control mode should be LOOP_IMMEDIATE"
    # Other instruction modes should be None/Null since they were dropped
    assert dut.io_o_bits_alu_mode.value == ALUModes.NONE.value, "ALU mode should be None"
    assert dut.io_o_bits_packet_mode.value == PacketModes.NONE.value, "Packet mode should be None"
    
    print("Basic dependency test passed!")


async def dependency_blocking_test(dut: HierarchyObject, params: BamletParams) -> None:
    """Test that instructions with dependencies are properly blocked"""
    # Reset
    await RisingEdge(dut.clock)
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)
    
    # Send first instruction: ALU write to register 1
    dut.io_i_valid.value = 1
    dut.io_i_bits_alu_mode.value = ALUModes.ADD.value
    dut.io_i_bits_alu_src1.value = 5
    dut.io_i_bits_alu_src2.value = 10
    dut.io_i_bits_alu_predicate.value = 0
    dut.io_i_bits_alu_dst.value = 1  # Write to register 1
    # Set other modes to None/Null
    dut.io_i_bits_control_mode.value = ControlModes.NONE.value
    dut.io_i_bits_predicate_mode.value = PredicateModes.NONE.value
    dut.io_i_bits_packet_mode.value = PacketModes.NONE.value
    dut.io_i_bits_aluLite_mode.value = ALULiteModes.NONE.value
    dut.io_i_bits_loadStore_mode.value = LoadStoreModes.NONE.value
    
    await RisingEdge(dut.clock)
    
    # Send second instruction: ALU read from register 1 (RAW dependency)
    dut.io_i_bits_alu_mode.value = ALUModes.ADD.value
    dut.io_i_bits_alu_src1.value = 1  # Read from register 1 - creates RAW dependency
    dut.io_i_bits_alu_src2.value = 12
    dut.io_i_bits_alu_predicate.value = 0
    dut.io_i_bits_alu_dst.value = 2
    
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0
    
    await wait_for_buffers(dut)
    
    # First instruction should be available for output
    await ReadOnly()
    assert dut.io_o_valid.value == 1, "First instruction should be available"
    assert dut.io_o_bits_alu_mode.value == ALUModes.ADD.value, "First ALU instruction should be valid"
    
    # Accept first instruction
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 1
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 0
    
    await wait_for_buffers(dut)
    
    # Now second instruction should become available
    await ReadOnly()
    assert dut.io_o_valid.value == 1, "Second instruction should now be available"
    assert dut.io_o_bits_alu_mode.value == ALUModes.ADD.value, "Second ALU instruction should be valid"
    
    print("Dependency blocking test passed!")


async def age_priority_test(dut: HierarchyObject, params: BamletParams) -> None:
    """Test that older instructions (higher counts) take priority"""
    # Reset
    await RisingEdge(dut.clock)
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)
    
    # Send multiple independent instructions
    for i in range(3):
        dut.io_i_valid.value = 1
        dut.io_i_bits_control_mode.value = ControlModes.LOOP_IMMEDIATE.value
        dut.io_i_bits_control_level.value = i
        # Set other modes to None/Null
        dut.io_i_bits_alu_mode.value = ALUModes.NONE.value
        dut.io_i_bits_predicate_mode.value = PredicateModes.NONE.value
        dut.io_i_bits_packet_mode.value = PacketModes.NONE.value
        dut.io_i_bits_aluLite_mode.value = ALULiteModes.NONE.value
        dut.io_i_bits_loadStore_mode.value = LoadStoreModes.NONE.value
        
        await RisingEdge(dut.clock)
    
    dut.io_i_valid.value = 0
    
    await wait_for_buffers(dut)
    
    # All instructions should be available since they don't have dependencies
    await ReadOnly()
    assert dut.io_o_valid.value == 1, "Instructions should be available"
    
    # Accept them one by one - they should come out in age order (oldest first)
    for i in range(3):
        assert dut.io_o_bits_control_mode.value == ControlModes.LOOP_IMMEDIATE.value, f"Control instruction {i} should be valid"
        
        # Drive ready signal after ReadOnly
        await RisingEdge(dut.clock)
        dut.io_o_ready.value = 1
        await RisingEdge(dut.clock)
        dut.io_o_ready.value = 0
        
        if i < 2:  # Still more instructions to come
            await ReadOnly()
            assert dut.io_o_valid.value == 1, f"Instruction {i+1} should be available"
        await RisingEdge(dut.clock)
        await ReadOnly()
    
    print("Age priority test passed!")


async def null_mode_filtering_test(dut: HierarchyObject, params: BamletParams) -> None:
    """Test that instructions with NULL/None modes are properly dropped"""
    # Reset
    await RisingEdge(dut.clock)
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)
    
    # Send VLIW with mixed valid and NULL instructions
    dut.io_i_valid.value = 1
    dut.io_i_bits_control_mode.value = ControlModes.LOOP_IMMEDIATE.value
    dut.io_i_bits_control_level.value = 0
    # ALU mode set to None - should be dropped
    dut.io_i_bits_alu_mode.value = ALUModes.NONE.value
    dut.io_i_bits_predicate_mode.value = PredicateModes.NONE.value
    dut.io_i_bits_packet_mode.value = PacketModes.NONE.value
    dut.io_i_bits_aluLite_mode.value = ALULiteModes.NONE.value
    dut.io_i_bits_loadStore_mode.value = LoadStoreModes.NONE.value
    
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0
    
    await wait_for_buffers(dut)
    
    # Output should be valid (control instruction should pass through)
    await ReadOnly()
    assert dut.io_o_valid.value == 1, "Valid instruction should pass through"
    
    # Verify that only control instruction has valid mode, others are NULL/None
    assert dut.io_o_bits_control_mode.value == ControlModes.LOOP_IMMEDIATE.value, "Control mode should be LOOP_IMMEDIATE"
    assert dut.io_o_bits_alu_mode.value == ALUModes.NONE.value, "ALU mode should be None"
    assert dut.io_o_bits_predicate_mode.value == PredicateModes.NONE.value, "Predicate mode should be None"
    assert dut.io_o_bits_packet_mode.value == PacketModes.NONE.value, "Packet mode should be None"
    assert dut.io_o_bits_aluLite_mode.value == ALULiteModes.NONE.value, "ALULite mode should be None"
    assert dut.io_o_bits_loadStore_mode.value == LoadStoreModes.NONE.value, "LoadStore mode should be None"
    
    print("NULL mode filtering test passed!")


async def loop_index_dependency_test(dut: HierarchyObject, params: BamletParams) -> None:
    """Test that predicate instruction with loop index src1 depends on control instruction"""
    # Reset
    await RisingEdge(dut.clock)
    dut.reset.value = 1
    await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)
    
    # Send VLIW with both control instruction (loop setup) and predicate instruction (uses loop index)
    dut.io_i_valid.value = 1
    
    # Control instruction: sets up a loop and writes to loop index register
    dut.io_i_bits_control_mode.value = ControlModes.LOOP_IMMEDIATE.value
    dut.io_i_bits_control_dst.value = 5  # Loop index goes to A-register 5
    
    # Predicate instruction: uses loop index as src1 (should depend on control instruction)
    dut.io_i_bits_predicate_mode.value = PredicateModes.EQ.value
    dut.io_i_bits_predicate_src1Mode.value = 1  # LoopIndex mode (Src1Mode.LoopIndex)
    dut.io_i_bits_predicate_src1.value = 0  # Loop level 0
    dut.io_i_bits_predicate_src2.value = 7  # A-register 7
    dut.io_i_bits_predicate_base.value = 1  # P-register 1 (avoid hardwired P-reg 0)
    dut.io_i_bits_predicate_notBase.value = 0
    dut.io_i_bits_predicate_dst.value = 2  # P-register 2
    
    # Set other modes to None/Null
    dut.io_i_bits_alu_mode.value = ALUModes.NONE.value
    dut.io_i_bits_packet_mode.value = PacketModes.NONE.value
    dut.io_i_bits_aluLite_mode.value = ALULiteModes.NONE.value
    dut.io_i_bits_loadStore_mode.value = LoadStoreModes.NONE.value
    
    await RisingEdge(dut.clock)
    dut.io_i_valid.value = 0
    
    await wait_for_buffers(dut)
    
    # Control instruction should be available first, predicate should be blocked due to dependency
    await ReadOnly()
    assert dut.io_o_valid.value == 1, "Control instruction should be available first"
    assert dut.io_o_bits_control_mode.value == ControlModes.LOOP_IMMEDIATE.value, "Control instruction should be valid"
    assert dut.io_o_bits_predicate_mode.value == PredicateModes.NONE.value, "Predicate instruction should be blocked"
    
    # Accept control instruction
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 1
    await RisingEdge(dut.clock)
    dut.io_o_ready.value = 0
    
    await wait_for_buffers(dut)
    
    # Now predicate instruction should become available
    await ReadOnly()
    assert dut.io_o_valid.value == 1, "Predicate instruction should now be available"
    assert dut.io_o_bits_control_mode.value == ControlModes.NONE.value, "Control mode should be None"
    assert dut.io_o_bits_predicate_mode.value == PredicateModes.EQ.value, "Predicate instruction should be valid"
    
    print("Loop index dependency test passed!")


@cocotb.test()
async def dependency_tracker_test(dut: HierarchyObject) -> None:
    """Main test function for DependencyTracker"""
    test_utils.configure_logging_sim("DEBUG")
    
    # Load parameters
    config_file = os.path.join(os.path.dirname(this_dir), '..', '..', 'configs', 'bamlet_default.json')
    config_file = os.path.abspath(config_file)
    with open(config_file, 'r') as f:
        params = BamletParams.from_dict(json.load(f))
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())
    
    # Run tests
    await basic_dependency_test(dut, params)
    await dependency_blocking_test(dut, params)
    await age_priority_test(dut, params)
    await null_mode_filtering_test(dut, params)
    await loop_index_dependency_test(dut, params)
    
    print("All DependencyTracker tests passed!")


def test_dependency_tracker(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "DependencyTracker"
    module = "zamlet.bamlet_test.test_dependency_tracker"
    
    test_params = {
        "seed": seed,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_dependency_tracker(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Find the bamlet config file
        config_file = os.path.join(os.path.dirname(this_dir), '..', '..', 'configs', 'bamlet_default.json')
        config_file = os.path.abspath(config_file)
        
        # Generate DependencyTracker with bamlet parameters
        filenames = generate_rtl.generate("DependencyTracker", working_dir, [config_file])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, "dependency_tracker_verilog.sv")
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_dependency_tracker(concat_filename, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) >= 2:
        # Called from Bazel with verilog_file
        verilog_file = sys.argv[1]
        test_dependency_tracker(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_dependency_tracker()
