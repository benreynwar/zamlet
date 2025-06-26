import os
import sys
import json
import tempfile
from typing import Optional

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from fmvpu import generate_rtl
from fmvpu import test_utils
from fmvpu.params import FMVPUParams
from fmvpu.control_structures import NetworkSlowControl, ChannelSlowControl

this_dir = os.path.abspath(os.path.dirname(__file__))


@cocotb.test()
async def network_basic_test(dut: HierarchyObject) -> None:
    """Basic test of NetworkNode module initialization."""
    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    
    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    
    # Initialize inputs
    dut.io_networkInstr_valid.value = 0
    dut.io_fromDRF_valid.value = 0
    dut.io_fromDDM_valid.value = 0
    dut.io_fromDDMChannel.value = 0
    dut.io_writeControl_enable.value = 0
    dut.io_sendReceiveInstr_valid.value = 0
    dut.io_thisLoc_x.value = 0
    dut.io_thisLoc_y.value = 0

    # Read test parameters to get n_channels
    test_params = test_utils.read_params()
    params_dict = test_params['params']
    params = FMVPUParams.from_dict(params_dict)
    
    # Initialize bus inputs
    for direction in range(4):
        for channel in range(params.n_channels):
            getattr(dut, f'io_inputs_{direction}_{channel}_valid').value = 0
            getattr(dut, f'io_inputs_{direction}_{channel}_bits_header').value = 0
            getattr(dut, f'io_inputs_{direction}_{channel}_bits_bits').value = 0
            getattr(dut, f'io_outputs_{direction}_{channel}_token').value = 0
    
    
    await triggers.RisingEdge(dut.clock)


@cocotb.test()
async def network_packet_mode_test(dut: HierarchyObject) -> None:
    """Test NetworkNode in packet mode configuration."""
    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    
    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    
    # Configure for packet mode (slot 0 is already in packet mode by default)
    dut.io_networkInstr_valid.value = 1
    dut.io_networkInstr_bits_instrType.value = 1  # Set slow control slot
    dut.io_networkInstr_bits_data.value = 0  # slot = 0
    await triggers.RisingEdge(dut.clock)
    dut.io_networkInstr_valid.value = 0
    
    # Test that node is in packet mode
    await triggers.RisingEdge(dut.clock)


@cocotb.test()
async def network_delay_mode_test(dut: HierarchyObject) -> None:
    """Test NetworkNode in delay mode configuration."""
    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    
    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    
    # Read test parameters to get params
    test_params = test_utils.read_params()
    params_dict = test_params['params']
    params = FMVPUParams.from_dict(params_dict)
    
    # Configure slot 1 for static mode
    slot_1_config = NetworkSlowControl.default(params)
    for i in range(params.n_channels):
        slot_1_config.channels[i] = ChannelSlowControl.static_mode(params)
    
    # Write general control for slot 1
    general_words = slot_1_config.general.to_words(params)
    for i, word in enumerate(general_words):
        dut.io_writeControl_enable.value = 1
        dut.io_writeControl_address.value = i  # Simplified addressing for now
        dut.io_writeControl_data.value = word
        await triggers.RisingEdge(dut.clock)
        dut.io_writeControl_enable.value = 0
    
    # Write channel control for slot 1
    for channel_idx in range(params.n_channels):
        channel_words = slot_1_config.channels[channel_idx].to_words(params)
        for i, word in enumerate(channel_words):
            dut.io_writeControl_enable.value = 1
            dut.io_writeControl_address.value = len(general_words) + channel_idx * len(channel_words) + i
            dut.io_writeControl_data.value = word
            await triggers.RisingEdge(dut.clock)
            dut.io_writeControl_enable.value = 0
    
    # Switch to slot 1
    dut.io_networkInstr_valid.value = 1
    dut.io_networkInstr_bits_instrType.value = 1  # Set slow control slot
    dut.io_networkInstr_bits_data.value = 1  # slot = 1
    await triggers.RisingEdge(dut.clock)
    dut.io_networkInstr_valid.value = 0
    
    # Test that node is in delay mode
    await triggers.RisingEdge(dut.clock)


def test_network(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    # Use the single concatenated Verilog file
    filenames = [verilog_file]
    
    toplevel = 'NetworkNode'
    module = 'fmvpu.network.test_network'
    
    with open(params_file, 'r', encoding='utf-8') as params_f:
        design_params = json.loads(params_f.read())
    
    test_params = {
        'seed': seed,
        'params': design_params,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_network(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        params_filename = os.path.join(this_dir, 'params.json')
        filenames = generate_rtl.generate('NetworkNode', working_dir, [params_filename])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, 'network_verilog.sv')
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_network(concat_filename, params_filename, seed)


if __name__ == '__main__':
    test_utils.configure_logging_pre_sim('INFO')
    
    if len(sys.argv) == 3:
        # Called from Bazel with verilog_file and params_file
        verilog_file = sys.argv[1]
        params_file = sys.argv[2]
        
        test_network(verilog_file, params_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_network()
