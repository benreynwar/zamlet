import os
import sys
import json
import tempfile
from random import Random
from typing import Optional
 
import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from fmvpu import generate_rtl
from fmvpu import test_utils
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


def test_data_memory(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    # Use the single concatenated Verilog file
    filenames = [verilog_file]
    
    toplevel = 'DataMemory'
    module = 'fmvpu.data_memory.test_data_memory'
    
    test_params = {
        'seed': seed,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_data_memory(width: int = 32, depth: int = 16, n_banks: int = 2, temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        filenames = generate_rtl.generate('DataMemory', working_dir, [str(width), str(depth), str(n_banks)])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, 'data_memory_verilog.sv')
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_data_memory(concat_filename, seed)


if __name__ == '__main__':
    test_utils.configure_logging_pre_sim('INFO')
    
    if len(sys.argv) == 2:
        # Called from Bazel with verilog_file
        verilog_file = sys.argv[1]
        
        test_data_memory(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_data_memory()
