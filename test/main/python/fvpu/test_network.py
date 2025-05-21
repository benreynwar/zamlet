import os
import subprocess

import cocotb
from cocotb import triggers, clock
from cocotb_tools.runner import get_runner

from fvpu import generate_rtl

this_dir = os.path.abspath(os.path.dirname(__file__))


@cocotb.test()
async def network_test(dut):
    cocotb.start_soon(clock.Clock(dut.clock, 1, 'ns').start())
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0


def test_proc():
    sim = 'verilator'
    runner = get_runner(sim)
    working_dir = os.path.abspath('deleteme')
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
    test_proc()
