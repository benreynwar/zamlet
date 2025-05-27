import os
import json
from random import Random
import collections

import cocotb
from cocotb import triggers, clock

from fvpu import generate_rtl, test_utils
from fvpu.params import FVPUParams

this_dir = os.path.abspath(os.path.dirname(__file__))


async def process_to_lane(dut, tolane_queue):
    while True:
        if tolane_queue:
            dut.wI_0_valid.value = 1
            dut.wI_0_bits_bits.value = tolane_queue.popleft()
            dut.wI_0_bits_header.value = 0
        else:
            dut.wI_0_valid.value = 0
        await triggers.RisingEdge(dut.clock)


async def process_from_lane(dut, fromlane_queue):
    while True:
        await triggers.ReadOnly()
        if dut.eO_1_valid.value:
            fromlane_queue.append(dut.eO_1_bits_bits.value)
        await triggers.RisingEdge(dut.clock)
        # Set token after the ReadOnly phase
        if dut.eO_1_valid.value:
            dut.eO_1_token.value = 1
        else:
            dut.eO_1_token.value = 0


def submit_send(dut, length, address):
    dut.nInstr_sendreceive_valid.value = 1
    dut.nInstr_sendreceive_bits_mode.value = 0
    dut.nInstr_sendreceive_bits_length.value = length
    dut.nInstr_sendreceive_bits_addr.value = address


def submit_receive(dut, length, address):
    dut.nInstr_sendreceive_valid.value = 1
    dut.nInstr_sendreceive_bits_mode.value = 1
    dut.nInstr_sendreceive_bits_length.value = length
    dut.nInstr_sendreceive_bits_addr.value = address


def clear_sendreceive(dut):
    dut.nInstr_sendreceive_valid.value = 0


def submit_load(dut, reg, addr):
    """Load from register to memory address"""
    dut.nInstr_loadstore_valid.value = 1
    dut.nInstr_loadstore_bits_mode.value = 0  # Load mode: register -> memory
    dut.nInstr_loadstore_bits_reg.value = reg
    dut.nInstr_loadstore_bits_addr.value = addr


def submit_store(dut, reg, addr):
    """Store from memory address to register"""
    dut.nInstr_loadstore_valid.value = 1
    dut.nInstr_loadstore_bits_mode.value = 1  # Store mode: memory -> register
    dut.nInstr_loadstore_bits_reg.value = reg
    dut.nInstr_loadstore_bits_addr.value = addr


def clear_loadstore(dut):
    dut.nInstr_loadstore_valid.value = 0
    

async def send_and_receive(dut, rnd, params):
    """
    Send in two words using the Receive instruction.
    Send out two words using the Send instruction.
    Check that they match.
    """
    test_data = [0x1234, 0x5678]
    tolane_queue = collections.deque()
    fromlane_queue = collections.deque()
    tolane_task = cocotb.start_soon(process_to_lane(dut, tolane_queue))
    fromlane_task = cocotb.start_soon(process_from_lane(dut, fromlane_queue))
    submit_receive(dut, 2, 0)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut)
    tolane_queue += test_data
    while tolane_queue:
        await triggers.RisingEdge(dut.clock)
    submit_send(dut, 2, 0)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut)
    while len(fromlane_queue) < 2:
        await triggers.RisingEdge(dut.clock)
    received_data = [fromlane_queue.popleft() for i in range(2)]
    assert test_data == received_data
    tolane_task.kill()
    fromlane_task.kill()


async def send_and_receive_swap_order(dut, rnd, params):
    """
    Send in two words using the Receive instruction.
    Load the two words into registers
    Store them back to the data memory but in the opposite order.
    Send out two words using the Send instruction.
    """
    test_data = [0x1234, 0x5678]
    expected_data = [0x5678, 0x1234]  # swapped order
    tolane_queue = collections.deque()
    fromlane_queue = collections.deque()
    tolane_task = cocotb.start_soon(process_to_lane(dut, tolane_queue))
    fromlane_task = cocotb.start_soon(process_from_lane(dut, fromlane_queue))
    
    # Step 1: Receive two words into memory (addresses 0 and 1)
    submit_receive(dut, 2, 0)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut)
    tolane_queue += test_data

    while tolane_queue:
        await triggers.RisingEdge(dut.clock)
    await triggers.RisingEdge(dut.clock)
    
    # Step 2: Store word from memory address 0 into register 0
    submit_store(dut, 0, 0)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut)
    await triggers.RisingEdge(dut.clock)  # Wait for store to complete
    
    # Step 3: Store word from memory address 1 into register 1
    submit_store(dut, 1, 1)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut)
    await triggers.RisingEdge(dut.clock)  # Wait for store to complete
    
    # Step 4: Load register 0 to memory address 1 (swap)
    submit_load(dut, 0, 1)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut)
    await triggers.RisingEdge(dut.clock)  # Wait for load to complete
    
    # Step 5: Load register 1 to memory address 0 (swap)
    submit_load(dut, 1, 0)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut)
    await triggers.RisingEdge(dut.clock)  # Wait for load to complete
    
    # Step 6: Send the swapped data out
    submit_send(dut, 2, 0)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut)
    while len(fromlane_queue) < 2:
        await triggers.RisingEdge(dut.clock)
    received_data = [fromlane_queue.popleft() for i in range(2)]
    assert expected_data == received_data

    tolane_task.kill()
    fromlane_task.kill()


async def timeout(dut, max_cycles):
    count = 0
    while True:
        await triggers.RisingEdge(dut.clock)
        assert count < max_cycles
        count += 1


@cocotb.test()
async def lane_test(dut):
    test_params = test_utils.read_params()
    rnd = Random(test_params['seed'])
    params_dict = test_params['params']
    params = FVPUParams.from_dict(params_dict)
    dut.nInstr_compute_valid.value = 0
    dut.nInstr_loadstore_valid.value = 0
    dut.nInstr_network_valid.value = 0
    dut.nInstr_sendreceive_valid.value = 0
    dut.instrDelay.value = 0
    dut.thisLoc_x.value = 0
    dut.thisLoc_y.value = 0
    dut.configValid.value = 0
    dut.configIsPacketMode.value = 1
    dut.configDelay.value = 0
    for i in range(params.n_buses):
        dut.nI_0_valid.value = 0
        dut.sI_0_valid.value = 0
        dut.eI_0_valid.value = 0
        dut.wI_0_valid.value = 0

    cocotb.start_soon(clock.Clock(dut.clock, 1, 'ns').start())
    cocotb.start_soon(timeout(dut, 100))
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.configValid.value = 1
    dut.configIsPacketMode.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.configValid.value = 0
    await triggers.RisingEdge(dut.clock)
    
    await send_and_receive(dut, rnd, params)
    await send_and_receive_swap_order(dut, rnd, params)


def test_proc():
    working_dir = os.path.abspath('deleteme')
    params_filename = os.path.join(this_dir, 'params.json')
    filenames = generate_rtl.generate('Lane', working_dir, [params_filename])
    toplevel = 'Lane'
    module = 'test_lane'
    with open(params_filename, 'r', encoding='utf-8') as params_f:
        design_params = json.loads(params_f.read())
    test_params = {
        'seed': 0,
        'params': design_params,
        }
    test_utils.run_test(working_dir, filenames, test_params, toplevel, module)


if __name__ == '__main__':
    test_proc()
