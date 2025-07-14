import os
import sys
import tempfile
from typing import Optional
import logging
from random import Random

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from fmvpu import generate_rtl
from fmvpu import test_utils
from fmvpu.new_lane import lane_interface
from fmvpu.new_lane.lane_interface import LaneInterface
from fmvpu.new_lane.instructions import PacketInstruction, PacketModes, HaltInstruction, ALUInstruction, ALUModes


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def send_zero_length_packet_test(li: LaneInterface) -> None:
    """Sends a packet with zero length"""
    coord_word = lane_interface.make_coord_register(x=0, y=1)
    await li.write_register(3, coord_word)

    # Create packet send instruction: send from location=reg3, value=reg5, result=reg0
    program = [
        PacketInstruction(
            mode=PacketModes.SEND,
            mask=False,  # 0
            location_reg=3,  # coordinate
            send_length_reg=0,  # 0 length
            result_reg=0,  # No result used
        ),
        HaltInstruction()
        ]
    await li.write_program(program)
    await li.start_program()
    # Wait for program execution and monitor outputs
    await li.get_packet(dest_x=0, dest_y=1, expected_length=0)


async def echo_packet_test(li: LaneInterface) -> None:

    # Create packet send instruction: send from location=reg3, value=reg5, result=reg0
    program = [
        PacketInstruction(
            mode=PacketModes.RECEIVE,
            result_reg=5,  # It will put the length here
        ),
        PacketInstruction(
            mode=PacketModes.SEND,
            location_reg=0,  # coordinate
            send_length_reg=5,  # Same length as packet received
        ),
        # We're assuming that the packet has length 2 here
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=0,  # It will put the received packet in the send packet
        ),
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=0,  # It will put the received packet in the send packet
        ),
        HaltInstruction(),
        ]
    await li.write_program(program)
    await li.start_program()
    
    data = [1, 2]
    await li.send_packet(data)
    packet = await li.get_packet(expected_length=len(data))
    assert packet[1:] == data


async def add_two_numbers_test(li: LaneInterface) -> None:

    # Create packet send instruction: send from location=reg3, value=reg5, result=reg0
    program = [
        PacketInstruction(
            mode=PacketModes.RECEIVE,
            result_reg=5,  # It will put the length here
        ),
        PacketInstruction(
            mode=PacketModes.SEND,
            location_reg=0,  # coordinate
            send_length_reg=5,  # Same length as packet received
        ),
        # We're assuming that the packet has length 2 here
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=1,
        ),
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=2,
        ),
        ALUInstruction(
            mode=ALUModes.ADD,
            src1_reg=1,
            src2_reg=2,
            result_reg=0,
        ),
        ALUInstruction(
            mode=ALUModes.MULT,
            src1_reg=1,
            src2_reg=2,
            result_reg=0,
        ),
        HaltInstruction(),
        ]
    await li.write_program(program)
    await li.start_program()
    
    data = [10, 8]
    await li.send_packet(data)
    packet = await li.get_packet(expected_length=2)
    assert packet[1:] == [data[0] + data[1], data[0] * data[1]]


async def check_dependency_test(li: LaneInterface) -> None:

    # Create packet send instruction: send from location=reg3, value=reg5, result=reg0
    program = [
        PacketInstruction(
            mode=PacketModes.RECEIVE,
            result_reg=5,  # It will put the length here
        ),
        PacketInstruction(
            mode=PacketModes.SEND,
            location_reg=0,  # coordinate
            send_length_reg=5,  # Same length as packet received
        ),
        # We're assuming that the packet has length 2 here
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=1,
        ),
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=2,
        ),
        # Add reg1 and reg2 together and put in reg4
        ALUInstruction(
            mode=ALUModes.ADD,
            src1_reg=1,
            src2_reg=2,
            result_reg=4,
        ),
        # Add reg2 onto  reg4 and put in reg5
        ALUInstruction(
            mode=ALUModes.ADD,
            src1_reg=4,
            src2_reg=2,
            result_reg=5,
        ),
        # Output the results of reg4 and reg5
        ALUInstruction(
            mode=ALUModes.ADD,
            src1_reg=4,
            src2_reg=0,
            result_reg=0,
        ),
        ALUInstruction(
            mode=ALUModes.ADD,
            src1_reg=5,
            src2_reg=0,
            result_reg=0,
        ),
        HaltInstruction(),
        ]
    await li.write_program(program)
    await li.start_program()
    
    data = [10, 8]
    await li.send_packet(data)
    packet = await li.get_packet(expected_length=2)
    assert packet[1:] == [data[0] + data[1], data[0] + 2*data[1]]


@cocotb.test()
async def lane_test(dut: HierarchyObject, seed=0) -> None:
    test_utils.configure_logging_sim("DEBUG")
    rnd = Random(seed)
    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    # Create the lane interface
    li = LaneInterface(dut, rnd, 1, 2)
    li.initialize_signals()
    await li.start()

    # Run tests
    await send_zero_length_packet_test(li)
    await echo_packet_test(li)
    await add_two_numbers_test(li)
    await check_dependency_test(li)


def test_lane_basic(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]

    toplevel = "NewLane"
    module = "fmvpu.lane_test.test_lane"

    test_params = {
        "seed": seed,
    }

    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_lane_basic(temp_dir: Optional[str] = None, seed: int = 0) -> None:
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

        test_lane_basic(concat_filename, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")

    if len(sys.argv) >= 2:
        # Called from Bazel with verilog_file
        verilog_file = sys.argv[1]
        test_lane_basic(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_lane_basic()
