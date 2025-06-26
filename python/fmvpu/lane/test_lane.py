import os
import sys
import json
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
from fmvpu.control_structures import ChannelSlowControl, NetworkSlowControl, GeneralSlowControl, NetworkFastControl
from fmvpu.packet_utils import PacketHeader, PacketSender, PacketReceiver


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def send_data_via_packets(data: List[int], address, ident, dut, queue: Deque[List[int]], params: FMVPUParams) -> None:
    logger.info('send_data_via_packets: start')
    column_index = 1
    row_index = 1
    expected_receive=True
    packet_header = PacketHeader(
        dest_x=column_index, dest_y=row_index, src_x=0, src_y=0,
        address=address, length=len(data), expects_receive=expected_receive, ident=ident
    )
    header = packet_header.to_word(params)
    packet = [header] + data
    queue.append(packet)
    
    # Wait for instruction response to indicate packet has been received
    while not dut.io_instrResponse_valid.value:
        await triggers.RisingEdge(dut.clock)
    
    # Verify the response matches our sent packet
    response_mode = int(dut.io_instrResponse_bits_mode.value)
    response_ident = int(dut.io_instrResponse_bits_ident.value)
    assert response_mode == 1, f"Expected receive mode (1), got {response_mode}"
    assert response_ident == ident, f"Expected ident {ident}, got {response_ident}"
    logger.info('send_data_via_packets: end')
    await triggers.RisingEdge(dut.clock)


async def receive_data_via_packets(dut, queues: Deque[List[int]]) -> List[int]:
    logger.info('receive_data_via_packets: start')
    """Monitor instruction responses and output queue to receive packet data."""
    # Wait for instruction response indicating send is complete
    while not dut.io_instrResponse_valid.value:
        await triggers.RisingEdge(dut.clock)
    
    # Verify the response is for a send instruction
    response_mode = int(dut.io_instrResponse_bits_mode.value)
    assert response_mode == 0, f"Expected send mode (0), got {response_mode}"
    
    # Wait for packet in output queue
    while not queues:
        await triggers.RisingEdge(dut.clock)
    
    packet = queues.popleft()
    logger.info('receive_data_via_packets: end')
    return packet[1:]  # Return data without header


def submit_receive(dut: HierarchyObject, ident: int, length: int, address: int, network_slot: int = 0) -> None:
    """Submit a receive instruction to the lane."""
    dut.io_nInstr_sendreceive_valid.value = 1
    dut.io_nInstr_sendreceive_bits_mode.value = 1
    dut.io_nInstr_sendreceive_bits_length.value = length
    dut.io_nInstr_sendreceive_bits_dstAddr.value = address
    dut.io_nInstr_sendreceive_bits_ident.value = ident


def submit_send(dut: HierarchyObject, ident: int, length: int, address: int, dest_x: int = 0, dest_y: int = 0, channel: int = 0) -> None:
    """Submit a send instruction to the lane."""
    dut.io_nInstr_sendreceive_valid.value = 1
    dut.io_nInstr_sendreceive_bits_mode.value = 0
    dut.io_nInstr_sendreceive_bits_length.value = length
    dut.io_nInstr_sendreceive_bits_srcAddr.value = address
    dut.io_nInstr_sendreceive_bits_ident.value = ident
    dut.io_nInstr_sendreceive_bits_dstAddr.value = 0
    dut.io_nInstr_sendreceive_bits_destX.value = dest_x
    dut.io_nInstr_sendreceive_bits_destY.value = dest_y
    dut.io_nInstr_sendreceive_bits_useSameX.value = 0
    dut.io_nInstr_sendreceive_bits_useSameY.value = 0
    dut.io_nInstr_sendreceive_bits_channel.value = channel


def clear_sendreceive(dut: HierarchyObject) -> None:
    """Clear the send/receive instruction."""
    dut.io_nInstr_sendreceive_valid.value = 0


def submit_load(dut: HierarchyObject, reg: int, addr: int) -> None:
    """Submit a load instruction (register -> memory)."""
    dut.io_nInstr_loadstore_valid.value = 1
    dut.io_nInstr_loadstore_bits_mode.value = 0  # Load mode: register -> memory
    dut.io_nInstr_loadstore_bits_reg.value = reg
    dut.io_nInstr_loadstore_bits_addr.value = addr


def submit_store(dut: HierarchyObject, reg: int, addr: int) -> None:
    """Submit a store instruction (memory -> register)."""
    dut.io_nInstr_loadstore_valid.value = 1
    dut.io_nInstr_loadstore_bits_mode.value = 1  # Store mode: memory -> register
    dut.io_nInstr_loadstore_bits_reg.value = reg
    dut.io_nInstr_loadstore_bits_addr.value = addr


