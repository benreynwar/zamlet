# WARNING: This file was created by Claude Code with negligible human oversight.
# It is not a test that should be trusted.

import os
import sys
import tempfile
from typing import Optional

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from fmvpu import generate_rtl
from fmvpu import test_utils

this_dir = os.path.abspath(os.path.dirname(__file__))


@cocotb.test()
async def rff_basic_reset_test(dut: HierarchyObject) -> None:
    """Basic test that resets the RFF module and waits 10 cycles."""
    print("Starting basic RFF reset test...")
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    
    # Initialize inputs
    dut.io_startValid.value = 0
    dut.io_startPC.value = 0
    dut.io_instrValid.value = 0
    dut.io_instruction.value = 0
    dut.io_aluReady.value = 1
    dut.io_ldstReady.value = 1
    dut.io_packetsReady.value = 1
    
    # Initialize write inputs
    for i in range(3):  # 3 write ports
        getattr(dut, f'io_writeInputs_{i}_valid').value = 0
        getattr(dut, f'io_writeInputs_{i}_value').value = 0
        getattr(dut, f'io_writeInputs_{i}_address_regAddr').value = 0
        getattr(dut, f'io_writeInputs_{i}_address_writeIdent').value = 0
    
    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    
    # Wait 10 cycles
    for cycle in range(10):
        await triggers.RisingEdge(dut.clock)
    
    print("Basic reset test completed successfully!")


def test_rff_basic(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = 'RegisterFileAndFriends'
    module = 'fmvpu.lane.test_rff_basic'
    
    test_params = {
        'seed': seed,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_rff_basic(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Find the lane config file
        config_file = os.path.join(os.path.dirname(this_dir), '..', '..', 'configs', 'lane_default.json')
        config_file = os.path.abspath(config_file)
        
        # Generate RFF with lane parameters
        filenames = generate_rtl.generate('RegisterFileAndFriends', working_dir, [config_file])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, 'rff_verilog.sv')
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_rff_basic(concat_filename, seed)


if __name__ == '__main__':
    test_utils.configure_logging_pre_sim('INFO')
    
    if len(sys.argv) >= 2:
        # Called from Bazel with verilog_file
        verilog_file = sys.argv[1]
        test_rff_basic(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_rff_basic()