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
from fmvpu.amlet import packet_utils
from fmvpu.amlet.packet_utils import packet_to_str, make_coord_register
from fmvpu.amlet.instruction import VLIWInstruction
from fmvpu.amlet.packet_instruction import PacketInstruction, PacketModes
from fmvpu.amlet.control_instruction import ControlInstruction, ControlModes
from fmvpu.amlet.alu_instruction import ALUInstruction, ALUModes


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def packet_receive_test(bi: BamletInterface) -> None:
    """Test RECEIVE packet operation"""
    program = [
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.RECEIVE,
                result=17,  # D-register 1 (cutoff + 1 = 16 + 1)
            )
        ),
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                result=18,  # D-register 2 (cutoff + 2 = 16 + 2)
            )
        ),
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
        )
    ]
    bi.write_program(program)
    await bi.wait_to_send_packets()
    await bi.start_program()
    
    # Send a test packet
    test_data = [5]
    await bi.send_packet(test_data)
    
    await bi.wait_for_program_to_run()
    
    # Check that packet length was stored correctly
    packet_length = bi.probe_d_register(1)
    assert packet_length == len(test_data), f"Expected packet length {len(test_data)}, got {packet_length}"
    assert test_data[0] == bi.probe_d_register(2)


async def packet_send_test(bi: BamletInterface) -> None:
    """Test SEND packet operation"""
    # Use specific destination coordinates
    dest_x, dest_y = 3, 2
    coord_value = make_coord_register(dest_x, dest_y, bi.params.amlet)
    
    await bi.write_a_register(1, coord_value)  # coordinate/location
    await bi.write_a_register(2, 3)           # send length
    
    program = [
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.SEND,
                target=1,      # coordinate from A-register 1
                length=2,      # length from A-register 2
            )
        ),
        VLIWInstruction(
            alu=ALUInstruction(mode=ALUModes.ADDI, src1=0, src2=1, a_dst=0)
        ),
        VLIWInstruction(
            alu=ALUInstruction(mode=ALUModes.ADDI, src1=0, src2=2, a_dst=0)
        ),
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(mode=ALUModes.ADDI, src1=0, src2=3, a_dst=0)
        ),
    ]
    bi.write_program(program)
    await bi.wait_to_send_packets()
    await bi.start_program()
    
    await bi.wait_for_program_to_run()
    
    # Check that a packet was sent with correct length and destination
    packet = await bi.get_packet(dest_x=dest_x, dest_y=dest_y, expected_length=3)
    assert len(packet) == 4, f"Expected packet with 4 elements (header + 3 data), got {len(packet)}"  # header + data
    assert packet[1:] == [1, 2, 3]


async def packet_get_word_test(bi: BamletInterface) -> None:
    """Test GET_WORD packet operation"""
    program = [
        # First receive a packet
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.RECEIVE,
                result=23,  # D-register 7 (cutoff + 7 = 16 + 7)
            )
        ),
        # Get first word
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                result=17,  # D-register 1
            )
        ),
        # Get second word
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                result=18,  # D-register 2
            )
        ),
        # Get third word
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                result=19,  # D-register 3
            )
        ),
    ]
    bi.write_program(program)
    await bi.wait_to_send_packets()
    await bi.start_program()
    
    # Send test data (values within 27-bit limit)
    test_data = [0x7ABCCDD, 0x1223344, 0x5667788]
    await bi.send_packet(test_data)
    
    await bi.wait_for_program_to_run()
    
    # Check that words were extracted correctly
    word1 = bi.probe_d_register(1)
    word2 = bi.probe_d_register(2)
    word3 = bi.probe_d_register(3)
    packet_length = bi.probe_d_register(7)
    
    assert packet_length == len(test_data), f"Expected packet length {len(test_data)}, got {packet_length}"
    assert word1 == test_data[0], f"Expected word1 {test_data[0]:08x}, got {word1:08x}"
    assert word2 == test_data[1], f"Expected word2 {test_data[1]:08x}, got {word2:08x}"
    assert word3 == test_data[2], f"Expected word3 {test_data[2]:08x}, got {word3:08x}"


async def packet_receive_and_forward_test(bi: BamletInterface) -> None:
    """Test RECEIVE_AND_FORWARD packet operation"""
    # Use specific destination coordinates for forwarding
    dest_x, dest_y = 2, 3
    coord_value = make_coord_register(dest_x, dest_y, bi.params.amlet)
    await bi.write_a_register(4, coord_value)  # new coordinate for forwarding
    
    program = [
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.RECEIVE_AND_FORWARD,
                target=4,      # new coordinate
                result=21,     # D-register 5 (cutoff + 5 = 16 + 5)
            )
        ),
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                result=22,     # D-register 6
            )
        ),
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                result=23,     # D-register 7
            )
        ),
    ]
    bi.write_program(program)
    await bi.wait_to_send_packets()
    await bi.start_program()
    
    # Send a test packet (values within 27-bit limit)
    test_data = [0x3579BDF, 0x468ACE0]
    await bi.send_packet(test_data, forward=True)
    
    await bi.wait_for_program_to_run()
    
    # Check that packet was received
    packet_length = bi.probe_d_register(5)
    assert packet_length == len(test_data), f"Expected packet length {len(test_data)}, got {packet_length}"
    
    # Check that packet was forwarded with new coordinate
    forwarded_packet = await bi.get_packet(dest_x=dest_x, dest_y=dest_y, expected_length=len(test_data))
    assert len(forwarded_packet) == len(test_data) + 1, f"Expected forwarded packet length {len(test_data) + 1}, got {len(forwarded_packet)}"
    # Data should be preserved
    assert forwarded_packet[1:] == test_data


