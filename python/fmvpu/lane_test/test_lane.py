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
from fmvpu.new_lane import packet_utils
from fmvpu.new_lane.instructions import PacketInstruction, PacketModes, HaltInstruction
from fmvpu.new_lane.lane_params import LaneParams


logger = logging.getLogger(__name__)


def create_register_write_packet(register: int, value: int, dest_x: int = 0, dest_y: int = 0, params: LaneParams = LaneParams()) -> list[int]:
    """Create a command packet to write a value to a register"""
    header = packet_utils.PacketHeader(
        length=1,  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND
    )
    command_word = packet_utils.create_register_write_command(register, value, params)
    return [header.encode(), command_word]


def create_instruction_write_packet(instructions: list[int], base_address: int = 0, dest_x: int = 0, dest_y: int = 0, params: LaneParams = LaneParams()) -> list[int]:
    """Create a command packet to write multiple instructions to instruction memory"""
    header = packet_utils.PacketHeader(
        length=len(instructions),  # One command word per instruction
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND
    )
    command_words = []
    for i, instruction in enumerate(instructions):
        address = base_address + i
        command_word = packet_utils.create_instruction_memory_write_command(address, instruction, params)
        command_words.append(command_word)
    return [header.encode()] + command_words


def create_start_packet(pc: int, dest_x: int = 0, dest_y: int = 0, params: LaneParams = LaneParams()) -> list[int]:
    """Create a command packet to start execution at a given PC"""
    header = packet_utils.PacketHeader(
        length=1,  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND
    )
    command_word = packet_utils.create_start_command(pc, params)
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
    west_driver = packet_utils.PacketDriver(
        dut=dut,
        seed=make_seed(rnd),
        valid_signal=dut.io_wi_0_valid,
        ready_signal=dut.io_wi_0_ready,
        data_signal=dut.io_wi_0_bits_data,
        isheader_signal=dut.io_wi_0_bits_isHeader
    )
    
    # Create packet receivers for all outputs to monitor packets
    north_receiver = packet_utils.PacketReceiver(
        dut=dut,
        seed=make_seed(rnd),
        valid_signal=dut.io_no_0_valid,
        ready_signal=dut.io_no_0_ready,
        data_signal=dut.io_no_0_bits_data,
        isheader_signal=dut.io_no_0_bits_isHeader,
        name="north"
    )
    
    south_receiver = packet_utils.PacketReceiver(
        dut=dut,
        seed=make_seed(rnd),
        valid_signal=dut.io_so_0_valid,
        ready_signal=dut.io_so_0_ready,
        data_signal=dut.io_so_0_bits_data,
        isheader_signal=dut.io_so_0_bits_isHeader,
        name="south"
    )
    
    east_receiver = packet_utils.PacketReceiver(
        dut=dut,
        seed=make_seed(rnd),
        valid_signal=dut.io_eo_0_valid,
        ready_signal=dut.io_eo_0_ready,
        data_signal=dut.io_eo_0_bits_data,
        isheader_signal=dut.io_eo_0_bits_isHeader,
        name="east"
    )
    
    west_receiver = packet_utils.PacketReceiver(
        dut=dut,
        seed=make_seed(rnd),
        valid_signal=dut.io_wo_0_valid,
        ready_signal=dut.io_wo_0_ready,
        data_signal=dut.io_wo_0_bits_data,
        isheader_signal=dut.io_wo_0_bits_isHeader,
        name="west"
    )
    
    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    
    # Start packet driver and receivers after reset
    cocotb.start_soon(west_driver.drive_packets())
    cocotb.start_soon(north_receiver.receive_packets())
    cocotb.start_soon(south_receiver.receive_packets())
    cocotb.start_soon(east_receiver.receive_packets())
    cocotb.start_soon(west_receiver.receive_packets())
    
    # Send a command packet to write register 3 with coordinate (0,1)
    # Coordinate encoding: (y << 5) | x = (1 << 5) | 0 = 32 = 0x0020
    coord_packet = create_register_write_packet(register=3, value=0x0020, dest_x=LANE_X, dest_y=LANE_Y)
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
    expected_value = 0x0020
    if register_3_value == expected_value:
        logger.info("Register write successful!")
    else:
        logger.info(f"Register write failed! Expected {expected_value}, got {register_3_value}")
        assert False
    
    # Phase 2: Write value 0 to register 5 (packet length)
    logger.info("Phase 2: Writing value 0 to register 5")
    value_packet = create_register_write_packet(register=5, value=0, dest_x=LANE_X, dest_y=LANE_Y)
    west_driver.add_packet(value_packet)
    
    # Wait for packet processing
    for cycle in range(20):
        await triggers.RisingEdge(dut.clock)
    
    # Check register 5 value
    register_5_value = dut.rff.registers_5_value.value
    logger.info(f"Register 5 value: {register_5_value}")
    assert register_5_value == 0, f"Expected register 5 to be 0, got {register_5_value}"
    
    # Phase 2: Write program instructions to instruction memory
    logger.info("Phase 2: Writing packet send and halt instructions to instruction memory")
    
    # Create packet send instruction: send from location=reg3, value=reg5, result=reg0
    packet_instr = PacketInstruction(
        mode=PacketModes.SEND,  # 4
        mask=False,             # 0
        location_reg=3,         # register 3 (coordinate)
        send_length_reg=5,      # register 5 (value 4)
        result_reg=0            # register 0
    )
    packet_word = packet_instr.encode()
    logger.info(f"Encoded packet instruction: 0x{packet_word:04x}")
    
    # Create halt instruction
    halt_instr = HaltInstruction()
    halt_word = halt_instr.encode()
    logger.info(f"Encoded halt instruction: 0x{halt_word:04x}")
    
    # Write both instructions starting at address 0
    program = [packet_word, halt_word]
    instr_packet = create_instruction_write_packet(program, base_address=0, dest_x=LANE_X, dest_y=LANE_Y)
    west_driver.add_packet(instr_packet)
    
    # Wait for instruction write
    for cycle in range(20):
        await triggers.RisingEdge(dut.clock)
    
    # Phase 2: Start program execution
    logger.info("Phase 2: Starting program execution at PC=0")
    start_packet = create_start_packet(pc=0, dest_x=LANE_X, dest_y=LANE_Y)
    west_driver.add_packet(start_packet)
    
    # Wait for program execution and monitor outputs
    logger.info("Phase 2: Monitoring for packet output")
    packet_found = False
    for cycle in range(100):
        await triggers.RisingEdge(dut.clock)
        
        # Check all receivers for packets
        for receiver in [north_receiver, south_receiver, east_receiver, west_receiver]:
            if receiver.has_packet():
                packet = receiver.get_packet()
                header = packet_utils.PacketHeader.from_word(packet[0])
                logger.info(f"Received packet from {receiver.name}: dest=({header.dest_x},{header.dest_y}), length={header.length}")
                
                # Check if this matches our expected packet
                if header.dest_x == 0 and header.dest_y == 1 and header.length == 0:
                    logger.info("SUCCESS: Found expected packet with destination (0,1) and length 0!")
                    packet_found = True
                    break
        
        if packet_found:
            break
    
    if not packet_found:
        logger.error("FAILURE: Expected packet with destination (0,1) and length 0 was not found")
        assert False, "Expected packet not found"
    
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
