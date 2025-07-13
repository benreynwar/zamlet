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
from fmvpu.new_lane.packet_utils import PacketDriver, PacketReceiver
from fmvpu.new_lane.instructions import PacketHeader, PacketHeaderModes
from fmvpu.new_lane.lane_params import LaneParams


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


def create_simple_packet(dest_x: int, dest_y: int, data_words: list[int]) -> list[int]:
    """Create a simple test packet with header and one data word"""
    header = PacketHeader(
        length=len(data_words),
        dest_x=dest_x,
        dest_y=dest_y,
        mode=PacketHeaderModes.NORMAL,
    )
    return [header.encode()] + data_words


def make_seed(rnd):
    return rnd.getrandbits(32)

SWITCH_X = 8
SWITCH_Y = 8

@cocotb.test()
async def packet_switch_test(dut: HierarchyObject, seed=0) -> None:
    test_utils.configure_logging_sim('DEBUG')
    rnd = Random(seed)

    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())

    # Initialize position inputs
    dut.io_thisX.value = SWITCH_X
    dut.io_thisY.value = SWITCH_Y

    # Initialize forward interface
    dut.io_forward_valid.value = 0

    drivers = {
        label: PacketDriver(
            dut=dut,
            seed=make_seed(rnd),
            valid_signal=getattr(dut, f'io_{label}i_valid'),
            ready_signal=getattr(dut, f'io_{label}i_ready'),
            data_signal=getattr(dut, f'io_{label}i_bits_data'),
            isheader_signal=getattr(dut, f'io_{label}i_bits_isHeader'),
            p_valid=0.5,
        )
        for label in ['n', 's', 'e', 'w', 'h']}

    receivers = {
        label: PacketReceiver(
            name=label,
            dut=dut,
            seed=make_seed(rnd),
            valid_signal=getattr(dut, f'io_{label}o_valid'),
            ready_signal=getattr(dut, f'io_{label}o_ready'),
            data_signal=getattr(dut, f'io_{label}o_bits_data'),
            isheader_signal=getattr(dut, f'io_{label}o_bits_isHeader'),
        )
        for label in ['n', 's', 'e', 'w', 'h']}

    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0

    # Wait a few cycles for reset to stabilize
    for _ in range(5):
        await triggers.RisingEdge(dut.clock)
    
    logger.info("Reset sequence completed")
    
    # Start the packet driver and receiver tasks
    for direction in ['n', 's', 'e', 'w', 'h']:
        cocotb.start_soon(drivers[direction].drive_packets())
        cocotb.start_soon(receivers[direction].receive_packets())

    for i in range(100):
        await packet_switch_rnd_test(dut, rnd, drivers, receivers)


async def packet_switch_rnd_test(dut: HierarchyObject, rnd: Random, drivers, receivers) -> None:
    directions = ['n', 's', 'e', 'w', 'h']

    x_pos = SWITCH_X
    y_pos = SWITCH_Y

    max_x = 16
    max_y = 16

    # Finding which destinations would get routed in each direction
    positions = {'n': [], 'e': [], 's': [], 'w': [], 'h': []}
    all_positions = set()
    for x in range(0, 16):
        for y in range(0, 16):
            pos = (x, y)
            all_positions.add(pos)
            if (x == x_pos):
                if (y == y_pos):
                    positions['h'].append(pos)
                elif y < y_pos:
                    positions['n'].append(pos)
                else:
                    positions['s'].append(pos)
            elif (x < x_pos):
                positions['w'].append(pos)
            else:
                positions['e'].append(pos)
    available_directions = directions[:]

    # Maps destination to packet
    # We send only one packet to each destination so we can tell them apart.
    expected_packets = {}

    n_packets = 30
    for index in range(n_packets):
        # Pick a random directions for the packet to come from
        src = rnd.choice(directions)
        other_directions = available_directions[:]
        if src in other_directions:
            other_directions.remove(src)
        if not other_directions:
            logger.warning('Could not produce all the packets. Running out of destinations')
            break
        # Pick a random direction for it to go to
        # Can't be where it came from.
        # There also must still be coords in that direction that
        # we haven't already sent a packet too.
        dst = rnd.choice(other_directions)
        dest_x, dest_y = rnd.choice(positions[dst])
        logger.info(f'Trying to send a packet from {src} to {dst} to {dest_x}, {dest_y}')
        positions[dst].remove((dest_x, dest_y))
        if not positions[dst]:
            # That was the last coord in this direction
            available_directions.remove(dst)
        length = rnd.randint(0, 8)
        data_words = [rnd.randint(0, 10) for i in range(length)]
        test_packet = create_simple_packet(dest_x=dest_x, dest_y=dest_y, data_words=data_words)
        drivers[src].add_packet(test_packet)
        assert (dest_x, dest_y) not in expected_packets
        expected_packets[(dest_x, dest_y)] = test_packet
    
    timeout_cycles = 1000
    # Wait for packet to be received
    for cycle in range(timeout_cycles):
        await triggers.RisingEdge(dut.clock)
        for direction in directions:
            if receivers[direction].has_packet():
                received_packet = receivers[direction].get_packet()
                header = PacketHeader.from_word(received_packet[0])
                expected_packet = expected_packets[(header.dest_x, header.dest_y)]
                logger.info(f'rcv_dir:{direction} ({header.dest_x}, {header.dest_y})')
                logger.info(f'Recived packet is {received_packet} ({header.dest_x}, {header.dest_y})')
                logger.info(f'Expected packet is {expected_packet}')
                assert received_packet == expected_packet
                del expected_packets[(header.dest_x, header.dest_y)]
        if not expected_packets:
            break
    logger.info(f'Expected packet dests with packets are {expected_packets.keys()}')
    assert not expected_packets


def test_packet_switch_basic(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = 'PacketSwitch'
    module = 'fmvpu.lane_test.test_packet_switch'
    
    test_params = {
        'seed': seed,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_packet_switch_basic(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Find the lane config file
        config_file = os.path.join(os.path.dirname(this_dir), '..', '..', 'configs', 'lane_default.json')
        config_file = os.path.abspath(config_file)
        
        # Generate PacketSwitch with lane parameters
        filenames = generate_rtl.generate('PacketSwitch', working_dir, [config_file])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, 'packet_switch_verilog.sv')
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_packet_switch_basic(concat_filename, seed)


if __name__ == '__main__':
    test_utils.configure_logging_pre_sim('INFO')
    
    if len(sys.argv) >= 2:
        # Called from Bazel with verilog_file
        verilog_file = sys.argv[1]
        test_packet_switch_basic(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_packet_switch_basic()
