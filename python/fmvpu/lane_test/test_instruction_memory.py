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
async def instruction_memory_basic_test(dut: HierarchyObject) -> None:
    """Basic functionality test for InstructionMemory module."""
    clock = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock.start())
    
    # Reset sequence
    dut.reset.value = 1
    await triggers.ClockCycles(dut.clock, 5)
    dut.reset.value = 0
    await triggers.ClockCycles(dut.clock, 5)
    
    # Test write operations
    test_instructions = [
        (0, 0x12345678),
        (1, 0xABCDEF00),
        (10, 0x11111111),
        (63, 0xFFFFFFFF)  # Last address
    ]
    
    # Write test instructions
    for addr, instr in test_instructions:
        dut.io_writeAddress.value = addr
        dut.io_writeData.value = instr
        dut.io_writeEnable.value = 1
        await triggers.ClockCycles(dut.clock, 1)
        dut.io_writeEnable.value = 0
        await triggers.ClockCycles(dut.clock, 1)
    
    # Test read operations with pipeline timing
    for addr, expected_instr in test_instructions:
        # Start read
        dut.io_readAddress.value = addr
        dut.io_readValid.value = 1
        await triggers.ClockCycles(dut.clock, 1)
        dut.io_readValid.value = 0
        
        # Wait for pipeline delay (2 cycles total)
        await triggers.ClockCycles(dut.clock, 1)
        
        # Check results
        assert dut.io_instructionValid.value == 1, f"instructionValid should be 1 for address {addr}"
        actual_instr = int(dut.io_instruction.value)
        assert actual_instr == expected_instr, f"Expected 0x{expected_instr:08x}, got 0x{actual_instr:08x} at address {addr}"
        
        await triggers.ClockCycles(dut.clock, 1)

@cocotb.test()
async def instruction_memory_edge_cases_test(dut: HierarchyObject) -> None:
    """Test edge cases and boundary conditions."""
    clock = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock.start())
    
    # Reset sequence
    dut.reset.value = 1
    await triggers.ClockCycles(dut.clock, 5)
    dut.reset.value = 0
    await triggers.ClockCycles(dut.clock, 5)
    
    # Test read without valid signal
    dut.io_readAddress.value = 0
    dut.io_readValid.value = 0
    await triggers.ClockCycles(dut.clock, 3)
    
    # instructionValid should remain 0
    assert dut.io_instructionValid.value == 0, "instructionValid should be 0 when readValid is 0"
    
    # Test uninitialized memory read
    dut.io_readAddress.value = 32  # Unwritten address
    dut.io_readValid.value = 1
    await triggers.ClockCycles(dut.clock, 1)
    dut.io_readValid.value = 0
    await triggers.ClockCycles(dut.clock, 2)
    
    # Should get some value (likely 0 or undefined)
    assert dut.io_instructionValid.value == 1, "instructionValid should be 1 after valid read"

def test_instruction_memory(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    print(f"Testing InstructionMemory with verilog file: {verilog_file}")
    
    test_utils.configure_logging_pre_sim()
    test_utils.run_test(
        verilog_file=verilog_file,
        test_module="test_instruction_memory",
        test_dir=this_dir,
        extra_env={"RANDOM_SEED": str(seed)}
    )

def generate_and_test_instruction_memory(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    config_file = os.path.join(this_dir, "../../../../configs/lane_default.json")
    
    if temp_dir is None:
        temp_dir = tempfile.mkdtemp()
        
    print(f"Generating InstructionMemory Verilog in {temp_dir}")
    
    # Generate Verilog
    generate_rtl.generate(
        output_dir=temp_dir,
        module_name="InstructionMemory",
        module_args=[config_file]
    )
    
    verilog_file = os.path.join(temp_dir, "InstructionMemory.sv")
    
    if not os.path.exists(verilog_file):
        raise FileNotFoundError(f"Generated Verilog file not found: {verilog_file}")
    
    test_instruction_memory(verilog_file, seed)

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Test InstructionMemory module')
    parser.add_argument('--verilog-file', type=str, help='Pre-generated Verilog file to test')
    parser.add_argument('--temp-dir', type=str, help='Temporary directory for generated files')
    parser.add_argument('--seed', type=int, default=0, help='Random seed for simulation')
    
    args = parser.parse_args()
    
    if args.verilog_file:
        test_instruction_memory(args.verilog_file, args.seed)
    else:
        generate_and_test_instruction_memory(args.temp_dir, args.seed)