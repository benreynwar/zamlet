import os
import tempfile
from collections import deque
from random import Random
from typing import Deque, Optional

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb_tools.runner import get_runner

import generate_rtl

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
    seed = 0
    rnd = Random(seed)
    width = len(dut.io_input_bits.value)
    delay_width = len(dut.io_delay.value)
    
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
        delay = rnd.getrandbits(delay_width)
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


def test_adjustable_delay_main(max_delay: int = 3, width: int = 4, temp_dir: Optional[str] = None) -> None:
    """Generate RTL and run the AdjustableDelay test."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        sim = 'verilator'
        runner = get_runner(sim)
        filenames = generate_rtl.generate('AdjustableDelay', working_dir, [str(max_delay), str(width)])
        runner.build(
            sources=filenames,
            hdl_toplevel='AdjustableDelay',
            always=True,
            waves=True,
            build_args=['--trace', '--trace-structs'],
            )
        runner.test(
            hdl_toplevel='AdjustableDelay',
            test_module='test_adjustable_delay',
            waves=True
        )


if __name__ == '__main__':
    test_adjustable_delay_main(temp_dir=os.path.abspath('deleteme'))
