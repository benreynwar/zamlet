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
from fmvpu.amlet.alu_instruction import ALUInstruction, ALUModes
from fmvpu.amlet.alu_lite_instruction import ALULiteInstruction, ALULiteModes
from fmvpu.amlet.predicate_instruction import PredicateInstruction, PredicateModes, Src1Mode
from fmvpu.bamlet_kernels.kernel_utils import instructions_into_vliw


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def simple_loop_test(bi: BamletInterface) -> None:
    """Test a simple loop that increments a counter"""
    # Initialize counter and increment value on all amlets
    for offset_x in range(bi.params.n_amlet_columns):
        for offset_y in range(bi.params.n_amlet_rows):
            await bi.write_register('d', 1, 0, offset_x=offset_x, offset_y=offset_y)  # Counter
            await bi.write_register('d', 2, 1, offset_x=offset_x, offset_y=offset_y)  # Increment value
    
    # Create a simple loop that runs 3 times
    instrs = [
        # Loop 3 times -> A-register 1 (loop index)
        ControlInstruction(
            mode=ControlModes.LOOP_IMMEDIATE,
            iterations=3,
            dst=1,         # A-register 1 gets loop index
        ),
        # Increment counter: d1 = d1 + d2
        ALUInstruction(
            mode=ALUModes.ADD,
            src1=1,  # counter
            src2=2,  # increment
            d_dst=1, # store back to counter
        ),
        # End of loop
        ControlInstruction(mode=ControlModes.END_LOOP),
        # Halt
        ControlInstruction(mode=ControlModes.HALT),
    ]
    
    program = instructions_into_vliw(bi.params, instrs)
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check that counter was incremented 3 times: 0 + 3*1 = 3
    result = bi.probe_register('d', 1)
    assert result == 3, f"Expected 3, got {result}"
    
    # Check final loop index value (should be 2 after 3 iterations: 0, 1, 2)
    index_result = bi.probe_register('a', 1)
    assert index_result == 2, f"Expected final loop index 2, got {index_result}"


async def loop_local_test(bi: BamletInterface) -> None:
    """Test LOOP_LOCAL mode using A-register for iteration count"""
    # Initialize counter, increment value, and iteration count on all amlets
    for offset_x in range(bi.params.n_amlet_columns):
        for offset_y in range(bi.params.n_amlet_rows):
            await bi.write_register('d', 1, 0, offset_x=offset_x, offset_y=offset_y)  # Counter
            await bi.write_register('d', 2, 2, offset_x=offset_x, offset_y=offset_y)  # Increment value
            await bi.write_register('a', 3, 5, offset_x=offset_x, offset_y=offset_y)  # Iteration count in A-register 3
    
    instrs = [
        # Loop using A-register 3 for iteration count
        ControlInstruction(
            mode=ControlModes.LOOP_LOCAL,
            iterations=3,  # A-register index containing iteration count
            dst=1,               # A-register 1 gets loop index
        ),
        # Increment counter: d1 = d1 + d2
        ALUInstruction(
            mode=ALUModes.ADD,
            src1=1,  # counter
            src2=2,  # increment
            d_dst=1, # store back to counter
        ),
        # End of loop
        ControlInstruction(mode=ControlModes.END_LOOP),
        # Halt
        ControlInstruction(mode=ControlModes.HALT),
    ]
    
    program = instructions_into_vliw(bi.params, instrs)
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check that counter was incremented 5 times: 0 + 5*2 = 10
    result = bi.probe_register('d', 1)
    assert result == 10, f"Expected 10, got {result}"
    
    # Check final loop index value (should be 4 after 5 iterations: 0, 1, 2, 3, 4)
    index_result = bi.probe_register('a', 1)
    assert index_result == 4, f"Expected final loop index 4, got {index_result}"


async def loop_global_test(bi: BamletInterface) -> None:
    """Test LOOP_GLOBAL mode using G-register for iteration count"""
    # Initialize counter and increment value on all amlets
    for offset_x in range(bi.params.n_amlet_columns):
        for offset_y in range(bi.params.n_amlet_rows):
            await bi.write_register('d', 1, 0, offset_x=offset_x, offset_y=offset_y)  # Counter
            await bi.write_register('d', 2, 3, offset_x=offset_x, offset_y=offset_y)  # Increment value
    
    # G-register is shared, only write to one amlet
    await bi.write_register('g', 4, 4)  # Iteration count in G-register 4
    
    instrs = [
        # Loop using G-register 4 for iteration count
        ControlInstruction(
            mode=ControlModes.LOOP_GLOBAL,
            iterations=4,  # G-register index containing iteration count
            dst=1,               # A-register 1 gets loop index
        ),
        # Increment counter: d1 = d1 + d2
        ALUInstruction(
            mode=ALUModes.ADD,
            src1=1,  # counter
            src2=2,  # increment
            d_dst=1, # store back to counter
        ),
        # End of loop
        ControlInstruction(mode=ControlModes.END_LOOP),
        # Halt
        ControlInstruction(mode=ControlModes.HALT),
    ]
    
    program = instructions_into_vliw(bi.params, instrs)
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check that counter was incremented 4 times: 0 + 4*3 = 12
    result = bi.probe_register('d', 1)
    assert result == 12, f"Expected 12, got {result}"
    
    # Check final loop index value (should be 3 after 4 iterations: 0, 1, 2, 3)
    index_result = bi.probe_register('a', 1)
    assert index_result == 3, f"Expected final loop index 3, got {index_result}"


