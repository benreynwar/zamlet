import os
import json
from random import Random
import collections
import tempfile
from typing import Any, Deque, Optional

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from fmpvu import generate_rtl, test_utils
from fmpvu.params import FMPVUParams

this_dir = os.path.abspath(os.path.dirname(__file__))


async def process_to_lane(dut: HierarchyObject, tolane_queue: Deque[int]) -> None:
    """Drive data from queue to the lane's west input interface."""
    while True:
        if tolane_queue:
            dut.io_wI_0_valid.value = 1
            dut.io_wI_0_bits_bits.value = tolane_queue.popleft()
            dut.io_wI_0_bits_header.value = 0
        else:
            dut.io_wI_0_valid.value = 0
        await triggers.RisingEdge(dut.clock)


async def process_from_lane(dut: HierarchyObject, fromlane_queue: Deque[int]) -> None:
    """Collect data from the lane's east output interface."""
    while True:
        await triggers.ReadOnly()
        if dut.io_eO_1_valid.value:
            fromlane_queue.append(dut.io_eO_1_bits_bits.value)
        await triggers.RisingEdge(dut.clock)
        # Set token after the ReadOnly phase
        if dut.io_eO_1_valid.value:
            dut.io_eO_1_token.value = 1
        else:
            dut.io_eO_1_token.value = 0


def submit_send(dut: HierarchyObject, length: int, address: int) -> None:
    """Submit a send instruction to the lane."""
    dut.io_nInstr_sendreceive_valid.value = 1
    dut.io_nInstr_sendreceive_bits_mode.value = 0
    dut.io_nInstr_sendreceive_bits_length.value = length
    dut.io_nInstr_sendreceive_bits_addr.value = address


def submit_receive(dut: HierarchyObject, length: int, address: int) -> None:
    """Submit a receive instruction to the lane."""
    dut.io_nInstr_sendreceive_valid.value = 1
    dut.io_nInstr_sendreceive_bits_mode.value = 1
    dut.io_nInstr_sendreceive_bits_length.value = length
    dut.io_nInstr_sendreceive_bits_addr.value = address


def clear_sendreceive(dut: HierarchyObject) -> None:
    """Clear the send/receive instruction."""
    dut.io_nInstr_sendreceive_valid.value = 0


def submit_load(dut: HierarchyObject, reg: int, addr: int) -> None:
    """Submit a load instruction (register -> memory)."""
    dut.io_nInstr_loadstore_valid.value = 1
    dut.io_nInstr_loadstore_bits_mode.value = 0  # Load mode: register -> memory
    dut.io_nInstr_loadstore_bits_reg.value = reg
    dut.io_nInstr_loadstore_bits_addr.value = addr


def submit_store(dut: HierarchyObject, reg: int, addr: int) -> None:
    """Submit a store instruction (memory -> register)."""
    dut.io_nInstr_loadstore_valid.value = 1
    dut.io_nInstr_loadstore_bits_mode.value = 1  # Store mode: memory -> register
    dut.io_nInstr_loadstore_bits_reg.value = reg
    dut.io_nInstr_loadstore_bits_addr.value = addr


def clear_loadstore(dut: HierarchyObject) -> None:
    """Clear the load/store instruction."""
    dut.io_nInstr_loadstore_valid.value = 0
    

async def send_and_receive(dut: HierarchyObject, rnd: Random, params: Any) -> None:
    """
    Test basic send and receive functionality.
    
    Send in two words using the Receive instruction.
    Send out two words using the Send instruction.
    Check that they match.
    """
    test_data = [0x1234, 0x5678]
    tolane_queue: Deque[int] = collections.deque()
    fromlane_queue: Deque[int] = collections.deque()
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
    received_data = [fromlane_queue.popleft() for _ in range(2)]
    assert test_data == received_data, f"Expected {test_data}, got {received_data}"
    tolane_task.kill()
    fromlane_task.kill()


async def send_and_receive_swap_order(dut: HierarchyObject, rnd: Random, params: Any) -> None:
    """
    Test data manipulation through register file.
    
    Send in two words using the Receive instruction.
    Load the two words into registers.
    Store them back to the data memory but in the opposite order.
    Send out two words using the Send instruction.
    """
    test_data = [0x1234, 0x5678]
    expected_data = [0x5678, 0x1234]  # swapped order
    tolane_queue: Deque[int] = collections.deque()
    fromlane_queue: Deque[int] = collections.deque()
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
    received_data = [fromlane_queue.popleft() for _ in range(2)]
    assert expected_data == received_data, f"Expected {expected_data}, got {received_data}"

    tolane_task.kill()
    fromlane_task.kill()


async def timeout_watchdog(dut: HierarchyObject, max_cycles: int) -> None:
    """Timeout watchdog to prevent infinite test execution."""
    count = 0
    while True:
        await triggers.RisingEdge(dut.clock)
        assert count < max_cycles, f"Test timed out after {max_cycles} cycles"
        count += 1


async def reset_dut(dut: HierarchyObject) -> None:
    """Apply reset sequence to DUT."""
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)


@cocotb.test()
async def lane_test(dut: HierarchyObject) -> None:
    """Main test for Lane module functionality."""
    # Read test parameters
    test_params = test_utils.read_params()
    rnd = Random(test_params['seed'])
    params_dict = test_params['params']
    params = FMPVUParams.from_dict(params_dict)
    
    # Initialize all inputs to safe values
    dut.io_nInstr_compute_valid.value = 0
    dut.io_nInstr_loadstore_valid.value = 0
    dut.io_nInstr_network_valid.value = 0
    dut.io_nInstr_sendreceive_valid.value = 0
    dut.io_instrDelay.value = 0
    dut.io_thisLoc_x.value = 0
    dut.io_thisLoc_y.value = 0
    dut.io_nConfig_configValid.value = 0
    dut.io_nConfig_configIsPacketMode.value = 1
    dut.io_nConfig_configDelay.value = 0
    
    # Initialize bus interfaces
    for i in range(params.n_buses):
        getattr(dut, f'io_nI_{i}_valid').value = 0
        getattr(dut, f'io_sI_{i}_valid').value = 0
        getattr(dut, f'io_eI_{i}_valid').value = 0
        getattr(dut, f'io_wI_{i}_valid').value = 0

    # Start clock and timeout watchdog
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    cocotb.start_soon(timeout_watchdog(dut, 1000))  # Increased timeout for safety
    
    # Apply reset sequence
    await reset_dut(dut)
    
    # Configure network for crossbar mode
    dut.io_nConfig_configValid.value = 1
    dut.io_nConfig_configIsPacketMode.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.io_nConfig_configValid.value = 0
    await triggers.RisingEdge(dut.clock)
    
    # Run test scenarios
    await send_and_receive(dut, rnd, params)
    await send_and_receive_swap_order(dut, rnd, params)


def test_lane(temp_dir: Optional[str] = None) -> None:
    """Main test procedure to generate RTL and run cocotb test."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
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
    test_lane(os.path.abspath('deleteme'))
