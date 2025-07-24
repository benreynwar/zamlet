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
from fmvpu.amlet import packet_utils


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
    for _ in range(10):
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


async def simple_packet_test(bi: BamletInterface) -> None:
    """Test sending a command packet to write instruction 0 to IM address 0"""
    # Create a command packet to write instruction 0 to address 0 of IM
    halt_instruction = create_halt_instruction()
    instructions = [halt_instruction]
    packet = packet_utils.create_instruction_write_packet(
        instructions=instructions,
        base_address=0,  # Write to address 0
        dest_x=1,  # bamlet_x(1) + offset_x(0)
        dest_y=1,  # bamlet_y(1) + offset_y(0)
        params=bi.params.amlet
    )
    
    # Send the packet manually using packet driver
    bi.drivers[('w', 0, 0)].add_packet(packet)
    
    logger.info(f"Sent IM write command packet with dest=(1,1) to west side")
    
    # Calculate expected header for verification - should match create_instruction_write_packet
    # which creates: 1 setup command + len(instruction_words) data words
    instruction_words = []
    for instruction in instructions:
        words = instruction.to_words(bi.params.amlet)
        padded_words = packet_utils.pad_words_to_power_of_2(words)
        instruction_words.extend(padded_words)
    
    expected_header = packet_utils.PacketHeader(
        length=1 + len(instruction_words),  # 1 setup command + instruction words
        dest_x=1,  # bamlet_x(1) + offset_x(0) 
        dest_y=1,  # bamlet_y(1) + offset_y(0)
        mode=packet_utils.PacketHeaderModes.COMMAND,
        forward=False,
        append_length=0
    )
    expected_header_value = expected_header.encode()
    logger.info(f"Expected header value: 0x{expected_header_value:08x}")
    
    # Monitor the buffered input handler for the received packet
    logger.info("Checking packet in networkNode.switches_0.inHandlers_3...")
    
    packet_found = False
    for cycle in range(10):
        await triggers.RisingEdge(bi.dut.clock)
        
        # Check buffered_valid signal
        buffered_valid = bi.dut.Amlet.networkNode.switches_0.inHandlers_3.buffered_valid.value
        if buffered_valid == 1:
            # Check if this is a header word
            is_header = int(bi.dut.Amlet.networkNode.switches_0.inHandlers_3.buffered_bits_isHeader.value)
            if is_header == 1:
                logger.info("Found valid buffered header!")
                
                # Read header components
                header_y_dest = int(bi.dut.Amlet.networkNode.switches_0.inHandlers_3.bufferedHeader_yDest.value)
                header_x_dest = int(bi.dut.Amlet.networkNode.switches_0.inHandlers_3.bufferedHeader_xDest.value)
                header_length = int(bi.dut.Amlet.networkNode.switches_0.inHandlers_3.bufferedHeader_length.value)
                
                # Get the raw header word for comparison
                raw_header = int(bi.dut.Amlet.networkNode.switches_0.inHandlers_3.buffered_bits_data.value)
                logger.info(f"Raw header word: 0x{raw_header:08x}")
                logger.info(f"Expected header: 0x{expected_header_value:08x}")
                
                # Decode our expected header for comparison
                decoded_expected = packet_utils.PacketHeader.from_word(expected_header_value)
                logger.info(f"Expected decoded: {decoded_expected}")
                
                logger.info(f"Received header components:")
                logger.info(f"  dest_x: {header_x_dest}, dest_y: {header_y_dest}")
                logger.info(f"  length: {header_length}")
                
                # Verify components match expected values
                expected_length = 1 + len(instruction_words)
                if header_x_dest == 1 and header_y_dest == 1 and header_length == expected_length:
                    logger.info("✓ Packet header verification successful!")
                    packet_found = True
                    logger.info(f"Expected command packet with {len(instruction_words)} instruction words + 1 setup command = {expected_length} total")
                    break
                else:
                    logger.error(f"Header mismatch! Expected x=1,y=1,len={expected_length}, got x={header_x_dest},y={header_y_dest},len={header_length}")
                    logger.error("This suggests a bit-packing mismatch between Python and Verilog")
                    assert False, f"Packet header verification failed: expected (x=1,y=1,len={expected_length}), got (x={header_x_dest},y={header_y_dest},len={header_length})"
            else:
                logger.debug(f"Valid buffered data but not a header (isHeader={is_header})")
    
    if not packet_found:
        logger.error("No valid packet found in buffered input handler")
        assert False, "Packet header verification failed: no valid packet found"
        
    logger.info("Packet verification complete")


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
    bi = BamletInterface(dut, params, rnd, 1, 1)
    bi.initialize_signals()
    await bi.start()
    
    # Run simple packet test
    await simple_packet_test(bi)

    await write_instruction_test(bi)


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
