import cocotb
from cocotb.clock import Clock
from zamlet.test_utils import rising_edge


@cocotb.test()
async def cvc_smoke_test(dut):
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    dut.reset.value = 1
    dut.data_in.value = 0
    await rising_edge(dut.clock)

    dut.reset.value = 0
    dut.data_in.value = 0x5A
    await rising_edge(dut.clock)
    await rising_edge(dut.clock)

    assert dut.data_out.value == 0x5A
