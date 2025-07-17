import os
import sys
import tempfile
from typing import Optional
import logging
from random import Random
import json

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from fmvpu import generate_rtl
from fmvpu import test_utils
from fmvpu.lane import lane_interface
from fmvpu.lane.lane_interface import LaneInterface
from fmvpu.lane.lane_params import LaneParams
from fmvpu.lane.instructions import LoadStoreInstruction, LoadStoreModes, HaltInstruction


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def loadstore_basic_test(li: LaneInterface) -> None:
    """Test basic LOAD and STORE operations with base + offset addressing"""
    # Test storing a value and loading it back
    test_value = 0x1234567
    base_addr = 0x100
    offset = 0x4
    
    # Set up addresses and test value
    await li.write_register(1, base_addr)  # base address
    await li.write_register(2, offset)     # offset
    await li.write_register(4, test_value) # value to store
    
    program = [
        # First store the test value to memory at base + offset
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            use_base=True,
            offset_reg=2,    # offset in register 2
            src_reg=4,       # value to store from register 4
        ),
        # Then load it back from the same address
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            use_base=True,   # Use base address from register
            offset_reg=2,    # offset in register 2
            dest_reg=3,      # load result into register 3
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    await li.wait_for_program_to_run()
    
    # Verify that the loaded value matches what we stored
    loaded_value = await li.read_register(3)
    assert loaded_value == test_value, f"Store/load roundtrip failed: expected {test_value:08x}, got {loaded_value:08x}"


async def load_without_base_test(li: LaneInterface) -> None:
    """Test LOAD operation without base address (direct addressing)"""
    test_value = 0x2BCDEF0
    store_base = 0x20
    store_offset = 0x03
    direct_addr = 0x23  # Same final address as store_base + store_offset
    
    await li.write_register(3, store_base)    # base address for store
    await li.write_register(2, store_offset)  # offset for store  
    await li.write_register(1, test_value)    # value to store
    await li.write_register(4, direct_addr)   # direct address for load
    
    program = [
        # Store using base + offset addressing (known to work from basic test)
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            use_base=True,   # Use base + offset
            offset_reg=2,    # offset in register 2
            src_reg=1,       # value to store from register 3
        ),
        # Load using direct addressing (what we're testing)
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            use_base=False,  # Direct addressing - this is what we're testing
            offset_reg=4,
            dest_reg=5,      # load result into register 5
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    await li.wait_for_program_to_run()
    
    # Verify the loaded value matches what we stored
    loaded_value = await li.read_register(5)
    assert loaded_value == test_value, f"Direct addressing load failed: expected {test_value:08x}, got {loaded_value:08x}"


async def store_without_base_test(li: LaneInterface) -> None:
    """Test STORE operation without base address (direct addressing)"""
    test_value = 0x00345678
    direct_addr = 0x400
    load_base = 0x400
    load_offset = 0x0
    
    await li.write_register(1, direct_addr)  # direct address for store
    await li.write_register(2, test_value)   # value to store
    await li.write_register(3, load_base)    # base address for load
    await li.write_register(4, load_offset)  # offset for load
    
    program = [
        # Store using direct addressing (what we're testing)
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            use_base=False,  # Direct addressing - this is what we're testing
            offset_reg=0,    # no offset used
            src_reg=2,       # value to store from register 2
            dest_reg=1,      # direct address in register 1
        ),
        # Load using base + offset addressing (known to work from basic test)
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            use_base=True,   # Use base + offset
            offset_reg=4,    # offset in register 4
            src_reg=3,       # base address in register 3
            dest_reg=5,      # load result into register 5
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    await li.wait_for_program_to_run()
    
    # Verify the loaded value matches what we stored
    loaded_value = await li.read_register(5)
    assert loaded_value == test_value, f"Direct addressing store failed: expected {test_value:08x}, got {loaded_value:08x}"


async def load_store_sequence_test(li: LaneInterface) -> None:
    """Test sequence of load and store operations"""
    # Initialize registers
    await li.write_register(3, 0x500)  # base address
    await li.write_register(2, 0x0)    # offset for first location
    await li.write_register(1, 0x4)    # offset for second location
    await li.write_register(4, 0x00CDEF0)  # test value
    
    program = [
        # Store value to first location (0x500 + 0x0 = 0x500)
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            use_base=True,
            offset_reg=2,
            src_reg=4,      # value from register 4
        ),
        # Load from first location to register 5
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            use_base=True,
            offset_reg=2,   # same offset (0)
            dest_reg=5,     # load into register 5
        ),
        # Store the loaded value to second location (0x500 + 0x4 = 0x504)
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            use_base=True,
            offset_reg=1,   # offset 0x4
            src_reg=5,      # value from register 5
        ),
        # Load from second location to verify the sequence worked
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            use_base=True,
            offset_reg=1,   # offset 0x4 (second location)
            dest_reg=6,     # load into register 6
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    await li.wait_for_program_to_run()
    
    # Verify the sequence: original value -> first load -> second store -> final load
    original_value = 0x00CDEF0
    first_loaded = await li.read_register(5)
    final_loaded = await li.read_register(6)
    
    assert first_loaded == original_value, f"First load failed: expected {original_value:08x}, got {first_loaded:08x}"
    assert final_loaded == original_value, f"Store-load sequence failed: expected {original_value:08x}, got {final_loaded:08x}"


