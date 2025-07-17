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
from fmvpu.new_lane import lane_interface
from fmvpu.new_lane.lane_interface import LaneInterface, make_coord_register
from fmvpu.new_lane.lane_params import LaneParams
from fmvpu.new_lane.instructions import PacketInstruction, PacketModes, HaltInstruction, ALUInstruction, ALUModes


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def packet_receive_test(li: LaneInterface) -> None:
    """Test RECEIVE packet operation"""
    program = [
        PacketInstruction(
            mode=PacketModes.RECEIVE,
            result_reg=1,  # packet length will be stored here
        ),
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=2,  # packet data
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Send a test packet
    test_data = [5]
    await li.send_packet(test_data)
    
    # Check that packet length was stored correctly
    packet_length = await li.read_register(1)
    assert packet_length == len(test_data), f"Expected packet length {len(test_data)}, got {packet_length}"
    assert test_data[0] == await li.read_register(2)


async def packet_send_test(li: LaneInterface) -> None:
    """Test SEND packet operation"""
    # Use specific destination coordinates
    dest_x, dest_y = 3, 2
    coord_value = make_coord_register(dest_x, dest_y, li.params)
    
    await li.write_register(1, coord_value)  # coordinate/location
    await li.write_register(2, 3)           # send length
    
    program = [
        PacketInstruction(
            mode=PacketModes.SEND,
            location_reg=1,      # coordinate from register 1
            send_length_reg=2,   # length from register 2
        ),
        ALUInstruction(mode=ALUModes.ADDI, src1_reg=0, src2_reg=1, result_reg=0),
        ALUInstruction(mode=ALUModes.ADDI, src1_reg=0, src2_reg=2, result_reg=0),
        ALUInstruction(mode=ALUModes.ADDI, src1_reg=0, src2_reg=3, result_reg=0),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Check that a packet was sent with correct length and destination
    packet = await li.get_packet(dest_x=dest_x, dest_y=dest_y, expected_length=3)
    assert len(packet) == 4, f"Expected packet with 4 elements (header + 3 data), got {len(packet)}"  # header + data
    assert packet[1:] == [1, 2, 3]


async def packet_get_word_test(li: LaneInterface) -> None:
    """Test GET_WORD packet operation"""
    program = [
        # First receive a packet
        PacketInstruction(
            mode=PacketModes.RECEIVE,
            result_reg=7,  # packet length
        ),
        # Get first word
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=1,
        ),
        # Get second word
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=2,
        ),
        # Get third word
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=3,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Send test data (values within 27-bit limit)
    test_data = [0x7ABCCDD, 0x1223344, 0x5667788]
    await li.send_packet(test_data)
    
    # Check that words were extracted correctly
    word1 = await li.read_register(1)
    word2 = await li.read_register(2)
    word3 = await li.read_register(3)
    packet_length = await li.read_register(7)
    
    assert packet_length == len(test_data), f"Expected packet length {len(test_data)}, got {packet_length}"
    assert word1 == test_data[0], f"Expected word1 {test_data[0]:08x}, got {word1:08x}"
    assert word2 == test_data[1], f"Expected word2 {test_data[1]:08x}, got {word2:08x}"
    assert word3 == test_data[2], f"Expected word3 {test_data[2]:08x}, got {word3:08x}"


async def packet_receive_and_forward_test(li: LaneInterface) -> None:
    """Test RECEIVE_AND_FORWARD packet operation"""
    # Use specific destination coordinates for forwarding
    dest_x, dest_y = 2, 3
    coord_value = make_coord_register(dest_x, dest_y, li.params)
    await li.write_register(4, coord_value)  # new coordinate for forwarding
    
    program = [
        PacketInstruction(
            mode=PacketModes.RECEIVE_AND_FORWARD,
            location_reg=4,      # new coordinate
            result_reg=5,        # packet length
        ),
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=6,
        ),
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=7,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Send a test packet (values within 27-bit limit)
    test_data = [0x3579BDF, 0x468ACE0]
    await li.send_packet(test_data, forward=True)
    
    # Check that packet was received
    packet_length = await li.read_register(5)
    assert packet_length == len(test_data), f"Expected packet length {len(test_data)}, got {packet_length}"
    
    # Check that packet was forwarded with new coordinate
    forwarded_packet = await li.get_packet(dest_x=dest_x, dest_y=dest_y, expected_length=len(test_data))
    assert len(forwarded_packet) == len(test_data) + 1, f"Expected forwarded packet length {len(test_data) + 1}, got {len(forwarded_packet)}"
    # Data should be preserved
    assert forwarded_packet[1:] == test_data


async def packet_receive_forward_and_append_test(li: LaneInterface) -> None:
    """Test RECEIVE_FORWARD_AND_APPEND packet operation"""
    # Use specific destination coordinates for forwarding
    dest_x, dest_y = 4, 1
    coord_value = make_coord_register(dest_x, dest_y, li.params)
    await li.write_register(3, coord_value)  # new coordinate
    await li.write_register(2, 3)  # Number to append
    await li.write_register(6, 0x00ADBEEF)  # data to append (27 bits max)
    
    program = [
        PacketInstruction(
            mode=PacketModes.RECEIVE_FORWARD_AND_APPEND,
            location_reg=3,      # new coordinate
            send_length_reg=2,
            result_reg=7,        # packet length
        ),
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=4,
        ),
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=5,
        ),
        ALUInstruction(mode=ALUModes.ADDI, src1_reg=0, src2_reg=1, result_reg=0),
        ALUInstruction(mode=ALUModes.ADDI, src1_reg=0, src2_reg=2, result_reg=0),
        ALUInstruction(mode=ALUModes.ADDI, src1_reg=0, src2_reg=3, result_reg=0),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Send a test packet (values within 27-bit limit)
    test_data = [0x1234567, 0x7ABCDEF]
    await li.send_packet(test_data, forward=True, append_length=3)
    
    # Check that packet was received
    packet_length = await li.read_register(7)
    assert packet_length == len(test_data), f"Expected packet length {len(test_data)}, got {packet_length}"
    
    # Check that packet was forwarded with appended data
    forwarded_packet = await li.get_packet(dest_x=dest_x, dest_y=dest_y, expected_length=len(test_data) + 3)
    assert len(forwarded_packet) == len(test_data) + 4, f"Expected forwarded packet length {len(test_data) + 4}, got {len(forwarded_packet)}"

    assert forwarded_packet[1:] == test_data + [1, 2, 3]


