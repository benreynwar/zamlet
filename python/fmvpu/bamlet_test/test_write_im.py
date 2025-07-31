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
from fmvpu.amlet.control_instruction import ControlInstruction, ControlModes
from fmvpu.amlet.packet_instruction import PacketInstruction, PacketModes
from fmvpu.amlet.alu_instruction import ALUInstruction, ALUModes
from fmvpu.amlet.alu_lite_instruction import ALULiteInstruction, ALULiteModes
from fmvpu.amlet.ldst_instruction import LoadStoreInstruction, LoadStoreModes
from fmvpu.amlet.predicate_instruction import PredicateInstruction, PredicateModes, Src1Mode
from fmvpu.amlet import packet_utils


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def write_instruction_test(bi: BamletInterface) -> None:
    """Test writing a complex instruction to instruction memory and probe the output"""
    # Create a complex VLIW instruction that exercises all execution units
    complex_instr = VLIWInstruction(
        control=ControlInstruction(
            mode=ControlModes.LOOP_IMMEDIATE,
            iterations_value=10,
            dst=1,
            predicate=0,
            length=5
        ),
        predicate=PredicateInstruction(
            mode=PredicateModes.EQ,
            src1_mode=Src1Mode.IMMEDIATE,
            src1_value=42,  # Compare immediate value 42
            src2=3,  # A-register 3
            base=1,  # P-register 1 (base predicate)
            not_base=False,
            dst=2    # P-register 2 (destination)
        ),
        alu=ALUInstruction(
            mode=ALUModes.ADD,
            src1=1,  # D-register 1
            src2=2,  # D-register 2  
            dst=19   # D-register 3 (encoded as cutoff+3 = 16+3 = 19)
        ),
        alu_lite=ALULiteInstruction(
            mode=ALULiteModes.ADD,
            src1=1,  # A-register 1
            src2=2,  # A-register 2
            dst=4    # A-register 4 (encoded as 4)
        ),
        load_store=LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            addr=5,  # A-register 5 (address)
            reg=22   # D-register 6 (encoded as cutoff+6 = 16+6 = 22)
        ),
        packet=PacketInstruction(
            mode=PacketModes.SEND,
            target=7,   # A-register 7 (target coordinates)
            length=8,   # A-register 8 (length)
            d_dst=9,  # D-register 9 (will be encoded as cutoff+9 = 16+9 = 25)
            channel=1
        )
    )

    # Calculate expected widths from Python
    control_width_py = complex_instr.control.get_width(bi.params.amlet)
    alu_width_py = complex_instr.alu.get_width(bi.params.amlet)
    alu_lite_width_py = complex_instr.alu_lite.get_width(bi.params.amlet)
    load_store_width_py = complex_instr.load_store.get_width(bi.params.amlet)
    packet_width_py = complex_instr.packet.get_width(bi.params.amlet)
    predicate_width_py = complex_instr.predicate.get_width(bi.params.amlet)
    total_width_py = control_width_py + alu_width_py + alu_lite_width_py + load_store_width_py + packet_width_py + predicate_width_py
    
    logger.info("Python calculated VLIW instruction component widths:")
    logger.info(f"  Control: {control_width_py} bits")
    logger.info(f"  ALU: {alu_width_py} bits")
    logger.info(f"  ALU Lite: {alu_lite_width_py} bits")
    logger.info(f"  Load/Store: {load_store_width_py} bits")
    logger.info(f"  Packet: {packet_width_py} bits")
    logger.info(f"  Predicate: {predicate_width_py} bits")
    logger.info(f"  Total VLIW width: {total_width_py} bits")
    
    # We'll compare this to simulation widths after we fetch the instruction
    
    # Write the instruction to address 0
    program = [complex_instr]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    
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
            control_mode = bi.dut.control.io_instr_bits_control_mode.value
            
            # ALU instruction  
            alu_mode = bi.dut.control.io_instr_bits_alu_mode.value
            alu_src1 = bi.dut.control.io_instr_bits_alu_src1.value
            alu_src2 = bi.dut.control.io_instr_bits_alu_src2.value
            alu_dst = bi.dut.control.io_instr_bits_alu_dst.value
            
            # ALU Lite instruction
            alu_lite_mode = bi.dut.control.io_instr_bits_aluLite_mode.value
            alu_lite_src1 = bi.dut.control.io_instr_bits_aluLite_src1.value
            alu_lite_src2 = bi.dut.control.io_instr_bits_aluLite_src2.value
            alu_lite_dst = bi.dut.control.io_instr_bits_aluLite_dst.value
            
            # Load/Store instruction
            ldst_mode = bi.dut.control.io_instr_bits_loadStore_mode.value
            ldst_addr = bi.dut.control.io_instr_bits_loadStore_addr.value
            ldst_reg = bi.dut.control.io_instr_bits_loadStore_reg.value
            
            # Packet instruction
            packet_mode = bi.dut.control.io_instr_bits_packet_mode.value
            packet_target = bi.dut.control.io_instr_bits_packet_target.value
            packet_length = bi.dut.control.io_instr_bits_packet_length.value
            packet_result = bi.dut.control.io_instr_bits_packet_result.value
            packet_channel = bi.dut.control.io_instr_bits_packet_channel.value
            
            # Predicate instruction
            predicate_mode = bi.dut.control.io_instr_bits_predicate_mode.value
            predicate_src2 = bi.dut.control.io_instr_bits_predicate_src2.value
            predicate_base = bi.dut.control.io_instr_bits_predicate_base.value
            predicate_not_base = bi.dut.control.io_instr_bits_predicate_notBase.value
            predicate_dst = bi.dut.control.io_instr_bits_predicate_dst.value
            
            logger.info(f"Complex instruction components:")
            logger.info(f"  Control: mode={control_mode}")
            logger.info(f"  Predicate: mode={predicate_mode}, src2={predicate_src2}, base={predicate_base}, not_base={predicate_not_base}, dst={predicate_dst}")
            logger.info(f"  ALU: mode={alu_mode}, src1={alu_src1}, src2={alu_src2}, dst={alu_dst}")
            logger.info(f"  ALULite: mode={alu_lite_mode}, src1={alu_lite_src1}, src2={alu_lite_src2}, dst={alu_lite_dst}")
            logger.info(f"  LoadStore: mode={ldst_mode}, addr={ldst_addr}, reg={ldst_reg}")
            logger.info(f"  Packet: mode={packet_mode}, target={packet_target}, length={packet_length}, result={packet_result}, channel={packet_channel}")
            
            # Compare Python calculated widths vs simulation signal widths using find_signals_by_prefix
            control_signals = test_utils.find_signals_by_prefix(bi.dut.control, "io_imResp_bits_instr_control_")
            alu_signals = test_utils.find_signals_by_prefix(bi.dut.control, "io_imResp_bits_instr_alu_")
            alu_lite_signals = test_utils.find_signals_by_prefix(bi.dut.control, "io_imResp_bits_instr_aluLite_")
            load_store_signals = test_utils.find_signals_by_prefix(bi.dut.control, "io_imResp_bits_instr_loadStore_")
            packet_signals = test_utils.find_signals_by_prefix(bi.dut.control, "io_imResp_bits_instr_packet_")
            predicate_signals = test_utils.find_signals_by_prefix(bi.dut.control, "io_imResp_bits_instr_predicate_")
            
            logger.info(f"Control signals found: {list(control_signals.keys())}")
            logger.info(f"ALU signals found: {list(alu_signals.keys())}")
            logger.info(f"ALU Lite signals found: {list(alu_lite_signals.keys())}")
            logger.info(f"Load/Store signals found: {list(load_store_signals.keys())}")
            logger.info(f"Packet signals found: {list(packet_signals.keys())}")
            logger.info(f"Predicate signals found: {list(predicate_signals.keys())}")
            
            # Calculate total widths by summing individual signal widths
            control_width_sim = sum(len(signal) for signal in control_signals.values())
            alu_width_sim = sum(len(signal) for signal in alu_signals.values())
            alu_lite_width_sim = sum(len(signal) for signal in alu_lite_signals.values())
            load_store_width_sim = sum(len(signal) for signal in load_store_signals.values())
            packet_width_sim = sum(len(signal) for signal in packet_signals.values())
            predicate_width_sim = sum(len(signal) for signal in predicate_signals.values())
            
            logger.info("\nWidth comparison (Python vs Simulation):")
            logger.info(f"  Control: {control_width_py} vs {control_width_sim}")
            logger.info(f"  ALU: {alu_width_py} vs {alu_width_sim}")
            logger.info(f"  ALU Lite: {alu_lite_width_py} vs {alu_lite_width_sim}")
            logger.info(f"  Load/Store: {load_store_width_py} vs {load_store_width_sim}")
            logger.info(f"  Packet: {packet_width_py} vs {packet_width_sim}")
            logger.info(f"  Predicate: {predicate_width_py} vs {predicate_width_sim}")
            
            # Test failures if widths don't match
            assert control_width_py == control_width_sim, f"Control width mismatch: Python={control_width_py}, Sim={control_width_sim}"
            assert alu_width_py == alu_width_sim, f"ALU width mismatch: Python={alu_width_py}, Sim={alu_width_sim}"
            assert alu_lite_width_py == alu_lite_width_sim, f"ALU Lite width mismatch: Python={alu_lite_width_py}, Sim={alu_lite_width_sim}"
            assert load_store_width_py == load_store_width_sim, f"Load/Store width mismatch: Python={load_store_width_py}, Sim={load_store_width_sim}"
            assert packet_width_py == packet_width_sim, f"Packet width mismatch: Python={packet_width_py}, Sim={packet_width_sim}"
            assert predicate_width_py == predicate_width_sim, f"Predicate width mismatch: Python={predicate_width_py}, Sim={predicate_width_sim}"
            
            logger.info("✓ All VLIW component widths match between Python and simulation!")
            
            # Verify this matches our expected complex instruction
            assert control_mode == ControlModes.LOOP_IMMEDIATE, f"Expected control mode={ControlModes.LOOP_IMMEDIATE}, got {control_mode}"
            assert alu_mode == ALUModes.ADD, f"Expected ALU mode={ALUModes.ADD}, got {alu_mode}"
            assert alu_src1 == 1, f"Expected ALU src1=1, got {alu_src1}"
            assert alu_src2 == 2, f"Expected ALU src2=2, got {alu_src2}"
            # ALU dst should be 19 (D-register 3 encoded as cutoff+3 = 16+3 = 19)
            assert alu_dst == 19, f"Expected ALU dst=19, got {alu_dst}"
            
            assert alu_lite_mode == ALULiteModes.ADD, f"Expected ALULite mode={ALULiteModes.ADD}, got {alu_lite_mode}"
            assert alu_lite_src1 == 1, f"Expected ALULite src1=1, got {alu_lite_src1}"
            assert alu_lite_src2 == 2, f"Expected ALULite src2=2, got {alu_lite_src2}"
            assert alu_lite_dst == 4, f"Expected ALULite dst=4, got {alu_lite_dst}"  # A-register 4
            
            assert ldst_mode == LoadStoreModes.LOAD, f"Expected LoadStore mode={LoadStoreModes.LOAD}, got {ldst_mode}"
            assert ldst_addr == 5, f"Expected LoadStore addr=5, got {ldst_addr}"  # A-register 5
            assert ldst_reg == 22, f"Expected LoadStore reg=22, got {ldst_reg}"  # D-register 6 (encoded as 16+6=22)
            
            assert packet_mode == PacketModes.SEND, f"Expected Packet mode={PacketModes.SEND}, got {packet_mode}"
            assert packet_target == 7, f"Expected Packet target=7, got {packet_target}"  # A-register 7
            assert packet_length == 8, f"Expected Packet length=8, got {packet_length}"  # A-register 8
            assert packet_result == 25, f"Expected Packet result=25, got {packet_result}"  # D-register 9 (encoded as 16+9=25)
            assert packet_channel == 1, f"Expected Packet channel=1, got {packet_channel}"
            
            assert predicate_mode == PredicateModes.EQ, f"Expected Predicate mode={PredicateModes.EQ}, got {predicate_mode}"
            assert predicate_src2 == 3, f"Expected Predicate src2=3, got {predicate_src2}"  # A-register 3
            assert predicate_base == 1, f"Expected Predicate base=1, got {predicate_base}"  # P-register 1
            assert predicate_not_base == 0, f"Expected Predicate not_base=0, got {predicate_not_base}"  # False = 0
            assert predicate_dst == 2, f"Expected Predicate dst=2, got {predicate_dst}"  # P-register 2
            
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


async def send_zero_length_packet_test(bi: BamletInterface) -> None:
    """Sends a packet with zero length using a proper VLIW program"""
    # Create destination coordinates: bamlet_x + 0, bamlet_y + 1
    dest_x = 0
    dest_y = 0
    coord_word = packet_utils.make_coord_register(dest_x, dest_y, bi.params.amlet)
    await bi.write_a_register(3, coord_word)
    
    # Write zero length to register 4
    await bi.write_a_register(4, 0)
    
    # Create a single VLIW instruction that sends a zero-length packet and halts
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            packet=PacketInstruction(
                mode=PacketModes.SEND,
                target=3,  # Contains destination coordinates
                length=4,  # Contains length (0) 
                a_dst=0   # Store result/status here
            )
        )
    ]
    
    # Write and run the program
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    
    # Wait for program execution and monitor outputs
    await bi.get_packet(expected_length=0)
    
    logger.info("Successfully sent zero-length packet program")



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
    
    # # Run simple packet test
    # await simple_packet_test(bi)

    # await send_zero_length_packet_test(bi)

    # # This one must be the last test.
    # # It leaves packets hanging
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
