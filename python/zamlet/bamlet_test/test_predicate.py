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

from zamlet import generate_rtl
from zamlet import test_utils
from zamlet.bamlet.bamlet_interface import BamletInterface
from zamlet.bamlet.bamlet_params import BamletParams
from zamlet.amlet.instruction import VLIWInstruction
from zamlet.amlet.control_instruction import ControlInstruction, ControlModes
from zamlet.amlet.predicate_instruction import PredicateInstruction, PredicateModes, Src1Mode


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def predicate_eq_immediate_test(bi: BamletInterface) -> None:
    """Test EQ predicate with immediate value"""
    # Set up A-register with test value (use small value that fits in 4-bit immediate field)
    test_value = 10  # Fits in 4 bits (0-15 range)
    await bi.write_register('a', 1, test_value)
    await bi.write_register('p', 1, 1)  # Base predicate true
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            predicate=PredicateInstruction(
                mode=PredicateModes.EQ,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=test_value,  # Compare with same value
                src2=1,  # A-register 1
                base=1,  # P-register 1 (base predicate)
                not_base=False,
                dst=2    # P-register 2 (destination)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Should be true (42 == 42)
    result = bi.probe_register('p', 2)
    assert result == 1, f"Expected 1 (equal), got {result}"


async def predicate_neq_immediate_test(bi: BamletInterface) -> None:
    """Test NEQ predicate with immediate value"""
    # Set up A-register with test value (use small values that fit in 4-bit immediate field)
    await bi.write_register('a', 1, 8)  # Fits in 4 bits
    await bi.write_register('p', 1, 1)  # Base predicate true
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            predicate=PredicateInstruction(
                mode=PredicateModes.NEQ,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=3,  # Compare with different value (3 != 8)
                src2=1,  # A-register 1
                base=1,  # P-register 1 (base predicate)
                not_base=False,
                dst=2    # P-register 2 (destination)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Should be true (25 != 42)
    result = bi.probe_register('p', 2)
    assert result == 1, f"Expected 1 (not equal), got {result}"


async def predicate_gt_immediate_test(bi: BamletInterface) -> None:
    """Test GT predicate with immediate value"""
    # Set up A-register with test value (use small values that fit in 4-bit immediate field)
    await bi.write_register('a', 1, 12)  # Fits in 4 bits
    await bi.write_register('p', 1, 1)  # Base predicate true
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            predicate=PredicateInstruction(
                mode=PredicateModes.GT,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=7,  # 7 > 12? No
                src2=1,  # A-register 1
                base=1,  # P-register 1 (base predicate)
                not_base=False,
                dst=2    # P-register 2 (destination)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Should be false (7 > 12 is false)
    result = bi.probe_register('p', 2)
    assert result == 0, f"Expected 0 (not greater), got {result}"


async def predicate_gte_immediate_test(bi: BamletInterface) -> None:
    """Test GTE predicate with immediate value"""
    # Set up A-register with test value (use small values that fit in 4-bit immediate field)
    test_value = 5  # Fits in 4 bits (0-15 range)
    await bi.write_register('a', 1, test_value)
    await bi.write_register('p', 1, 1)  # Base predicate true
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            predicate=PredicateInstruction(
                mode=PredicateModes.GTE,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=test_value,  # 5 >= 5? Yes
                src2=1,  # A-register 1
                base=1,  # P-register 1 (base predicate)
                not_base=False,
                dst=2    # P-register 2 (destination)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Should be true (30 >= 30)
    result = bi.probe_register('p', 2)
    assert result == 1, f"Expected 1 (greater or equal), got {result}"


async def predicate_lt_immediate_test(bi: BamletInterface) -> None:
    """Test LT predicate with immediate value"""
    # Set up A-register with test value (use small values that fit in 4-bit immediate field)
    await bi.write_register('a', 1, 6)  # Fits in 4 bits
    await bi.write_register('p', 1, 1)  # Base predicate true
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            predicate=PredicateInstruction(
                mode=PredicateModes.LT,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=9,  # 9 < 6? No
                src2=1,  # A-register 1
                base=1,  # P-register 1 (base predicate)
                not_base=False,
                dst=2    # P-register 2 (destination)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Should be false (9 < 6 is false)
    result = bi.probe_register('p', 2)
    assert result == 0, f"Expected 0 (not less), got {result}"


async def predicate_lte_immediate_test(bi: BamletInterface) -> None:
    """Test LTE predicate with immediate value"""
    # Set up A-register with test value (use small values that fit in 4-bit immediate field)
    await bi.write_register('a', 1, 11)  # Fits in 4 bits
    await bi.write_register('p', 1, 1)  # Base predicate true
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            predicate=PredicateInstruction(
                mode=PredicateModes.LTE,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=11,  # 11 <= 11? Yes
                src2=1,  # A-register 1
                base=1,  # P-register 1 (base predicate)
                not_base=False,
                dst=2    # P-register 2 (destination)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Should be true (15 <= 15)
    result = bi.probe_register('p', 2)
    assert result == 1, f"Expected 1 (less or equal), got {result}"


async def predicate_base_false_test(bi: BamletInterface) -> None:
    """Test that predicate results are AND'ed with base predicate"""
    # Set up A-register with test value (use small values that fit in 4-bit immediate field)
    await bi.write_register('a', 1, 7)  # Fits in 4 bits
    await bi.write_register('p', 1, 0)  # Base predicate false
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            predicate=PredicateInstruction(
                mode=PredicateModes.EQ,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=7,  # Should be equal
                src2=1,  # A-register 1
                base=1,  # P-register 1 (base predicate - false)
                not_base=False,
                dst=2    # P-register 2 (destination)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Should be false (true AND false = false)
    result = bi.probe_register('p', 2)
    assert result == 0, f"Expected 0 (base predicate false), got {result}"


async def predicate_not_base_test(bi: BamletInterface) -> None:
    """Test predicate with negated base predicate"""
    # Set up A-register with test value (use small values that fit in 4-bit immediate field)
    await bi.write_register('a', 1, 9)  # Fits in 4 bits
    await bi.write_register('p', 1, 0)  # Base predicate false
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            predicate=PredicateInstruction(
                mode=PredicateModes.EQ,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=9,  # Should be equal
                src2=1,  # A-register 1
                base=1,  # P-register 1 (base predicate - false)
                not_base=True,  # Negate base predicate
                dst=2    # P-register 2 (destination)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Should be true (true AND !false = true AND true = true)
    result = bi.probe_register('p', 2)
    assert result == 1, f"Expected 1 (negated base predicate), got {result}"


async def predicate_global_src_test(bi: BamletInterface) -> None:
    """Test predicate with global register as source"""
    # Set up A-register and global register with test values (use small values that fit in 4-bit immediate field)
    await bi.write_register('a', 1, 13)  # Fits in 4 bits
    await bi.write_register('g', 2, 13)  # Global register 2, same value
    await bi.write_register('p', 1, 1)  # Base predicate true
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            predicate=PredicateInstruction(
                mode=PredicateModes.EQ,
                src1_mode=Src1Mode.GLOBAL,
                src1_value=2,  # Global register 2
                src2=1,  # A-register 1
                base=1,  # P-register 1 (base predicate)
                not_base=False,
                dst=2    # P-register 2 (destination)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Should be true (13 == 13)
    result = bi.probe_register('p', 2)
    assert result == 1, f"Expected 1 (equal global values), got {result}"


async def predicate_multiple_registers_test(bi: BamletInterface) -> None:
    """Test predicate operations with multiple different registers"""
    # Set up multiple test values (use small values that fit in 4-bit immediate field)
    await bi.write_register('a', 1, 4)   # Fits in 4 bits
    await bi.write_register('a', 2, 8)   # Fits in 4 bits
    await bi.write_register('a', 3, 12)  # Fits in 4 bits
    await bi.write_register('p', 1, 1)   # Base predicate true
    
    program = [
        # Test 1: 6 > 4? Yes -> p2 = true
        VLIWInstruction(
            predicate=PredicateInstruction(
                mode=PredicateModes.GT,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=6,
                src2=1,  # A-register 1 (4)
                base=1,  # P-register 1 (true)
                not_base=False,
                dst=2    # P-register 2
            )
        ),
        # Test 2: 15 < 8? No -> p3 = false
        VLIWInstruction(
            predicate=PredicateInstruction(
                mode=PredicateModes.LT,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=15,
                src2=2,  # A-register 2 (8)
                base=1,  # P-register 1 (true)
                not_base=False,
                dst=3    # P-register 3
            )
        ),
        # Test 3: 12 >= 12? Yes -> p4 = true
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            predicate=PredicateInstruction(
                mode=PredicateModes.GTE,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=12,
                src2=3,  # A-register 3 (12)
                base=1,  # P-register 1 (true)
                not_base=False,
                dst=4    # P-register 4
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check results
    result2 = bi.probe_register('p', 2)
    assert result2 == 1, f"Expected 1 (6 > 4), got {result2}"
    
    result3 = bi.probe_register('p', 3)
    assert result3 == 0, f"Expected 0 (15 < 8 is false), got {result3}"
    
    result4 = bi.probe_register('p', 4)
    assert result4 == 1, f"Expected 1 (12 >= 12), got {result4}"


async def predicate_none_mode_test(bi: BamletInterface) -> None:
    """Test NONE mode predicate instruction"""
    # Set up initial predicate states
    await bi.write_register('p', 2, 1)  # Set destination to 1 initially
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            predicate=PredicateInstruction(
                mode=PredicateModes.NONE,
                src1_mode=Src1Mode.IMMEDIATE,
                src1_value=0,
                src2=0,
                base=0,
                not_base=False,
                dst=2    # P-register 2 (should remain unchanged)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # NONE mode should not modify the destination register
    result = bi.probe_register('p', 2)
    assert result == 1, f"Expected 1 (unchanged), got {result}"


@cocotb.test()
async def bamlet_predicate_test(dut: HierarchyObject) -> None:
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
    
    # Run predicate tests
    await predicate_eq_immediate_test(bi)
    await predicate_neq_immediate_test(bi)
    await predicate_gt_immediate_test(bi)
    await predicate_gte_immediate_test(bi)
    await predicate_lt_immediate_test(bi)
    await predicate_lte_immediate_test(bi)
    await predicate_base_false_test(bi)
    await predicate_not_base_test(bi)
    await predicate_global_src_test(bi)
    await predicate_multiple_registers_test(bi)
    await predicate_none_mode_test(bi)


def test_bamlet_predicate(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "Bamlet"
    module = "zamlet.bamlet_test.test_predicate"
    
    test_params = {
        "seed": seed,
        "params_file": params_file,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_bamlet_predicate(temp_dir: Optional[str] = None, seed: int = 0) -> None:
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
        
        test_bamlet_predicate(concat_filename, config_file, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        assert len(sys.argv) >= 3
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_bamlet_predicate(verilog_file, config_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_bamlet_predicate()
