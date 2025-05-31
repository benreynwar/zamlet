import os
import json
import tempfile
from typing import Optional

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

import generate_rtl
import test_utils
from params import FMPVUParams

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
    dut.io_configValid.value = 0
    dut.io_configIsPacketMode.value = 0
    dut.io_configDelay.value = 0
    dut.io_fromDRF_valid.value = 0
    dut.io_fromDRF_bits.value = 0
    dut.io_fromDDM_valid.value = 0
    dut.io_fromDDM_bits.value = 0

    # Read test parameters to get n_channels
    test_params = test_utils.read_params()
    params_dict = test_params['params']
    params = FMPVUParams.from_dict(params_dict)
    
    # Initialize bus inputs
    for direction in range(4):
        for channel in range(params.n_channels):
            getattr(dut, f'io_inputs_{direction}_{channel}_valid').value = 0
            getattr(dut, f'io_inputs_{direction}_{channel}_bits_header').value = 0
            getattr(dut, f'io_inputs_{direction}_{channel}_bits_bits').value = 0
            getattr(dut, f'io_outputs_{direction}_{channel}_token').value = 0
    
    # Initialize control signals
    for channel in range(params.n_channels):
        getattr(dut, f'io_control_nsInputSel_{channel}').value = 0
        getattr(dut, f'io_control_weInputSel_{channel}').value = 0
        getattr(dut, f'io_control_nsCrossbarSel_{channel}').value = 0
        getattr(dut, f'io_control_weCrossbarSel_{channel}').value = 0
    dut.io_control_drfSel.value = 0
    dut.io_control_ddmSel.value = 0
    
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
    
    # Configure for packet mode
    dut.io_configValid.value = 1
    dut.io_configIsPacketMode.value = 1
    dut.io_configDelay.value = 2
    await triggers.RisingEdge(dut.clock)
    dut.io_configValid.value = 0
    
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
    
    # Configure for delay mode
    dut.io_configValid.value = 1
    dut.io_configIsPacketMode.value = 0
    dut.io_configDelay.value = 3
    await triggers.RisingEdge(dut.clock)
    dut.io_configValid.value = 0
    
    # Test that node is in delay mode
    await triggers.RisingEdge(dut.clock)


def test_network_main(temp_dir: Optional[str] = None) -> None:
    """Generate RTL and run the NetworkNode test."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        params_filename = os.path.join(this_dir, 'params.json')
        filenames = generate_rtl.generate('NetworkNode', working_dir, [params_filename])
        toplevel = 'NetworkNode'
        module = 'test_network'
        
        with open(params_filename, 'r', encoding='utf-8') as params_f:
            design_params = json.loads(params_f.read())
        
        test_params = {
            'seed': 0,
            'params': design_params,
        }
        
        test_utils.run_test(working_dir, filenames, test_params, toplevel, module)


if __name__ == '__main__':
    test_network_main(temp_dir=os.path.abspath('deleteme'))