async def nested_loops_test(bi: BamletInterface) -> None:
    """Test nested loops functionality"""
    # Initialize counter and increment values on all amlets
    for offset_x in range(bi.params.n_amlet_columns):
        for offset_y in range(bi.params.n_amlet_rows):
            await bi.write_register('d', 1, 0, offset_x=offset_x, offset_y=offset_y)  # Counter
            await bi.write_register('d', 2, 1, offset_x=offset_x, offset_y=offset_y)  # Increment value
    
    instrs = [
        # Outer loop: 3 iterations -> A-register 1
        ControlInstruction(
            mode=ControlModes.LOOP_IMMEDIATE,
            iterations=3,
            dst=1,         # A-register 1 gets outer loop index
        ),
        # Inner loop: 2 iterations -> A-register 2
        ControlInstruction(
            mode=ControlModes.LOOP_IMMEDIATE,
            iterations=2,
            dst=2,         # A-register 2 gets inner loop index
        ),
        # Increment counter: d1 = d1 + d2
        ALUInstruction(
            mode=ALUModes.ADD,
            src1=1,  # counter
            src2=2,  # increment
            d_dst=1, # store back to counter
        ),
        # End inner loop
        ControlInstruction(mode=ControlModes.END_LOOP),
        # End outer loop
        ControlInstruction(mode=ControlModes.END_LOOP),
        # Halt
        ControlInstruction(mode=ControlModes.HALT),
    ]
    
    program = instructions_into_vliw(bi.params, instrs)
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check that counter was incremented 3*2 = 6 times: 0 + 6*1 = 6
    result = bi.probe_register('d', 1)
    assert result == 6, f"Expected 6, got {result}"
    
    # Check final loop index values for nested loops
    # Outer loop: 3 iterations (0,1,2), Inner loop: 2 iterations (0,1) each time
    outer_index_result = bi.probe_register('a', 1)
    inner_index_result = bi.probe_register('a', 2)
    assert outer_index_result == 2, f"Expected final outer loop index 2, got {outer_index_result}"
    assert inner_index_result == 1, f"Expected final inner loop index 1, got {inner_index_result}"


async def loop_index_usage_test(bi: BamletInterface) -> None:
    """Test using loop index in ALU operations"""
    # Initialize counter and base value on all amlets
    for offset_x in range(bi.params.n_amlet_columns):
        for offset_y in range(bi.params.n_amlet_rows):
            await bi.write_register('d', 1, 0, offset_x=offset_x, offset_y=offset_y)  # Accumulator
            await bi.write_register('a', 2, 10, offset_x=offset_x, offset_y=offset_y)  # Base value
    
    instrs = [
        # Loop 4 times -> A-register 1 (loop index)
        ControlInstruction(
            mode=ControlModes.LOOP_IMMEDIATE,
            iterations=4,
            dst=1,         # A-register 1 gets loop index (0, 1, 2, 3)
        ),
        # Add loop index to base value and store to D-register: d2 = a1 + a2 (loop_index + base_value)
        ALULiteInstruction(
            mode=ALULiteModes.ADD,
            src1=1,    # loop index (A-register 1)
            src2=2,    # base value (A-register 2) 
            d_dst=2,   # store result in D-register 2
        ),
        # Add result to accumulator: d1 = d1 + d2 (accumulator += result)
        ALUInstruction(
            mode=ALUModes.ADD,
            src1=1,    # current accumulator value (D-register)
            src2=2,    # computed value from ALU Lite (D-register)
            d_dst=1,   # store back to accumulator
        ),
        # End of loop
        ControlInstruction(mode=ControlModes.END_LOOP),
        # Halt
        ControlInstruction(mode=ControlModes.HALT),
    ]
    
    program = instructions_into_vliw(bi.params, instrs)
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Expected: loop_index goes 0,1,2,3; base_value=10
    # Iteration 0: 0 + 10 = 10, accumulator = 0 + 10 = 10
    # Iteration 1: 1 + 10 = 11, accumulator = 10 + 11 = 21  
    # Iteration 2: 2 + 10 = 12, accumulator = 21 + 12 = 33
    # Iteration 3: 3 + 10 = 13, accumulator = 33 + 13 = 46
    result = bi.probe_register('d', 1)
    assert result == 46, f"Expected 46, got {result}"
    
    # Check final loop index value (should be 3 after 4 iterations: 0, 1, 2, 3)
    index_result = bi.probe_register('a', 1)
    assert index_result == 3, f"Expected final loop index 3, got {index_result}"


