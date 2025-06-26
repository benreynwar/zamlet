import os
import sys
import json
import math
from random import Random
import collections
import tempfile
import logging
from typing import Any, Deque, Optional, List

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from fmvpu import generate_rtl
from fmvpu import test_utils
from fmvpu.params import FMVPUParams
from fmvpu.packet_utils import PacketHeader, PacketSender, PacketReceiver

logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def send_data_via_packets(data: List[int], address, ident, dut, packet_senders: List[List], params: FMVPUParams) -> None:
    """Send data via packets to the lane grid using receive instruction."""
    logger.info('send_data_via_packets: start')
    
    # Send packets to each lane in the grid
    n_lanes = (params.n_rows - 2) * (params.n_columns - 2)
    assert len(data) % n_lanes == 0, f"Data length {len(data)} must be a multiple of number of lanes {n_lanes}"
    
    # Create packets for each lane position
    for row in range(params.n_rows - 2):
        for col in range(params.n_columns - 2):
            lane_index = row * (params.n_columns - 2) + col
            # Extract strided data for this lane
            lane_data = data[lane_index::n_lanes]
            channel = col % params.n_channels  # Distribute across channels
            packet_header = PacketHeader(
                dest_x=col+1, dest_y=row+1, src_x=0, src_y=0,
                address=address, length=len(lane_data), expects_receive=True, ident=ident
            )
            header = packet_header.to_word(params)
            packet = [header] + lane_data
            packet_senders[row][channel].queue.append(packet)
    
    # Wait for all packets to be sent
    while True:
        all_empty = True
        for row in range(params.n_rows-2):
            for channel in range(params.n_channels):
                if packet_senders[row][channel].queue:
                    all_empty = False
        if all_empty:
            break
        await triggers.RisingEdge(dut.clock)
    
    logger.info('send_data_via_packets: end')
    await triggers.RisingEdge(dut.clock)


async def receive_data_via_packets(dut, packet_receivers: List[List], params: FMVPUParams) -> List[int]:
    """Receive data via packets from the lane grid using send instruction."""
    logger.info('receive_data_via_packets: start')
    
    # Wait for packets from all lanes
    n_lanes = (params.n_rows - 2) * (params.n_columns - 2)
    received_data = [None] * n_lanes
    packets_received = 0
    expected_length = None
    
    while packets_received < n_lanes:
        await triggers.RisingEdge(dut.clock)
        
        # Check all packet receiver queues for new packets
        for row in range(params.n_rows-2):
            for channel in range(params.n_channels):
                queue = packet_receivers[row][channel].queue
                if queue:
                    packet = queue.popleft()
                    # Extract source lane coordinates from header
                    header = packet[0]
                    header_info = PacketHeader.from_word(params, header)
                    src_row = header_info.src_y
                    src_col = header_info.src_x
                    lane_index = (src_row - 1) * (params.n_columns - 2) + (src_col - 1)
                    
                    # Validate packet and lane index
                    if len(packet) <= 1:
                        raise RuntimeError(f"Received packet with zero length data from lane ({src_col}, {src_row})")
                    if not (0 <= lane_index < n_lanes):
                        raise RuntimeError(f"Lane index {lane_index} out of bounds [0, {n_lanes})")
                    if received_data[lane_index] is not None:
                        raise RuntimeError(f"Already received data for lane {lane_index} at ({src_col}, {src_row})")
                    
                    # Check packet length consistency
                    packet_data = packet[1:]
                    if expected_length is None:
                        expected_length = len(packet_data)
                    elif len(packet_data) != expected_length:
                        raise RuntimeError(f"Packet from lane ({src_col}, {src_row}) has length {len(packet_data)}, expected {expected_length}")
                    
                    # Store the data (skip header)
                    received_data[lane_index] = packet_data
                    packets_received += 1
    
    # Flatten the data: all 1st elements, then all 2nd elements, etc.
    if expected_length is None:
        raise RuntimeError("No packets received")
    
    flattened_data = []
    for word_index in range(expected_length):
        for lane_index in range(n_lanes):
            if received_data[lane_index] is None:
                raise RuntimeError(f"Missing data for lane {lane_index}")
            flattened_data.append(received_data[lane_index][word_index])
    
    logger.info('receive_data_via_packets: end')
    return flattened_data



def submit_send(dut: HierarchyObject, length: int, address: int, params: Any, ident: int) -> None:
    """Submit a send instruction to all columns in the lane grid."""
    # Submit to all columns
    for col in range(params.n_columns-2):
        getattr(dut, f'io_instr_{col}_sendreceive_valid').value = 1
        getattr(dut, f'io_instr_{col}_sendreceive_bits_mode').value = 0
        getattr(dut, f'io_instr_{col}_sendreceive_bits_length').value = length
        getattr(dut, f'io_instr_{col}_sendreceive_bits_srcAddr').value = address
        getattr(dut, f'io_instr_{col}_sendreceive_bits_ident').value = ident
        getattr(dut, f'io_instr_{col}_sendreceive_bits_dstAddr').value = 0
        getattr(dut, f'io_instr_{col}_sendreceive_bits_channel').value = col % params.n_channels
        getattr(dut, f'io_instr_{col}_sendreceive_bits_destX').value = 0  # West edge
        getattr(dut, f'io_instr_{col}_sendreceive_bits_destY').value = 0  # Don't care since useSameY=1
        getattr(dut, f'io_instr_{col}_sendreceive_bits_useSameX').value = 0
        getattr(dut, f'io_instr_{col}_sendreceive_bits_useSameY').value = 1


