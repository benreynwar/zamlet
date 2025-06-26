import os
import sys
import tempfile
from collections import deque
from random import Random
from typing import Deque, Optional

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb_tools.runner import get_runner

from fmvpu import generate_rtl
from fmvpu import test_utils

this_dir = os.path.abspath(os.path.dirname(__file__))


async def error_monitor(dut: HierarchyObject) -> None:
    """Monitor error signals and assert if any errors occur."""
    while True:
        await triggers.ReadOnly()
        assert dut.io_errors_dataOverwrite.value == 0, "dataOverwrite error detected"
        await triggers.RisingEdge(dut.clock)

@cocotb.test()
async def adjustable_delay_test(dut: HierarchyObject) -> None:
    """Test AdjustableDelay module with various delay values and input patterns."""
    params = test_utils.read_params()
    seed = params['seed']
    rnd = Random(seed)
    width = params['width']
    max_delay = params['max_delay']
    delay_width = len(dut.io_delay.value)  # Still infer this from hardware
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    
    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    
    # Start error monitoring after reset
    cocotb.start_soon(error_monitor(dut))
    for i in range(20):
        await triggers.RisingEdge(dut.clock)
        delay = rnd.randint(0, max_delay)
        dut.io_delay.value = delay
        valids: Deque[Optional[int]] = deque([None] * delay)
        datas: Deque[Optional[int]] = deque([None] * delay)
        for j in range(delay*4+10):
            valid = rnd.getrandbits(1)
            data = rnd.getrandbits(width)
            valids.append(valid)
            datas.append(data)
            dut.io_input_valid.value = valid
            dut.io_input_bits.value = data
            await triggers.ReadOnly()
            
            expected_valid = valids.popleft()
            expected_data = datas.popleft()
            if expected_valid is not None:
                assert expected_valid == dut.io_output_valid.value, f"Expected valid {expected_valid}, got {dut.io_output_valid.value}"
                if expected_valid:
                    assert expected_data == dut.io_output_bits.value, f"Expected data {expected_data}, got {dut.io_output_bits.value}"
            await triggers.RisingEdge(dut.clock)
        for i in range(delay):
            dut.io_input_valid.value = 0
            dut.io_input_bits.value = 0
            await triggers.RisingEdge(dut.clock)


def test_adjustable_delay(verilog_file: str, max_delay: int, width: int, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    # Use the single concatenated Verilog file
    filenames = [verilog_file]
    
    toplevel = 'AdjustableDelay'
    module = 'fmvpu.adjustable_delay.test_adjustable_delay'
    
    test_params = {
        'seed': seed,
        'max_delay': max_delay,
        'width': width,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_adjustable_delay(max_delay: int = 3, width: int = 4, temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        filenames = generate_rtl.generate('AdjustableDelay', working_dir, [str(max_delay), str(width)])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, 'adjustable_delay.sv')
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_adjustable_delay(concat_filename, max_delay, width, seed)


if __name__ == '__main__':
    test_utils.configure_logging_pre_sim('INFO')
    
    if len(sys.argv) == 4:
        # Called from Bazel with verilog_file, max_delay, width
        verilog_file = sys.argv[1]
        max_delay = int(sys.argv[2])
        width = int(sys.argv[3])
        
        test_adjustable_delay(verilog_file, max_delay, width)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_adjustable_delay()
