import os
import subprocess
import tempfile

import cocotb
from cocotb import triggers, clock
from cocotb_tools.runner import get_runner

from fmpvu import generate_rtl

this_dir = os.path.abspath(os.path.dirname(__file__))


@cocotb.test()
async def network_basic_test(dut):
    cocotb.start_soon(clock.Clock(dut.clock, 1, 'ns').start())
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    
    # Initialize inputs
    dut.configValid.value = 0
    dut.configIsPacketMode.value = 0
    dut.configDelay.value = 0
    dut.fromDRF_valid.value = 0
    dut.fromDRF_bits.value = 0
    dut.fromDDM_valid.value = 0
    dut.fromDDM_bits.value = 0

    # Initialize bus inputs
    for direction in range(4):
        for bus in range(2):  # assuming 2 buses from params
            getattr(dut, f'inputs_{direction}_{bus}_valid').value = 0
            getattr(dut, f'inputs_{direction}_{bus}_bits_header').value = 0
            getattr(dut, f'inputs_{direction}_{bus}_bits_bits').value = 0
            getattr(dut, f'outputs_{direction}_{bus}_token').value = 0
    
    # Initialize control signals
    for bus in range(2):
        getattr(dut, f'control_nsInputSel_{bus}').value = 0
        getattr(dut, f'control_weInputSel_{bus}').value = 0
        getattr(dut, f'control_nsCrossbarSel_{bus}').value = 0
        getattr(dut, f'control_weCrossbarSel_{bus}').value = 0
    dut.control_drfSel.value = 0
    dut.control_ddmSel.value = 0
    
    await triggers.RisingEdge(dut.clock)


@cocotb.test()
async def network_packet_mode_test(dut):
    cocotb.start_soon(clock.Clock(dut.clock, 1, 'ns').start())
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    
    # Configure for packet mode
    dut.configValid.value = 1
    dut.configIsPacketMode.value = 1
    dut.configDelay.value = 2
    await triggers.RisingEdge(dut.clock)
    dut.configValid.value = 0
    
    # Test that node is in packet mode
    await triggers.RisingEdge(dut.clock)


@cocotb.test()
async def network_delay_mode_test(dut):
    cocotb.start_soon(clock.Clock(dut.clock, 1, 'ns').start())
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    
    # Configure for delay mode
    dut.configValid.value = 1
    dut.configIsPacketMode.value = 0
    dut.configDelay.value = 3
    await triggers.RisingEdge(dut.clock)
    dut.configValid.value = 0
    
    # Test that node is in delay mode
    await triggers.RisingEdge(dut.clock)


def test_proc(temp_dir=None):
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        sim = 'verilator'
        runner = get_runner(sim)
        params_filename = os.path.join(this_dir, 'params.json')

        filenames = generate_rtl.generate('NetworkNode', working_dir, [params_filename])
        runner.build(
            sources=filenames,
            hdl_toplevel='NetworkNode',
            always=True,
            waves=True,
            build_args=['--trace', '--trace-structs'],
            )
        runner.test(hdl_toplevel='NetworkNode', test_module='test_network', waves=True)


if __name__ == '__main__':
    test_proc(os.path.abspath('deleteme'))