# async def packet_forward_and_append_test(li: LaneInterface) -> None:
#     """Test FORWARD_AND_APPEND packet operation (no receive)"""
#     # Use specific destination coordinates for forwarding
#     dest_x, dest_y = 6, 4
#     coord_value = make_coord_register(dest_x, dest_y, li.params)
#     await li.write_register(2, coord_value)  # new coordinate
#     await li.write_register(1, 0x2222222)  # data to append (27 bits max)
# 
#     program = [
#         # Then forward it with append
#         PacketInstruction(
#             mode=PacketModes.FORWARD_AND_APPEND,
#             location_reg=2,      # new coordinate
#         ),
#         ALUInstruction(mode=ALUModes.ADDI, src1_reg=0, src2_reg=26, result_reg=0),
#         HaltInstruction(),
#     ]
#     await li.write_program(program)
#     await li.start_program()
#     
#     # Send a test packet (values within 27-bit limit)
#     test_data = [0x7AAAAAA, 0x7BBBBBB]
#     await li.send_packet(test_data, forward=True, append_length = 1)
#     
#     # Check that packet was forwarded with appended data
#     forwarded_packet = await li.get_packet(dest_x=dest_x, dest_y=dest_y, expected_length=len(test_data) + 1)
#     assert len(forwarded_packet) == len(test_data) + 2, f"Expected forwarded packet length {len(test_data) + 2}, got {len(forwarded_packet)}"
#     
#     assert forwarded_packet[1:] == test_data + [26]