def clear_loadstore(dut: HierarchyObject) -> None:
    """Clear the load/store instruction."""
    dut.io_nInstr_loadstore_valid.value = 0
    

async def send_and_receive(dut: HierarchyObject, rnd: Random, params: Any, packet_sender, packet_receiver, send_channel) -> None:
    """
    Test basic send and receive functionality.
    
    Send in two words using the Receive instruction.
    Send out two words using the Send instruction.
    Check that they match.
    """
    test_data = [0x1234, 0x5678]

    ident = 3
    length = 2
    address = 0
    submit_receive(dut, ident, length, address)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut)
    data = [26, 28]
    await send_data_via_packets(data, address, ident, dut, packet_sender.queue, params)

    receive_packet_task = cocotb.start_soon(receive_data_via_packets(dut, packet_receiver.queue))

    submit_send(dut, ident, length, address, 0, 1, send_channel)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut)
    received_data = await receive_packet_task

    assert data == received_data


async def send_and_receive_swap_order(dut: HierarchyObject, rnd: Random, params: Any, packet_sender, packet_receiver, send_channel) -> None:
    """
    Test data manipulation through register file.
    
    Send in two words using the Receive instruction.
    Load the two words into registers.
    Store them back to the data memory but in the opposite order.
    Send out two words using the Send instruction.
    """
    test_data = [0x1234, 0x5678]
    expected_data = [0x5678, 0x1234]  # swapped order
    
    # Step 1: Receive two words into memory (addresses 0 and 1)
    ident = 3
    length = 2
    address = 0

    submit_receive(dut, ident, length, address)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut)
    await send_data_via_packets(test_data, address, ident, dut, packet_sender.queue, params)
    
    # Step 2: Store word from memory address 0 into register 0
    submit_store(dut, 0, 0)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut)
    await triggers.RisingEdge(dut.clock)  # Wait for store to complete
    
    # Step 3: Store word from memory address 1 into register 1
    submit_store(dut, 1, 1)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut)
    await triggers.RisingEdge(dut.clock)  # Wait for store to complete
    
    # Step 4: Load register 0 to memory address 1 (swap)
    submit_load(dut, 0, 1)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut)
    await triggers.RisingEdge(dut.clock)  # Wait for load to complete
    
    # Step 5: Load register 1 to memory address 0 (swap)
    submit_load(dut, 1, 0)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut)
    await triggers.RisingEdge(dut.clock)  # Wait for load to complete
    
    # Step 6: Send the swapped data out
    receive_packet_task = cocotb.start_soon(receive_data_via_packets(dut, packet_receiver.queue))
    
    submit_send(dut, ident, length, address, 0, 1, send_channel)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut)
    received_data = await receive_packet_task
    
    assert expected_data == received_data, f"Expected {expected_data}, got {received_data}"


async def timeout_watchdog(dut: HierarchyObject, max_cycles: int) -> None:
    """Timeout watchdog to prevent infinite test execution."""
    count = 0
    while True:
        await triggers.RisingEdge(dut.clock)
        assert count < max_cycles, f"Test timed out after {max_cycles} cycles"
        count += 1


async def reset_dut(dut: HierarchyObject) -> None:
    """Apply reset sequence to DUT."""
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)


async def error_monitor(dut: HierarchyObject, params: FMVPUParams) -> None:
    """Continuously monitor error signals and assert if any are asserted."""
    # Constants matching Lane module configuration
    N_DRF_WRITE_PORTS = 3
    
    while True:
        await triggers.RisingEdge(dut.clock)
        
        error_signals = []
        
        # Check ddmAccess error signals
        if dut.io_errors_ddmAccess_badInstr.value:
            error_signals.append("ddmAccess.badInstr")
        if dut.io_errors_ddmAccess_badFromNetwork.value:
            error_signals.append("ddmAccess.badFromNetwork")
        if dut.io_errors_ddmAccess_sendConflict.value:
            error_signals.append("ddmAccess.sendConflict")
        if dut.io_errors_ddmAccess_sendFifoOverflow.value:
            error_signals.append("ddmAccess.sendFifoOverflow")
        if dut.io_errors_ddmAccess_receiveSlotOccupied.value:
            error_signals.append("ddmAccess.receiveSlotOccupied")
        
        # Check networkNode error signals
        if dut.io_errors_networkNode_instrConflict.value:
            error_signals.append("networkNode.instrConflict")
        
        # Check dataMemory error signals (bank conflicts)
        for i in range(params.ddm_n_banks):
            bank_attr = f'io_errors_dataMemory_bankConflicts_{i}'
            if getattr(dut, bank_attr).value:
                error_signals.append(f"dataMemory.bankConflicts[{i}]")
        
        # Check registerFile error signals (write conflicts)
        if dut.io_errors_registerFile_writeConflict.value:
            error_signals.append("registerFile.writeConflict")
        
        # Assert if any errors are found
        if error_signals:
            error_msg = f"Error signals asserted: {', '.join(error_signals)}"
            assert False, error_msg


