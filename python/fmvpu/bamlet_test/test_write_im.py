import os
import sys
import tempfile
from typing import Optional
import logging
from random import Random
import json

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from fmvpu import generate_rtl
from fmvpu import test_utils
from fmvpu.bamlet.bamlet_interface import BamletInterface
from fmvpu.bamlet.bamlet_params import BamletParams
from fmvpu.amlet.instruction import VLIWInstruction, create_halt_instruction


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def write_instruction_test(bi: BamletInterface) -> None:
    """Test writing a single instruction to instruction memory and probe the output"""
    # Create a simple halt instruction
    halt_instr = create_halt_instruction()
    
    # Write the instruction to address 0
    program = [halt_instr]
    await bi.write_program(program, base_address=0)
    
    # Wait a few cycles for the write to complete
    for _ in range(10):
        await triggers.RisingEdge(bi.dut.clock)
    
    logger.info("Successfully wrote instruction to IM")
    
    # Now start the control unit to fetch and parse the instruction
    await bi.start_program(pc=0)
    
    # Wait a few cycles for the instruction to be fetched and parsed
    for _ in range(5):
        await triggers.RisingEdge(bi.dut.clock)
        
        # Check if instruction is valid on the control output
        if bi.dut.control.io_instr_valid.value == 1:
            logger.info("Instruction fetched and parsed by control unit")
            
            # Probe the VLIW instruction components
            # Control instruction
            control_halt = bi.dut.control.io_instr_bits_control_halt.value
            control_mode = bi.dut.control.io_instr_bits_control_mode.value
            
            # ALU instruction  
            alu_mode = bi.dut.control.io_instr_bits_alu_mode.value
            
            # Load/Store instruction
            ldst_mode = bi.dut.control.io_instr_bits_loadStore_mode.value
            
            # Packet instruction
            packet_mode = bi.dut.control.io_instr_bits_packet_mode.value
            
            logger.info(f"Instruction components:")
            logger.info(f"  Control: halt={control_halt}, mode={control_mode}")
            logger.info(f"  ALU: mode={alu_mode}")
            logger.info(f"  LoadStore: mode={ldst_mode}")
            logger.info(f"  Packet: mode={packet_mode}")
            
            # Verify this matches our expected halt instruction
            # A halt instruction should have control.halt=1 and other modes=0
            assert control_halt == 1, f"Expected halt=1, got {control_halt}"
            assert alu_mode == 0, f"Expected ALU mode=0, got {alu_mode}"
            assert ldst_mode == 0, f"Expected LoadStore mode=0, got {ldst_mode}"
            assert packet_mode == 0, f"Expected Packet mode=0, got {packet_mode}"
            
            logger.info("Instruction verification successful!")
            break
    else:
        assert False, "No valid instruction found on control output"


async def write_multiple_instructions_test(bi: BamletInterface) -> None:
    """Test writing multiple instructions to instruction memory"""
    # Create multiple halt instructions
    program = [create_halt_instruction() for _ in range(5)]
    
    # Write the instructions starting at address 10
    await bi.write_program(program, base_address=10)
    
    # Wait for writes to complete
    for _ in range(20):
        await triggers.RisingEdge(bi.dut.clock)
    
    logger.info("Successfully wrote multiple instructions to IM")


@cocotb.test()
async def bamlet_write_im_test(dut: HierarchyObject) -> None:
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
    bi = BamletInterface(dut, params, rnd, 0, 0)
    bi.initialize_signals()
    await bi.start()
    
    # Run instruction memory write tests
    await write_instruction_test(bi)
    await write_multiple_instructions_test(bi)


def test_bamlet_write_im(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "Bamlet"
    module = "fmvpu.bamlet_test.test_write_im"
    
    test_params = {
        "seed": seed,
        "params_file": params_file,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_bamlet_write_im(temp_dir: Optional[str] = None, seed: int = 0) -> None:
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
        
        test_bamlet_write_im(concat_filename, config_file, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        assert len(sys.argv) >= 3
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_bamlet_write_im(verilog_file, config_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_bamlet_write_im()