async def packet_receive_forward_and_append_test(bi: BamletInterface) -> None:
    """Test RECEIVE_FORWARD_AND_APPEND packet operation"""
    # Use specific destination coordinates for forwarding
    dest_x, dest_y = 4, 1
    coord_value = make_coord_register(dest_x, dest_y, bi.params.amlet)
    await bi.write_a_register(3, coord_value)  # new coordinate
    await bi.write_a_register(2, 3)  # Number to append
    await bi.write_d_register(6, 0x00ADBEEF)  # data to append (27 bits max)
    
    program = [
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.RECEIVE_FORWARD_AND_APPEND,
                target=3,      # new coordinate
                length=2,
                result=23,     # D-register 7 (cutoff + 7 = 16 + 7)
            )
        ),
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                result=20,     # D-register 4
            )
        ),
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                result=21,     # D-register 5
            )
        ),
        VLIWInstruction(
            alu=ALUInstruction(mode=ALUModes.ADDI, src1=0, src2=1, a_dst=0)
        ),
        VLIWInstruction(
            alu=ALUInstruction(mode=ALUModes.ADDI, src1=0, src2=2, a_dst=0)
        ),
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(mode=ALUModes.ADDI, src1=0, src2=3, a_dst=0)
        ),
    ]
    bi.write_program(program)
    await bi.wait_to_send_packets()
    await bi.start_program()
    
    # Send a test packet (values within 27-bit limit)  
    test_data = [0x1234567, 0x7ABCDEF]
    await bi.send_packet(test_data, forward=True, append_length=3)
    
    await bi.wait_for_program_to_run()
    
    # Check that packet was received
    packet_length = bi.probe_d_register(7)
    assert packet_length == len(test_data), f"Expected packet length {len(test_data)}, got {packet_length}"
    
    # Check that packet was forwarded with appended data
    forwarded_packet = await bi.get_packet(dest_x=dest_x, dest_y=dest_y, expected_length=len(test_data) + 3)
    assert len(forwarded_packet) == len(test_data) + 4, f"Expected forwarded packet length {len(test_data) + 4}, got {len(forwarded_packet)}"

    assert forwarded_packet[1:] == test_data + [1, 2, 3]


async def packet_empty_test(bi: BamletInterface) -> None:
    """Test packet operations with empty packets"""
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            packet=PacketInstruction(
                mode=PacketModes.RECEIVE,
                result=17,  # D-register 1
            )
        ),
    ]
    bi.write_program(program)
    await bi.wait_to_send_packets()
    await bi.start_program()
    
    # Send empty packet
    empty_data = []
    await bi.send_packet(empty_data)
    
    await bi.wait_for_program_to_run()
    
    # Check that packet length is 0
    packet_length = bi.probe_d_register(1)
    assert packet_length == 0, f"Expected empty packet length 0, got {packet_length}"


async def broadcast_test(bi: BamletInterface) -> None:
    """Test broadcasting a command packet"""
    # We'll write to register 2
    # We'll target a location south-east of the bamlet
    # The packet should come out the south and east sides.
    reg = 2
    value = 45
    # Destination must be outside the bamlet grid to the south-east
    dest_x = bi.bamlet_x + bi.params.n_amlet_columns
    dest_y = bi.bamlet_y + bi.params.n_amlet_rows
    write_packet = packet_utils.create_d_register_write_packet(
        register=reg, value=value, dest_x=dest_x, dest_y=dest_y,
        params=bi.params.amlet, is_broadcast=True,
    )
    logger.info(f'write packet is {packet_to_str(write_packet)}')
    bi.drivers[('w', 0, 0)].add_packet(write_packet)
    east_packet = await bi.get_packet_from_side('e', 0, 0)
    south_packet = await bi.get_packet_from_side('s', 0, 0)
    
    logger.info(f'east packet is {packet_to_str(east_packet)}')
    logger.info(f'south packet is {packet_to_str(south_packet)}')
    
    assert east_packet == write_packet, f'East packet mismatch: {packet_to_str(east_packet)} != {packet_to_str(write_packet)}'
    assert south_packet[1:] == write_packet[1:], f'South packet mismatch: {packet_to_str(south_packet)} != {packet_to_str(write_packet)}'
    
    probed_value = bi.probe_d_register(reg)
    assert probed_value == value, f"Register value mismatch: expected {value}, got {probed_value}"


@cocotb.test()
async def bamlet_packet_test(dut: HierarchyObject) -> None:
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
    bi = BamletInterface(dut, params, rnd, 1, 2)
    bi.initialize_signals()
    await bi.start()
    
    # Run packet tests
    await packet_receive_test(bi)
    await packet_send_test(bi)
    await packet_get_word_test(bi)
    await packet_receive_and_forward_test(bi)
    await packet_receive_forward_and_append_test(bi)
    await packet_empty_test(bi)
    await broadcast_test(bi)


def test_bamlet_packet(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "Bamlet"
    module = "fmvpu.bamlet_test.test_packet"
    
    test_params = {
        "seed": seed,
        "params_file": params_file,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_bamlet_packet(temp_dir: Optional[str] = None, seed: int = 0) -> None:
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
        
        test_bamlet_packet(concat_filename, config_file, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        assert len(sys.argv) >= 3
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_bamlet_packet(verilog_file, config_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_bamlet_packet()