def submit_receive(dut: HierarchyObject, length: int, address: int, params: Any, ident: int) -> None:
    """Submit a receive instruction to all columns in the lane grid."""
    # Submit to all columns
    for col in range(params.n_columns-2):
        getattr(dut, f'io_instr_{col}_sendreceive_valid').value = 1
        getattr(dut, f'io_instr_{col}_sendreceive_bits_mode').value = 1
        getattr(dut, f'io_instr_{col}_sendreceive_bits_length').value = length
        getattr(dut, f'io_instr_{col}_sendreceive_bits_dstAddr').value = address
        getattr(dut, f'io_instr_{col}_sendreceive_bits_ident').value = ident


def clear_sendreceive(dut: HierarchyObject, params: Any) -> None:
    # Clear all columns
    for col in range(params.n_columns-2):
        getattr(dut, f'io_instr_{col}_sendreceive_valid').value = 0


def submit_load(dut: HierarchyObject, reg: int, addr: int, params: Any) -> None:
    """Load from register to memory address"""
    for col in range(params.n_columns-2):
        getattr(dut, f'io_instr_{col}_loadstore_valid').value = 1
        getattr(dut, f'io_instr_{col}_loadstore_bits_mode').value = 0  # Load mode: register -> memory
        getattr(dut, f'io_instr_{col}_loadstore_bits_reg').value = reg
        getattr(dut, f'io_instr_{col}_loadstore_bits_addr').value = addr


def submit_store(dut: HierarchyObject, reg: int, addr: int, params: Any) -> None:
    """Store from memory address to register"""
    for col in range(params.n_columns-2):
        getattr(dut, f'io_instr_{col}_loadstore_valid').value = 1
        getattr(dut, f'io_instr_{col}_loadstore_bits_mode').value = 1  # Store mode: memory -> register
        getattr(dut, f'io_instr_{col}_loadstore_bits_reg').value = reg
        getattr(dut, f'io_instr_{col}_loadstore_bits_addr').value = addr


def clear_loadstore(dut: HierarchyObject, params: Any) -> None:
    for col in range(params.n_columns-2):
        getattr(dut, f'io_instr_{col}_loadstore_valid').value = 0


async def send_and_receive(dut: HierarchyObject, rnd: Random, params: Any, packet_senders: List[List], packet_receivers: List[List]) -> None:
    """
    Send in vectors using the Receive instruction.
    Send out vectors using the Send instruction.
    Check that they match.
    """
    n_lanes = (params.n_columns - 2) * (params.n_rows - 2)
    ident = 3
    length = 2
    address = 0
    
    test_data = [0x1000 + i for i in range(n_lanes * length)]  # Generate data based on length parameter
    
    # Set up receive instruction
    submit_receive(dut, length, address, params, ident)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut, params)
    for i in range(4):
        await triggers.RisingEdge(dut.clock)
    
    # Send data via packets
    await send_data_via_packets(test_data, address, ident, dut, packet_senders, params)
    for i in range(4):
        await triggers.RisingEdge(dut.clock)
    
    # Set up send instruction
    submit_send(dut, length, address, params, ident)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut, params)
    for i in range(4):
        await triggers.RisingEdge(dut.clock)
    
    # Receive data via packets
    received_data = await receive_data_via_packets(dut, packet_receivers, params)
    
    assert test_data == received_data


async def send_and_receive_swap_order(dut: HierarchyObject, rnd: Random, params: Any, packet_senders: List[List], packet_receivers: List[List]) -> None:
    """
    Send in vectors using the Receive instruction.
    Load the vectors into registers.
    Store them back to the data memory but in the opposite order.
    Send out vectors using the Send instruction.
    """
    n_lanes = (params.n_columns - 2) * (params.n_rows - 2)
    ident = 4
    length = 2
    address = 0
    
    test_data = [0x2000 + i for i in range(n_lanes * length)]  # Generate data based on length parameter
    expected_data = test_data[n_lanes:] + test_data[:n_lanes]  # Swapped order
    
    # Step 1: Receive vectors into memory (addresses 0 and 1)
    submit_receive(dut, length, address, params, ident)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut, params)
    for i in range(4):
        await triggers.RisingEdge(dut.clock)
    
    await send_data_via_packets(test_data, address, ident, dut, packet_senders, params)
    for i in range(4):
        await triggers.RisingEdge(dut.clock)
    
    # Step 2: Store vector from memory address 0 into register 0
    submit_store(dut, 0, 0, params)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut, params)
    await triggers.RisingEdge(dut.clock)
    
    # Step 3: Store vector from memory address 1 into register 1
    submit_store(dut, 1, 1, params)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut, params)
    await triggers.RisingEdge(dut.clock)
    
    # Step 4: Load register 0 to memory address 1 (swap)
    submit_load(dut, 0, 1, params)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut, params)
    await triggers.RisingEdge(dut.clock)
    
    # Step 5: Load register 1 to memory address 0 (swap)
    submit_load(dut, 1, 0, params)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut, params)
    await triggers.RisingEdge(dut.clock)
    
    # Step 6: Send the swapped data out
    submit_send(dut, length, address, params, ident)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut, params)
    for i in range(4):
        await triggers.RisingEdge(dut.clock)
    
    # Receive data via packets
    received_data = await receive_data_via_packets(dut, packet_receivers, params)
    
    assert expected_data == received_data


