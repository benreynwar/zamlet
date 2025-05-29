import os
import subprocess
from random import Random
from collections import deque
import tempfile

import cocotb
from cocotb import triggers, clock
from cocotb_tools.runner import get_runner

from fmpvu import generate_rtl

this_dir = os.path.abspath(os.path.dirname(__file__))


@cocotb.test()
async def adjustable_test(dut):
    seed = 0
    rnd = Random(seed)
    width = len(dut.input_bits.value)
    delay_width = len(dut.delay.value)
    cocotb.start_soon(clock.Clock(dut.clock, 1, 'ns').start())
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    for i in range(20):
        await triggers.RisingEdge(dut.clock)
        delay = rnd.getrandbits(delay_width)
        dut.delay.value = delay
        valids = deque([None] * delay)
        datas = deque([None] * delay)
        for j in range(delay*4+10):
            valid = rnd.getrandbits(1)
            data = rnd.getrandbits(width)
            valids.append(valid)
            datas.append(data)
            dut.input_valid.value = valid
            dut.input_bits.value = data
            await triggers.ReadOnly()
            print(datas)
            expected_valid = valids.popleft()
            expected_data = datas.popleft()
            if expected_valid is not None:
                assert expected_valid == dut.output_valid.value
                if expected_valid:
                    assert expected_data == dut.output_bits.value
            await triggers.RisingEdge(dut.clock)
        for i in range(delay):
            dut.input_valid.value = 0
            dut.input_bits.value = 0
            await triggers.RisingEdge(dut.clock)


def test_proc(max_delay=3, width=4, temp_dir=None):
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        sim = 'verilator'
        runner = get_runner(sim)
        params_filename = os.path.join(this_dir, 'params.json')
        filenames = generate_rtl.generate('AdjustableDelay', working_dir, [str(max_delay), str(width)])
        runner.build(
            sources=filenames,
            hdl_toplevel='AdjustableDelay',
            always=True,
            waves=True,
            build_args=['--trace', '--trace-structs'],
            )
        runner.test(hdl_toplevel='AdjustableDelay', test_module='test_adjustable_delay', waves=True)


if __name__ == '__main__':
    test_proc(os.path.abspath('deleteme'))
