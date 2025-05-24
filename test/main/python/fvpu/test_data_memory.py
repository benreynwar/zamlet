import os
from random import Random
import json

import cocotb
from cocotb import triggers, clock
from cocotb_tools.runner import get_runner

from fvpu import generate_rtl, test_utils
from fvpu.test_utils import clog2

this_dir = os.path.abspath(os.path.dirname(__file__))



@cocotb.test()
async def data_memory_test(dut):
    params = test_utils.read_params()
    seed = params['seed']
    rnd = Random(seed)
    cocotb.start_soon(clock.Clock(dut.clock, 1, 'ns').start())
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0


def test_proc(width=4, depth=8, n_banks=2):
    working_dir = os.path.abspath('deleteme')
    filenames = generate_rtl.generate(
            'DataMemory', working_dir, [str(width), str(depth), str(n_banks)])
    test_params = {
        'seed': 0,
        'width': width,
        'depth': depth,
        'n_banks': n_banks,
        }
    toplevel = 'DataMemory'
    module = 'test_data_memory'
    test_utils.run_test(working_dir, filenames, test_params, toplevel, module)


if __name__ == '__main__':
    test_proc()
