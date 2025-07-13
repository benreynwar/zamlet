# WARNING: This file was created by Claude Code with negligible human oversight.
# It is not a test that should be trusted.

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
from fmvpu.new_lane.packet_utils import PacketDriver
from fmvpu.new_lane.instructions import PacketHeader, PacketHeaderModes, create_register_write_command
from fmvpu.new_lane.lane_params import LaneParams


logger = logging.getLogger(__name__)


def create_register_write_packet(register: int, value: int, dest_x: int = 0, dest_y: int = 0, params: LaneParams = LaneParams()) -> list[int]:
    """Create a command packet to write a value to a register"""
    header = PacketHeader(
        length=1,  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=PacketHeaderModes.COMMAND
    )
    command_word = create_register_write_command(register, value, params)
    return [header.encode(), command_word]

this_dir = os.path.abspath(os.path.dirname(__file__))


def make_seed(rnd):
    return rnd.getrandbits(32)


@cocotb.test()
async def lane_basic_reset_test(dut: HierarchyObject, seed=0) -> None:
    """Basic test that resets the NewLane module and waits 10 cycles."""
    test_utils.configure_logging_sim('DEBUG')

    rnd = Random(seed)
    
    logger.info("Starting basic NewLane reset test...")
    
    # Test lane position
    LANE_X = 1
    LANE_Y = 2
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    
    # Initialize position inputs
    dut.io_thisX.value = LANE_X
    dut.io_thisY.value = LANE_Y
    
    # Initialize network inputs
    dut.io_ni_0_valid.value = 0
    dut.io_si_0_valid.value = 0
    dut.io_ei_0_valid.value = 0
    dut.io_wi_0_valid.value = 0
    
    # Create packet driver for west input, channel 0
    west_driver = PacketDriver(
        dut=dut,
        seed=make_seed(rnd),
        valid_signal=dut.io_wi_0_valid,
        ready_signal=dut.io_wi_0_ready,
        data_signal=dut.io_wi_0_bits_data,
        isheader_signal=dut.io_wi_0_bits_isHeader
    )
    
    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    
    # Start packet driver after reset
    cocotb.start_soon(west_driver.drive_packets())
    
    # Send a command packet to write register 3 with value 0x0001 (coordinate 0,1)
    coord_packet = create_register_write_packet(register=3, value=0x0001, dest_x=LANE_X, dest_y=LANE_Y)
    west_driver.add_packet(coord_packet)
    
    # Wait 40 cycles for packet processing
    logger.info('About to wait for 40 cycles')
    for cycle in range(40):
        await triggers.RisingEdge(dut.clock)
    logger.info('Done to wait for 40 cycles')
    
    # Probe register 3 to see if value was written
    register_3_value = dut.rff.registers_3_value.value
    logger.info(f"Register 3 value: {register_3_value}")
    
    # Check if the value matches what we wrote
    expected_value = 0x0001
    if register_3_value == expected_value:
        logger.info("Register write successful!")
    else:
        logger.info(f"Register write failed! Expected {expected_value}, got {register_3_value}")
        assert False
    
    logger.info("Basic reset test completed successfully!")


def test_lane_basic(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = 'NewLane'
    module = 'fmvpu.lane_test.test_lane'
    
    test_params = {
        'seed': seed,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_lane_basic(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Find the lane config file
        config_file = os.path.join(os.path.dirname(this_dir), '..', '..', 'configs', 'lane_default.json')
        config_file = os.path.abspath(config_file)
        
        # Generate NewLane with lane parameters
        filenames = generate_rtl.generate('NewLane', working_dir, [config_file])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, 'lane_verilog.sv')
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_lane_basic(concat_filename, seed)


if __name__ == '__main__':
    test_utils.configure_logging_pre_sim('INFO')
    
    if len(sys.argv) >= 2:
        # Called from Bazel with verilog_file
        verilog_file = sys.argv[1]
        test_lane_basic(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_lane_basic()