async def configure_network_fast_control(dut: HierarchyObject, params: FMVPUParams, packet_queue: collections.deque) -> None:
    """Configure NetworkFastControl for data routing between channels."""
    # Create fast control configuration
    fast_control = NetworkFastControl.default(params)
    
    # Configure channel 1 to receive from west input
    fast_control.channels[1].we_input_sel = True  # Select west input
    
    # Configure channel 2 to send to east output
    fast_control.channels[2].we_crossbar_sel = 2  # Route channel 2 to east
    
    # Configure general data routing
    fast_control.general.drf_sel = 1  # Select data from channel 1 for register file
    fast_control.general.ddm_sel = 1  # Select data from channel 1 for data memory
    
    # Pack fast control configuration into words
    config_words = fast_control.to_words(params)
    
    # Calculate fast control memory address for slot 0
    control_mem_start = params.fast_network_control_offset
    
    # Create packet header targeting this lane's location (0,0)
    packet_header = PacketHeader(
        dest_x=0, dest_y=0, src_x=0, src_y=0,
        address=control_mem_start, length=len(config_words), expects_receive=True, ident=0
    )
    header = packet_header.to_word(params)
    
    # Create the configuration packet and add to queue
    config_packet = [header] + config_words

    packet_queue.append(config_packet)
    
    # Wait for packet to be sent and processed
    while packet_queue:
        await triggers.RisingEdge(dut.clock)
    
    # Wait a few more cycles for packet processing
    for _ in range(10):
        await triggers.RisingEdge(dut.clock)


async def configure_network_mixed_mode(dut: HierarchyObject, params: FMVPUParams, packet_queue: collections.deque) -> None:
    """Configure network with channel 0 in packet mode, channels 1-2 in static mode."""
    # Create mixed mode configuration - channel 0 packet, channels 1-2 static
    mixed_config = NetworkSlowControl(
        channels=[
            # Channel 0: packet mode for network configuration
            ChannelSlowControl.default(params),
            # Channel 1: static mode for west input
            ChannelSlowControl(
                is_packet_mode=False,
                delays=[0, 0, 0, 0],
                is_output_delay=False,
                n_drive=[False] * params.n_channels,
                s_drive=[False] * params.n_channels,
                w_drive=[True] + [False] * (params.n_channels - 1),  # Only channel 1 from west
                e_drive=[False] * params.n_channels,
                ns_input_sel_delay=0,
                we_input_sel_delay=0,
                ns_crossbar_sel_delay=0,
                we_crossbar_sel_delay=0
            ),
            # Channel 2: static mode for east output
            ChannelSlowControl(
                is_packet_mode=False,
                delays=[0, 0, 0, 0],
                is_output_delay=False,
                n_drive=[False] * params.n_channels,
                s_drive=[False] * params.n_channels,
                w_drive=[False] * params.n_channels,
                e_drive=[False, False, True] + [False] * (params.n_channels - 3),  # Only channel 2 to east
                ns_input_sel_delay=0,
                we_input_sel_delay=0,
                ns_crossbar_sel_delay=0,
                we_crossbar_sel_delay=0
            )
        ] + [ChannelSlowControl.default(params) for _ in range(3, params.n_channels)],  # Remaining channels as default
        general=GeneralSlowControl.default()
    )
    
    # Pack general config first, then all channels
    config_words = []
    config_words.extend(mixed_config.general.to_words(params))
    for channel_config in mixed_config.channels:
        config_words.extend(channel_config.to_words(params))
    
    # Calculate control memory start address (after DDM space)
    ddm_max_addr = params.ddm_bank_depth * params.ddm_n_banks
    control_mem_start = 1 << (ddm_max_addr - 1).bit_length()  # Round up to power of 2
    
    # Create packet header targeting this lane's location (0,0)
    packet_header = PacketHeader(
        dest_x=0, dest_y=0, src_x=0, src_y=0,
        address=control_mem_start, length=len(config_words), expects_receive=True, ident=0
    )
    header = packet_header.to_word(params)
    
    # Create the configuration packet and add to queue
    config_packet = [header] + config_words
    packet_queue.append(config_packet)
    
    # Wait for packet to be sent and processed
    while packet_queue:
        await triggers.RisingEdge(dut.clock)
    
    # Wait a few more cycles for packet processing
    for _ in range(10):
        await triggers.RisingEdge(dut.clock)
    
    # Select slow control slot 0 to use our configuration
    dut.io_nInstr_network_valid.value = 1
    dut.io_nInstr_network_bits_instrType.value = 1  # Set slow control slot
    dut.io_nInstr_network_bits_data.value = 0  # slot = 0
    await triggers.RisingEdge(dut.clock)
    dut.io_nInstr_network_valid.value = 0
    await triggers.RisingEdge(dut.clock)


