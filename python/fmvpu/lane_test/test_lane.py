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
from fmvpu.new_lane.instructions import PacketInstruction, PacketModes, HaltInstruction, ALUInstruction, ALUModes
from fmvpu.new_lane.lane_params import LaneParams


logger = logging.getLogger(__name__)


def create_register_write_packet(
    register: int,
    value: int,
    dest_x: int = 0,
    dest_y: int = 0,
    params: LaneParams = LaneParams(),
) -> list[int]:
    """Create a command packet to write a value to a register"""
    header = packet_utils.PacketHeader(
        length=1,  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND,
    )
    command_word = packet_utils.create_register_write_command(register, value, params)
    return [header.encode(), command_word]


def create_instruction_write_packet(
    instructions: list[int],
    base_address: int = 0,
    dest_x: int = 0,
    dest_y: int = 0,
    params: LaneParams = LaneParams(),
) -> list[int]:
    """Create a command packet to write multiple instructions to instruction memory"""
    header = packet_utils.PacketHeader(
        length=len(instructions),  # One command word per instruction
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND,
    )
    command_words = []
    for i, instruction in enumerate(instructions):
        address = base_address + i
        command_word = packet_utils.create_instruction_memory_write_command(
            address, instruction, params
        )
        command_words.append(command_word)
    return [header.encode()] + command_words


def create_start_packet(
    pc: int, dest_x: int = 0, dest_y: int = 0, params: LaneParams = LaneParams()
) -> list[int]:
    """Create a command packet to start execution at a given PC"""
    header = packet_utils.PacketHeader(
        length=1,  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND,
    )
    command_word = packet_utils.create_start_command(pc, params)
    return [header.encode(), command_word]


def create_data_packet(
    data: list[int], dest_x: int = 0, dest_y: int = 0) -> list[int]:
    """Send a data packet in"""
    header = packet_utils.PacketHeader(
        length=len(data),  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.NORMAL,
    )
    return [header.encode()] + data


this_dir = os.path.abspath(os.path.dirname(__file__))


def make_seed(rnd):
    return rnd.getrandbits(32)


def make_coord_register(x: int, y: int, params: LaneParams = LaneParams()) -> int:
    """Create coordinate register value: (y << x_pos_width) | x"""
    return (y << params.x_pos_width) | x


# Test lane position
LANE_X = 1
LANE_Y = 2


async def send_zero_length_packet_test(dut: HierarchyObject, rnd, drivers, receivers) -> None:
    """Sends a packet with zero length"""
    coord_word = make_coord_register(x=0, y=1)
    coord_packet = create_register_write_packet(
        register=3, value=coord_word, dest_x=LANE_X, dest_y=LANE_Y
    )
    drivers['w'].add_packet(coord_packet)

    # Wait 40 cycles for packet processing
    for cycle in range(40):
        await triggers.RisingEdge(dut.clock)

    # Probe register 3 to see if value was written
    register_3_value = dut.rff.registers_3_value.value
    assert register_3_value == coord_word

    # Create packet send instruction: send from location=reg3, value=reg5, result=reg0
    program = [
        PacketInstruction(
            mode=PacketModes.SEND,
            mask=False,  # 0
            location_reg=3,  # coordinate
            send_length_reg=0,  # 0 length
            result_reg=0,  # No result used
        ).encode(),
        HaltInstruction().encode()
        ]

    instr_packet = create_instruction_write_packet(
        program, base_address=0, dest_x=LANE_X, dest_y=LANE_Y
    )
    drivers['w'].add_packet(instr_packet)

    # Wait for instruction write
    for cycle in range(20):
        await triggers.RisingEdge(dut.clock)

    # Start the program
    start_packet = create_start_packet(pc=0, dest_x=LANE_X, dest_y=LANE_Y)
    drivers['w'].add_packet(start_packet)

    # Wait for program execution and monitor outputs
    logger.info("Phase 2: Monitoring for packet output")
    packet_found = False
    for cycle in range(100):
        await triggers.RisingEdge(dut.clock)
        if receivers['w'].has_packet():
            packet = receivers['w'].get_packet()
            header = packet_utils.PacketHeader.from_word(packet[0])
            assert header.dest_x == 0 and header.dest_y == 1 and header.length == 0
            packet_found = True
            break
    assert packet_found


async def echo_packet_test(dut: HierarchyObject, rnd, drivers, receivers) -> None:

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
    machine_code = [instr.encode() for instr in program]

    instr_packet = create_instruction_write_packet(
        machine_code, base_address=0, dest_x=LANE_X, dest_y=LANE_Y
    )
    drivers['w'].add_packet(instr_packet)

    # Wait for instruction write
    for cycle in range(20):
        await triggers.RisingEdge(dut.clock)

    # Start the program
    start_packet = create_start_packet(pc=0, dest_x=LANE_X, dest_y=LANE_Y)
    drivers['w'].add_packet(start_packet)

    data = [1, 2]
    data_packet = create_data_packet(data=data, dest_x=LANE_X, dest_y=LANE_Y)
    drivers['w'].add_packet(data_packet)

    # Wait for program execution and monitor outputs
    logger.info("Phase 2: Monitoring for packet output")
    packet_found = False
    for cycle in range(100):
        await triggers.RisingEdge(dut.clock)
        if receivers['w'].has_packet():
            packet = receivers['w'].get_packet()
            header = packet_utils.PacketHeader.from_word(packet[0])
            assert header.dest_x == 0 and header.dest_y == 0 and header.length == len(data)
            assert packet[1:] == data
            packet_found = True
            break
    assert packet_found


