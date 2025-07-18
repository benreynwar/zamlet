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
from fmvpu.lane_array import lane_array_interface
from fmvpu.lane_array.lane_array_interface import LaneArrayInterface
from fmvpu.lane_array.lane_array_params import LaneArrayParams
from fmvpu.lane.instructions import PacketInstruction, PacketModes, HaltInstruction, ALUInstruction, ALUModes
from fmvpu.lane.lane_interface import make_coord_register


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def echo_packet_test(lai: LaneArrayInterface) -> None:

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
    await lai.write_program(program)
    await lai.start_program()
    
    for x in range(1, lai.params.n_columns+1):
        for y in range(1, lai.params.n_rows+1):
            data = [2*x, 2*y]
            await lai.send_data_packet(x, y, data)
            packet = await lai.get_packet(x, y, expected_length=len(data))
            assert packet[1:] == data


async def report_coords_test(lai: LaneArrayInterface) -> None:
    """
    Send a value to each lane with command packets.
    Write a program to return the values.
    Collect all the reponses.
    """

    values = []
    for x in range(1, lai.params.n_columns+1):
        for y in range(1, lai.params.n_rows+1):
            send_to_coords = (x, y)
            value = x << 5 + y
            values.append(value)
            await lai.write_register(x, y, 4, value)

    # Broadcast to all of them to write in register 5.
    await lai.write_register(x, y, 5, 1, is_broadcast=True)
    # Write the destination register (1, 0)
    coord_value = make_coord_register(1, 0, lai.params.lane)
    await lai.write_register(x, y, 6, coord_value, is_broadcast=True)

    program = [
        PacketInstruction(
            mode=PacketModes.SEND,
            location_reg=6,
            send_length_reg=5,
        ),
        ALUInstruction(mode=ALUModes.ADD, src1_reg=0, src2_reg=4, result_reg=0),
        HaltInstruction(),
        ]
    await lai.write_program(program)
    await lai.start_program()
    
    received_values = []
    for i in range(lai.params.n_lanes):
        packet = await lai.get_packet_from_side('n', index=1, channel=0)
        assert len(packet) == 2
        received_values.append(packet[1])
    assert set(received_values) == set(values)



@cocotb.test()
async def lane_test_array(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    test_params = test_utils.read_params()
    seed = test_params['seed']
    with open(test_params['params_file']) as f:
        params = LaneArrayParams.from_dict(json.load(f))

    rnd = Random(seed)
    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    # Create the lane interface
    lai = LaneArrayInterface(dut, params, rnd)
    lai.initialize_signals()
    await lai.start()

    # Run tests
    await echo_packet_test(lai)
    await report_coords_test(lai)


def test_lane_basic(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]

    toplevel = "LaneArray"
    module = "fmvpu.lane_array_test.test_lane_array"

    test_params = {
        "seed": seed,
        "params_file": params_file,
    }

    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_lane_array(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir

        # Find the lane config file
        config_file = os.path.join(
            os.path.dirname(this_dir), "..", "..", "configs", "lane_array_default.json"
        )
        config_file = os.path.abspath(config_file)

        # Generate Lane with lane parameters
        filenames = generate_rtl.generate("LaneArray", working_dir, [config_file])

        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, "lane_array_verilog.sv")
        test_utils.concatenate_sv_files(filenames, concat_filename)

        test_lane_basic(concat_filename, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")

    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        assert len(sys.argv) >= 3
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_lane_basic(verilog_file, config_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_lane_array()
