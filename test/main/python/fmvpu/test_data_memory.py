import os
import tempfile
from random import Random
from typing import Optional

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb_tools.runner import get_runner

from fmvpu import generate_rtl, test_utils
from fmvpu.test_utils import clog2

this_dir = os.path.abspath(os.path.dirname(__file__))



@cocotb.test()
async def data_memory_test(dut: HierarchyObject) -> None:
    """Test DataMemory module with read/write operations."""
    params = test_utils.read_params()
    seed = params['seed']
    rnd = Random(seed)
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    
    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)


def test_data_memory_main(width: int = 4, depth: int = 8, n_banks: int = 2, temp_dir: Optional[str] = None) -> None:
    """Generate RTL and run the DataMemory test."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
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
    test_data_memory_main(temp_dir=os.path.abspath('deleteme'))