async def add_two_numbers_test(dut: HierarchyObject, rnd, drivers, receivers) -> None:

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
    machine_code = [instr.encode() for instr in program]

    instr_packet = create_instruction_write_packet(
        machine_code, base_address=0, dest_x=LANE_X, dest_y=LANE_Y
    )
    drivers['w'].add_packet(instr_packet)

    # Wait for instruction write
    for cycle in range(20):
        await triggers.RisingEdge(dut.clock)

    # Start the program
    start_packet = create_start_packet(pc=0, dest_x=LANE_X, dest_y=LANE_Y)
    drivers['w'].add_packet(start_packet)

    data = [10, 8]
    data_packet = create_data_packet(data=data, dest_x=LANE_X, dest_y=LANE_Y)
    drivers['w'].add_packet(data_packet)

    # Wait for program execution and monitor outputs
    logger.info("Phase 2: Monitoring for packet output")
    packet_found = False
    for cycle in range(100):
        await triggers.RisingEdge(dut.clock)
        if receivers['w'].has_packet():
            packet = receivers['w'].get_packet()
            header = packet_utils.PacketHeader.from_word(packet[0])
            assert header.dest_x == 0 and header.dest_y == 0 and header.length == len(data)
            assert packet[1:] == [data[0] + data[1], data[0] * data[1]]
            packet_found = True
            break
    assert packet_found


async def check_dependency_test(dut: HierarchyObject, rnd, drivers, receivers) -> None:

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
    machine_code = [instr.encode() for instr in program]

    instr_packet = create_instruction_write_packet(
        machine_code, base_address=0, dest_x=LANE_X, dest_y=LANE_Y
    )
    drivers['w'].add_packet(instr_packet)

    # Wait for instruction write
    for cycle in range(20):
        await triggers.RisingEdge(dut.clock)

    # Start the program
    start_packet = create_start_packet(pc=0, dest_x=LANE_X, dest_y=LANE_Y)
    drivers['w'].add_packet(start_packet)

    data = [10, 8]
    data_packet = create_data_packet(data=data, dest_x=LANE_X, dest_y=LANE_Y)
    drivers['w'].add_packet(data_packet)

    # Wait for program execution and monitor outputs
    logger.info("Phase 2: Monitoring for packet output")
    packet_found = False
    for cycle in range(100):
        await triggers.RisingEdge(dut.clock)
        if receivers['w'].has_packet():
            packet = receivers['w'].get_packet()
            header = packet_utils.PacketHeader.from_word(packet[0])
            assert header.dest_x == 0 and header.dest_y == 0 and header.length == len(data)
            assert packet[1:] == [data[0] + data[1], data[0] + 2*data[1]]
            packet_found = True
            break
    assert packet_found

@cocotb.test()
async def lane_test(dut: HierarchyObject, seed=0) -> None:
    test_utils.configure_logging_sim("DEBUG")

    rnd = Random(seed)

    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())

    # Initialize position inputs
    dut.io_thisX.value = LANE_X
    dut.io_thisY.value = LANE_Y

    # Initialize network inputs
    dut.io_ni_0_valid.value = 0
    dut.io_si_0_valid.value = 0
    dut.io_ei_0_valid.value = 0
    dut.io_wi_0_valid.value = 0

    drivers = {
        label: packet_utils.PacketDriver(
            dut=dut,
            seed=make_seed(rnd),
            valid_signal=getattr(dut, f'io_{label}i_0_valid'),
            ready_signal=getattr(dut, f'io_{label}i_0_ready'),
            data_signal=getattr(dut, f'io_{label}i_0_bits_data'),
            isheader_signal=getattr(dut, f'io_{label}i_0_bits_isHeader'),
            p_valid=0.5,
        )
        for label in ['n', 's', 'e', 'w']}

    receivers = {
        label: packet_utils.PacketReceiver(
            name=label,
            dut=dut,
            seed=make_seed(rnd),
            valid_signal=getattr(dut, f'io_{label}o_0_valid'),
            ready_signal=getattr(dut, f'io_{label}o_0_ready'),
            data_signal=getattr(dut, f'io_{label}o_0_bits_data'),
            isheader_signal=getattr(dut, f'io_{label}o_0_bits_isHeader'),
        )
        for label in ['n', 's', 'e', 'w']}

    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0

    # Start packet driver and receivers after reset
    for label in ['n', 's', 'e', 'w']:
        cocotb.start_soon(drivers[label].drive_packets())
        cocotb.start_soon(receivers[label].receive_packets())

    await send_zero_length_packet_test(dut, rnd, drivers, receivers)
    await echo_packet_test(dut, rnd, drivers, receivers)
    await add_two_numbers_test(dut, rnd, drivers, receivers)
    await check_dependency_test(dut, rnd, drivers, receivers)


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