async def packet_mask_test(li: LaneInterface) -> None:
    """Test packet operation with mask bit set to skip execution"""
    await li.write_register(2, 1)   # mask register (bit 0 = 1 means skip execution)
    await li.write_register(3, 99)  # initial value that should remain unchanged
    
    program = [
        PacketInstruction(
            mode=PacketModes.RECEIVE,
            mask=True,           # Enable mask checking
            result_reg=3,        # Should not be modified due to mask
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Don't send a packet
    
    # Register 3 should remain unchanged due to mask
    final_value = await li.read_register(3)
    assert final_value == 99, f"Expected register 3 unchanged at 99, got {final_value}"


async def packet_mask_execute_test(li: LaneInterface) -> None:
    """Test packet operation with mask bit allowing execution"""
    await li.write_register(2, 0)   # mask register (bit 0 = 0 means execute normally)
    await li.write_register(3, 99)  # initial value that should be changed
    
    program = [
        PacketInstruction(
            mode=PacketModes.RECEIVE,
            mask=True,           # Enable mask checking
            result_reg=3,        # Should be modified since mask allows execution
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Send a packet
    test_data = []
    await li.send_packet(test_data)
    
    # Register 3 should be updated to packet length
    final_value = await li.read_register(3)
    assert final_value == len(test_data), f"Expected register 3 to be {len(test_data)}, got {final_value}"


async def packet_sequence_test(li: LaneInterface) -> None:
    """Test sequence of packet operations"""
    # Use specific destination coordinates for forwarding
    dest_x, dest_y = 5, 0
    coord_value = make_coord_register(dest_x, dest_y, li.params)
    await li.write_register(4, coord_value)  # coordinate for forwarding
    
    program = [
        # Receive first packet
        PacketInstruction(
            mode=PacketModes.RECEIVE,
            result_reg=1,
        ),
        # Get first word from packet
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=5,
        ),
        # Get second word from packet  
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=6,
        ),
        # Send a new packet with the extracted data
        PacketInstruction(
            mode=PacketModes.SEND,
            location_reg=4,      # coordinate
            send_length_reg=1,   # use original packet length
        ),
        ALUInstruction(mode=ALUModes.ADD, src1_reg=0, src2_reg=5, result_reg=0),
        ALUInstruction(mode=ALUModes.ADD, src1_reg=0, src2_reg=6, result_reg=0),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Send test packet (values within 27-bit limit)
    test_data = [0x4444444, 0x5555555]
    await li.send_packet(test_data)
    
    # Verify extracted words
    word1 = await li.read_register(5)
    word2 = await li.read_register(6)
    packet_length = await li.read_register(1)
    
    assert packet_length == len(test_data), f"Expected packet length {len(test_data)}, got {packet_length}"
    assert word1 == test_data[0], f"Expected word1 {test_data[0]:08x}, got {word1:08x}"
    assert word2 == test_data[1], f"Expected word2 {test_data[1]:08x}, got {word2:08x}"
    
    # Verify sent packet
    sent_packet = await li.get_packet(dest_x=dest_x, dest_y=dest_y, expected_length=len(test_data))
    assert sent_packet[1:] == test_data


async def packet_empty_test(li: LaneInterface) -> None:
    """Test packet operations with empty packets"""
    program = [
        PacketInstruction(
            mode=PacketModes.RECEIVE,
            result_reg=1,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Send empty packet
    empty_data = []
    await li.send_packet(empty_data)
    
    # Check that packet length is 0
    packet_length = await li.read_register(1)
    assert packet_length == 0, f"Expected empty packet length 0, got {packet_length}"


@cocotb.test()
async def lane_packet_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    test_params = test_utils.read_params()
    seed = test_params['seed']
    with open(test_params['params_file']) as f:
        params = LaneParams.from_dict(json.load(f))

    rnd = Random(seed)
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())
    
    # Create the lane interface
    li = LaneInterface(dut, params, rnd, 1, 2)
    li.initialize_signals()
    await li.start()
    
    # Run packet tests
    await packet_receive_test(li)
    await packet_send_test(li)
    await packet_get_word_test(li)
    await packet_receive_and_forward_test(li)
    await packet_receive_forward_and_append_test(li)
    # await packet_forward_and_append_test(li)   # Not implemented
    await packet_mask_test(li)
    await packet_mask_execute_test(li)
    await packet_sequence_test(li)
    await packet_empty_test(li)


def test_lane_packet(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "NewLane"
    module = "fmvpu.lane_test.test_lane_packet"
    
    test_params = {
        "seed": seed,
        "params_file": params_file,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_lane_packet(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Find the lane config file
        config_file = os.path.join(
            os.path.dirname(this_dir), "..", "..", "configs", "lane_default.json"
        )
        config_file = os.path.abspath(config_file)
        
        # Generate NewLane with lane parameters
        filenames = generate_rtl.generate("NewLane", working_dir, [config_file])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, "lane_verilog.sv")
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_lane_packet(concat_filename, config_file, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        assert len(sys.argv) >= 3
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_lane_packet(verilog_file, config_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_lane_packet()
