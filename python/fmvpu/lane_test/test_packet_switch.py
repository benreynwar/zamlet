import os
import sys
import tempfile
from typing import Optional
import logging

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


def create_simple_packet(dest_x: int, dest_y: int, data_word: int = 0x1234) -> list[int]:
    """Create a simple test packet with header and one data word"""
    header = PacketHeader(
        length=1,  # One data word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=PacketHeaderModes.NORMAL
    )
    return [header.encode(), data_word]


@cocotb.test()
async def packet_switch_north_to_south_test(dut: HierarchyObject) -> None:
    """Test sending packet from north input to south output."""
    test_utils.configure_logging_sim('DEBUG')
    
    logger.info("Starting PacketSwitch north-to-south test...")
    
    # Test switch position - we'll route through this switch
    SWITCH_X = 1
    SWITCH_Y = 1
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    
    # Initialize position inputs
    dut.io_thisX.value = SWITCH_X
    dut.io_thisY.value = SWITCH_Y
    
    # Initialize forward interface
    dut.io_forward_valid.value = 0
    
    # Create packet drivers and receivers
    north_driver = PacketDriver(
        dut=dut,
        valid_signal=dut.io_ni_valid,
        ready_signal=dut.io_ni_ready,
        data_signal=dut.io_ni_bits_data,
        isheader_signal=dut.io_ni_bits_isHeader
    )
    
    south_receiver = PacketReceiver(
        dut=dut,
        valid_signal=dut.io_so_valid,
        ready_signal=dut.io_so_ready,
        data_signal=dut.io_so_bits_data,
        isheader_signal=dut.io_so_bits_isHeader
    )
    
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
    cocotb.start_soon(north_driver.drive_packets())
    cocotb.start_soon(south_receiver.receive_packets())
    
    # Create packet destined for position (1, 2) - south of current position
    test_packet = create_simple_packet(dest_x=1, dest_y=2, data_word=0xDEADBEEF)
    
    logger.info(f"Sending packet to destination ({1}, {2}) with data 0x{0xDEADBEEF:x}")
    
    # Send the packet
    north_driver.add_packet(test_packet)
    
    # Wait for packet to be received
    timeout_cycles = 100
    for cycle in range(timeout_cycles):
        await triggers.RisingEdge(dut.clock)
        if south_receiver.has_packet():
            break
    
    if south_receiver.has_packet():
        received_packet = south_receiver.get_packet()
        logger.info(f"Received packet: {[hex(word) for word in received_packet]}")
        
        # Check if data word matches
        if len(received_packet) >= 2 and received_packet[1] == 0xDEADBEEF:
            logger.info("TEST PASSED: Packet successfully routed from north to south")
        else:
            logger.error("TEST FAILED: Data word mismatch")
            assert False
    else:
        logger.error("TEST FAILED: No packet received on south output")
        assert False


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
