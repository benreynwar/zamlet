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

from fmvpu import generate_rtl
from fmvpu import test_utils
from fmvpu.bamlet.bamlet_interface import BamletInterface
from fmvpu.bamlet.bamlet_params import BamletParams
from fmvpu.amlet.instruction import VLIWInstruction
from fmvpu.amlet.control_instruction import ControlInstruction, ControlModes
from fmvpu.amlet.alu_lite_instruction import ALULiteInstruction, ALULiteModes
from fmvpu.amlet import packet_utils


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def alu_lite_add_test(bi: BamletInterface) -> None:
    """Test ADD operation: reg1 + reg2 -> reg3"""
    await bi.write_register('a', 1, 15)
    await bi.write_register('a', 2, 7)
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu_lite=ALULiteInstruction(
                mode=ALULiteModes.ADD,
                src1=1,
                src2=2,
                a_dst=3,  # A-register 3
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check result in register 3
    result = bi.probe_register('a', 3)
    assert result == 22, f"Expected 22, got {result}"


async def alu_lite_addi_test(bi: BamletInterface) -> None:
    """Test ADDI operation: reg1 + immediate -> reg3"""
    await bi.write_register('a', 1, 10)
    await bi.write_register('a', 2, 5)  # immediate value in reg2
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu_lite=ALULiteInstruction(
                mode=ALULiteModes.ADDI,
                src1=1,
                src2=2,  # immediate value
                a_dst=3,  # A-register 3
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check result in register 3
    result = bi.probe_register('a', 3)
    assert result == 12, f"Expected 12, got {result}"


async def alu_lite_sub_test(bi: BamletInterface) -> None:
    """Test SUB operation: reg1 - reg2 -> reg3"""
    await bi.write_register('a', 1, 20)
    await bi.write_register('a', 2, 8)
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu_lite=ALULiteInstruction(
                mode=ALULiteModes.SUB,
                src1=1,
                src2=2,
                a_dst=3,  # A-register 3
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check result in register 3
    result = bi.probe_register('a', 3)
    assert result == 12, f"Expected 12, got {result}"


async def alu_lite_mult_test(bi: BamletInterface) -> None:
    """Test MULT operation: reg1 * reg2 -> reg3"""
    await bi.write_register('a', 1, 6)
    await bi.write_register('a', 2, 7)
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu_lite=ALULiteInstruction(
                mode=ALULiteModes.MULT,
                src1=1,
                src2=2,
                a_dst=3,  # A-register 3
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check result in register 3
    result = bi.probe_register('a', 3)
    assert result == 42, f"Expected 42, got {result}"


async def alu_lite_chain_operations_test(bi: BamletInterface) -> None:
    """Test chained ALULite operations with dependencies"""
    await bi.write_register('a', 1, 3)
    await bi.write_register('a', 2, 4)
    
    program = [
        # reg4 = reg1 + reg2 (3 + 4 = 7)
        VLIWInstruction(
            alu_lite=ALULiteInstruction(
                mode=ALULiteModes.ADD,
                src1=1,
                src2=2,
                a_dst=4,  # A-register 4
            )
        ),
        # reg5 = reg4 * reg1 (7 * 3 = 21)
        VLIWInstruction(
            alu_lite=ALULiteInstruction(
                mode=ALULiteModes.MULT,
                src1=4,
                src2=1,
                a_dst=5,  # A-register 5
            )
        ),
        # reg6 = reg5 - reg2 (21 - 4 = 17)
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu_lite=ALULiteInstruction(
                mode=ALULiteModes.SUB,
                src1=5,
                src2=2,
                a_dst=6,  # A-register 6
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check intermediate and final results
    result4 = bi.probe_register('a', 4)
    assert result4 == 7, f"Expected 7 in register 4, got {result4}"
    result5 = bi.probe_register('a', 5)
    assert result5 == 21, f"Expected 21 in register 5, got {result5}"
    result6 = bi.probe_register('a', 6)
    assert result6 == 17, f"Expected 17 in register 6, got {result6}"


async def alu_lite_predicate_test(bi: BamletInterface) -> None:
    """Test ALULite instruction predicate field - operations should only execute when predicate is true"""
    # Initialize source registers
    await bi.write_register('a', 1, 10)
    await bi.write_register('a', 2, 5)
    await bi.write_register('a', 3, 0)  # Clear destination register
    
    # Test 1: Set predicate register 1 to false (0), ALULite should not execute
    await bi.write_register('p', 1, 0)  # Predicate false
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu_lite=ALULiteInstruction(
                mode=ALULiteModes.ADD,
                src1=1,
                src2=2,
                a_dst=3,
                predicate=1,  # Use P-register 1 as predicate
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check that destination register wasn't modified (predicate was false)
    result = bi.probe_register('a', 3)
    assert result == 0, f"Expected 0 (no execution), got {result}"
    
    # Test 2: Set predicate register 1 to true (1), ALULite should execute
    await bi.write_register('p', 1, 1)  # Predicate true
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu_lite=ALULiteInstruction(
                mode=ALULiteModes.ADD,
                src1=1,
                src2=2,
                a_dst=3,
                predicate=1,  # Use P-register 1 as predicate
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check that operation executed (10 + 5 = 15)
    result = bi.probe_register('a', 3)
    assert result == 15, f"Expected 15 (executed), got {result}"


@cocotb.test()
async def bamlet_alu_lite_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    test_params = test_utils.read_params()
    seed = test_params['seed']
    with open(test_params['params_file']) as f:
        params = BamletParams.from_dict(json.load(f))

    rnd = Random(seed)
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())
    
    # Create the bamlet interface
    bi = BamletInterface(dut, params, rnd, 1, 1)
    bi.initialize_signals()
    await bi.start()
    
    # Run ALULite tests - basic operations only
    await alu_lite_add_test(bi)
    await alu_lite_addi_test(bi)
    await alu_lite_sub_test(bi)
    await alu_lite_mult_test(bi)
    await alu_lite_chain_operations_test(bi)
    await alu_lite_predicate_test(bi)


def test_bamlet_alu_lite(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "Bamlet"
    module = "fmvpu.bamlet_test.test_alu_lite"
    
    test_params = {
        "seed": seed,
        "params_file": params_file,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_bamlet_alu_lite(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Find the bamlet config file
        config_file = os.path.join(
            os.path.dirname(this_dir), "..", "..", "configs", "bamlet_default.json"
        )
        config_file = os.path.abspath(config_file)
        
        # Generate Bamlet with bamlet parameters
        filenames = generate_rtl.generate("Bamlet", working_dir, [config_file])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, "bamlet_verilog.sv")
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_bamlet_alu_lite(concat_filename, config_file, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        assert len(sys.argv) >= 3
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_bamlet_alu_lite(verilog_file, config_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_bamlet_alu_lite()