async def timeout(dut: HierarchyObject, max_cycles: int) -> None:
    count = 0
    while True:
        await triggers.RisingEdge(dut.clock)
        assert count < max_cycles, f"Test timed out after {max_cycles} cycles"
        count += 1


@cocotb.test()
async def lane_grid_test(dut: HierarchyObject) -> None:
    # Configure logging for the cocotb test
    test_utils.configure_logging_sim('INFO')
    
    test_params = test_utils.read_params()
    rnd = Random(test_params['seed'])
    params_dict = test_params['params']
    params = FMVPUParams.from_dict(params_dict)
    
    # Initialize all instruction interfaces to inactive
    for col in range(params.n_columns-2):
        getattr(dut, f'io_instr_{col}_compute_valid').value = 0
        getattr(dut, f'io_instr_{col}_loadstore_valid').value = 0
        getattr(dut, f'io_instr_{col}_network_valid').value = 0
        getattr(dut, f'io_instr_{col}_sendreceive_valid').value = 0
    
    # Initialize all network interfaces to inactive
    for row in range(params.n_rows-2):
        for channel in range(params.n_channels):
            getattr(dut, f'io_wI_{row}_{channel}_valid').value = 0
            getattr(dut, f'io_eI_{row}_{channel}_valid').value = 0
            # Token inputs for outputs (these go into the LaneGrid)
            getattr(dut, f'io_eO_{row}_{channel}_token').value = 0
            getattr(dut, f'io_wO_{row}_{channel}_token').value = 0
    
    for col in range(params.n_columns-2):
        for channel in range(params.n_channels):
            getattr(dut, f'io_nI_{col}_{channel}_valid').value = 0
            getattr(dut, f'io_sI_{col}_{channel}_valid').value = 0
            # Token inputs for outputs (these go into the LaneGrid)
            getattr(dut, f'io_nO_{col}_{channel}_token').value = 0
            getattr(dut, f'io_sO_{col}_{channel}_token').value = 0

    cocotb.start_soon(Clock(dut.clock, 1, 'ns').start())
    cocotb.start_soon(timeout(dut, 1000))
    
    # Reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0

    # Create packet senders and receivers for each row and channel (west direction)
    packet_senders = []
    packet_receivers = []
    
    for row in range(params.n_rows-2):
        row_senders = []
        row_receivers = []
        for channel in range(params.n_channels):
            # Create queues for this row/channel combination
            sender_queue = collections.deque()
            receiver_queue = collections.deque()
            
            # Create PacketSender and PacketReceiver for west direction
            sender = PacketSender(dut, 'w', row, channel, sender_queue)
            receiver = PacketReceiver(dut, 'w', row, channel, receiver_queue, params)
            
            row_senders.append(sender)
            row_receivers.append(receiver)
        
        packet_senders.append(row_senders)
        packet_receivers.append(row_receivers)
    
    # Run tests
    await send_and_receive(dut, rnd, params, packet_senders, packet_receivers)
    await send_and_receive_swap_order(dut, rnd, params, packet_senders, packet_receivers)
    
    # Clean up packet handlers
    for row in range(params.n_rows-2):
        for channel in range(params.n_channels):
            packet_senders[row][channel].cancel()
            packet_receivers[row][channel].cancel()


def test_lane_grid(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    # Use the single concatenated Verilog file
    filenames = [verilog_file]
    
    toplevel = 'LaneGrid'
    module = 'fmvpu.lane_grid.test_lane_grid'
    
    with open(params_file, 'r', encoding='utf-8') as params_f:
        design_params = json.loads(params_f.read())
    
    test_params = {
        'seed': seed,
        'params': design_params,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_lane_grid(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        params_filename = os.path.join(this_dir, 'params.json')
        filenames = generate_rtl.generate('LaneGrid', working_dir, [params_filename])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, 'lane_grid_verilog.sv')
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_lane_grid(concat_filename, params_filename, seed)


if __name__ == '__main__':
    test_utils.configure_logging_pre_sim('INFO')
    
    if len(sys.argv) == 3:
        # Called from Bazel with verilog_file and params_file
        verilog_file = sys.argv[1]
        params_file = sys.argv[2]
        
        test_lane_grid(verilog_file, params_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_lane_grid()