@cocotb.test()
async def bamlet_loops_test(dut: HierarchyObject) -> None:
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
    
    # Run all loop tests

    await simple_loop_test(bi)
    await loop_local_test(bi)
    await loop_global_test(bi)
    await nested_loops_test(bi)
    await loop_index_usage_test(bi)
    await loop_predicate_different_bounds_test(bi)


async def loop_predicate_different_bounds_test(bi: BamletInterface) -> None:
    """Test loop with different iteration counts in different amlets using loop predicate"""
    # Initialize counter and increment values on all amlets
    for offset_x in range(bi.params.n_amlet_columns):
        for offset_y in range(bi.params.n_amlet_rows):
            await bi.write_register('d', 1, 0, offset_x=offset_x, offset_y=offset_y)  # Counter
            await bi.write_register('d', 2, 1, offset_x=offset_x, offset_y=offset_y)  # Increment value
            
            # Set different iteration counts in different amlets
            if offset_x == 0 and offset_y == 0:
                # Amlet (0,0): 3 iterations
                await bi.write_register('a', 3, 3, offset_x=offset_x, offset_y=offset_y)
            else:
                # Other amlets: 5 iterations
                await bi.write_register('a', 3, 5, offset_x=offset_x, offset_y=offset_y)
    
    instrs = [
        # Loop using A-register 3 for iteration count (LOOP_LOCAL)
        # This will run for max(3, 5) = 5 iterations total
        ControlInstruction(
            mode=ControlModes.LOOP_LOCAL,
            iterations=3,  # A-register index containing iteration count
            dst=1,               # A-register 1 gets loop index
        ),
        PredicateInstruction(
            mode=PredicateModes.LT,
            src1_mode=Src1Mode.LOOP_INDEX,
            src1_value=0, # Loop level 0
            src2=3, # A-reg 3
            dst=1,
            ),
        # Conditionally increment counter: d1 = d1 + d2, only when loop predicate is true
        # This will only execute when loop_index < iteration_count for each amlet
        ALUInstruction(
            mode=ALUModes.ADD,
            src1=1,        # counter
            src2=2,        # increment
            d_dst=1,       # store back to counter
            predicate=1,   # Only execute when loop predicate is true
        ),
        # End of loop
        ControlInstruction(mode=ControlModes.END_LOOP),
        # Halt
        ControlInstruction(mode=ControlModes.HALT),
    ]
    # FIXME:  There is a fundamental problem with the way that I'm doing predicates.
    # If the predicate is false but someone is listening for that write, then when it resolves they
    # don't know what value they should use.
    # It needs rethinking.

    # In the RegisterFile we need to store the most latest value (with it's tag) along with the latest
    # tag issued.  We also need a bitfield that store what tags are pending as well as which ones arrived
    # but had a false predicate.  Then we can work out whether the value is current.

    # Similary in the Reservation Station we need to store all this information so we know when we can
    # resolve the value.
    # 
    # Actually we just need to know which are pending and what the tag was for the current value.
    # Once all the tags after the tag for the current value are not pending we know they had false
    # predicates so we can resolve.
    
    program = instructions_into_vliw(bi.params, instrs)
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check results for amlet (0,0) - should have incremented 3 times
    result_00 = bi.probe_register('d', 1, offset_x=0, offset_y=0)
    assert result_00 == 3, f"Expected 3 increments in amlet (0,0), got {result_00}"
    
    # Check results for other amlets - should have incremented 5 times
    if bi.params.n_amlet_rows > 1 or bi.params.n_amlet_columns > 1:
        for offset_x in range(bi.params.n_amlet_columns):
            for offset_y in range(bi.params.n_amlet_rows):
                if not (offset_x == 0 and offset_y == 0):  # Skip (0,0) amlet
                    result = bi.probe_register('d', 1, offset_x=offset_x, offset_y=offset_y)
                    assert result == 5, f"Expected 5 increments in amlet ({offset_x},{offset_y}), got {result}"


def test_bamlet_loops(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "Bamlet"
    module = "fmvpu.bamlet_test.test_loops"
    
    test_params = {
        "seed": seed,
        "params_file": params_file,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_bamlet_loops(temp_dir: Optional[str] = None, seed: int = 0) -> None:
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
        
        test_bamlet_loops(concat_filename, config_file, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        assert len(sys.argv) >= 3
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_bamlet_loops(verilog_file, config_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_bamlet_loops()