async def load_store_mask_test(li: LaneInterface) -> None:
    """Test load/store operations with mask bit"""
    await li.write_register(3, 0x600)  # address
    await li.write_register(2, 1)      # mask register (bit 0 = 1, skip execution)
    await li.write_register(1, 0x1999999)  # value to store
    await li.write_register(4, 0x1111111)  # initial value in destination
    
    program = [
        # This store should be skipped due to mask
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            mask=True,      # Enable mask checking
            use_base=False,
            src_reg=1,      # value to store
        ),
        # This load should also be skipped due to mask
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            mask=True,      # Enable mask checking
            use_base=False,
            dest_reg=4,     # destination (should remain unchanged)
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    await li.wait_for_program_to_run()
    
    # Register 4 should still contain its initial value due to mask
    final_value = await li.read_register(4)
    initial_value = 0x1111111
    assert final_value == initial_value, f"Mask test failed: register 4 should be unchanged but got {final_value:08x} instead of {initial_value:08x}"


async def load_store_mask_execute_test(li: LaneInterface) -> None:
    """Test load/store operations with mask bit allowing execution"""
    await li.write_register(3, 0x700)  # address
    await li.write_register(2, 0)      # mask register (bit 0 = 0, execute normally)
    await li.write_register(1, 0x7654321)  # value to store
    
    program = [
        # This store should execute normally
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            mask=True,      # Enable mask checking
            use_base=False,
            src_reg=1,      # value to store
        ),
        # This load should also execute normally
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            mask=True,      # Enable mask checking
            use_base=False,
            dest_reg=4,     # destination
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    await li.wait_for_program_to_run()
    
    # Register 4 should contain the stored value since mask allows execution
    final_value = await li.read_register(4)
    expected_value = 0x7654321
    assert final_value == expected_value, f"Mask execute test failed: expected {expected_value:08x}, got {final_value:08x}"


async def zero_offset_test(li: LaneInterface) -> None:
    """Test load/store with zero offset"""
    await li.write_register(3, 0x800)  # base address
    await li.write_register(2, 0)      # zero offset
    await li.write_register(1, 0x55AA55A)  # test value
    
    program = [
        # Store with zero offset
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            use_base=True,
            offset_reg=2,   # zero offset
            src_reg=1,      # value
        ),
        # Load with zero offset
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            use_base=True,
            offset_reg=2,   # zero offset
            dest_reg=4,     # destination
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    await li.wait_for_program_to_run()
    
    # Verify that zero offset works correctly
    final_value = await li.read_register(4)
    expected_value = 0x55AA55A
    assert final_value == expected_value, f"Zero offset test failed: expected {expected_value:08x}, got {final_value:08x}"


@cocotb.test()
async def lane_ldst_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    test_params = test_utils.read_params()
    seed = test_params['seed']
    with open(test_params['params_file']) as f:
        params = LaneParams.from_dict(json.load(f))

    rnd = Random(seed)
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())
    
    # Create the lane interface
    li = LaneInterface(dut, params, rnd, 1, 2)
    li.initialize_signals()
    await li.start()
    
    # Run load/store tests
    await loadstore_basic_test(li)
    await load_without_base_test(li)
    await store_without_base_test(li)
    await load_store_sequence_test(li)
    await load_store_mask_test(li)
    await load_store_mask_execute_test(li)
    await zero_offset_test(li)


def test_lane_ldst(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "Lane"
    module = "fmvpu.lane_test.test_lane_ldst"
    
    test_params = {
        "seed": seed,
        "params_file": params_file,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_lane_ldst(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Find the lane config file
        config_file = os.path.join(
            os.path.dirname(this_dir), "..", "..", "configs", "lane_default.json"
        )
        config_file = os.path.abspath(config_file)
        
        # Generate Lane with lane parameters
        filenames = generate_rtl.generate("Lane", working_dir, [config_file])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, "lane_verilog.sv")
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_lane_ldst(concat_filename, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        assert len(sys.argv) >= 3
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_lane_ldst(verilog_file, config_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_lane_ldst()