@cocotb.test()
async def lane_test(dut: HierarchyObject) -> None:
    """Main test for Lane module functionality."""
    # Configure logging for the cocotb test
    test_utils.configure_logging_sim('INFO')
    
    # Read test parameters
    test_params = test_utils.read_params()
    rnd = Random(test_params['seed'])
    params_dict = test_params['params']
    params = FMVPUParams.from_dict(params_dict)
    
    # Initialize all inputs to safe values
    dut.io_nInstr_compute_valid.value = 0
    dut.io_nInstr_loadstore_valid.value = 0
    dut.io_nInstr_network_valid.value = 0
    dut.io_nInstr_sendreceive_valid.value = 0
    dut.io_instrDelay.value = 0
    dut.io_thisLoc_x.value = 1
    dut.io_thisLoc_y.value = 1
    
    # Initialize bus interfaces
    for i in range(params.n_channels):
        getattr(dut, f'io_nI_{i}_valid').value = 0
        getattr(dut, f'io_sI_{i}_valid').value = 0
        getattr(dut, f'io_eI_{i}_valid').value = 0
        getattr(dut, f'io_wI_{i}_valid').value = 0
        # In static mode, always provide tokens (ignore flow control)
        getattr(dut, f'io_nO_{i}_token').value = 1
        getattr(dut, f'io_sO_{i}_token').value = 1
        getattr(dut, f'io_eO_{i}_token').value = 1
        getattr(dut, f'io_wO_{i}_token').value = 1

    # Start clock and timeout watchdog
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    cocotb.start_soon(timeout_watchdog(dut, 1000))  # Increased timeout for safety
    
    # Apply reset sequence
    await reset_dut(dut)
    
    # Start error monitor
    cocotb.start_soon(error_monitor(dut, params))
    
    # Create packet queues and handlers for tests
    tolane_queues = [collections.deque() for i in range(params.n_channels)]
    fromlane_queues = [collections.deque() for i in range(params.n_channels)]
    packet_senders = [PacketSender(dut, 'w', None, channel, tolane_queues[channel]) for channel in range(params.n_channels)]
    packet_receivers = [PacketReceiver(dut, 'w', None, channel, fromlane_queues[channel], params) for channel in range(params.n_channels)]
    
    # Run test scenarios
    receive_channel = 1
    send_channel = 2
    await send_and_receive(dut, rnd, params, packet_senders[receive_channel], packet_receivers[send_channel], send_channel)
    await send_and_receive_swap_order(dut, rnd, params, packet_senders[receive_channel], packet_receivers[send_channel], send_channel)
    
    # Clean up packet handlers
    for i in range(params.n_channels):
        packet_senders[i].cancel()
        packet_receivers[i].cancel()


def test_lane(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    # Use the single concatenated Verilog file
    filenames = [verilog_file]
    
    toplevel = 'Lane'
    module = 'fmvpu.lane.test_lane'
    
    with open(params_file, 'r', encoding='utf-8') as params_f:
        design_params = json.loads(params_f.read())
    
    test_params = {
        'seed': seed,
        'params': design_params,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_lane(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        params_filename = os.path.join(this_dir, 'params.json')
        filenames = generate_rtl.generate('Lane', working_dir, [params_filename])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, 'lane_verilog.sv')
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_lane(concat_filename, params_filename, seed)


if __name__ == '__main__':
    test_utils.configure_logging_pre_sim('INFO')
    
    if len(sys.argv) == 3:
        # Called from Bazel with verilog_file and params_file
        verilog_file = sys.argv[1]
        params_file = sys.argv[2]
        
        test_lane(verilog_file, params_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_lane()
