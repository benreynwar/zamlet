import os
import sys
import tempfile
from typing import Optional
import logging
from random import Random

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from fmvpu import generate_rtl
from fmvpu import test_utils
from fmvpu.new_lane import lane_interface
from fmvpu.new_lane.lane_interface import LaneInterface
from fmvpu.new_lane.instructions import LoadStoreInstruction, LoadStoreModes, HaltInstruction


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def load_basic_test(li: LaneInterface) -> None:
    """Test basic LOAD operation: load from memory address to register"""
    # Set up memory address in register 1 (base address)
    await li.write_register(1, 0x100)  # base address
    await li.write_register(2, 0x4)    # offset
    
    # Write some test data to memory at address 0x104 (0x100 + 0x4)
    # Note: This test assumes the lane has a way to initialize memory
    # For now we'll test the instruction encoding and basic flow
    
    program = [
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            use_base=True,   # Use base address from register
            offset_reg=2,    # offset in register 2
            src_reg=1,       # base address in register 1
            dest_reg=3,      # load result into register 3
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # In a real implementation, we would check that register 3 contains the loaded value
    # For now, we just verify the program runs without error


async def store_basic_test(li: LaneInterface) -> None:
    """Test basic STORE operation: store from register to memory address"""
    # Set up values
    await li.write_register(1, 0x200)  # base address
    await li.write_register(2, 0x8)    # offset
    await li.write_register(3, 0xDEADBEEF)  # value to store
    
    program = [
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            use_base=True,   # Use base address from register
            offset_reg=2,    # offset in register 2
            src_reg=3,       # value to store from register 3
            dest_reg=1,      # base address in register 1
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # In a real implementation, we would check that memory at 0x208 contains 0xDEADBEEF


async def load_without_base_test(li: LaneInterface) -> None:
    """Test LOAD operation without base address (direct addressing)"""
    await li.write_register(1, 0x300)  # direct address
    
    program = [
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            use_base=False,  # Direct addressing
            offset_reg=0,    # no offset used
            src_reg=1,       # address in register 1
            dest_reg=4,      # load result into register 4
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()


async def store_without_base_test(li: LaneInterface) -> None:
    """Test STORE operation without base address (direct addressing)"""
    await li.write_register(1, 0x400)  # direct address
    await li.write_register(2, 0x12345678)  # value to store
    
    program = [
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            use_base=False,  # Direct addressing
            offset_reg=0,    # no offset used
            src_reg=2,       # value to store from register 2
            dest_reg=1,      # address in register 1
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()


async def load_store_sequence_test(li: LaneInterface) -> None:
    """Test sequence of load and store operations"""
    # Initialize registers
    await li.write_register(1, 0x500)  # base address
    await li.write_register(2, 0x0)    # offset for first location
    await li.write_register(3, 0x4)    # offset for second location
    await li.write_register(4, 0xABCDEF01)  # test value
    
    program = [
        # Store value to first location (0x500 + 0x0 = 0x500)
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            use_base=True,
            offset_reg=2,
            src_reg=4,      # value from register 4
            dest_reg=1,     # base address from register 1
        ),
        # Load from first location to register 5
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            use_base=True,
            offset_reg=2,   # same offset (0)
            src_reg=1,      # base address from register 1
            dest_reg=5,     # load into register 5
        ),
        # Store the loaded value to second location (0x500 + 0x4 = 0x504)
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            use_base=True,
            offset_reg=3,   # offset 0x4
            src_reg=5,      # value from register 5
            dest_reg=1,     # base address from register 1
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()


async def load_store_mask_test(li: LaneInterface) -> None:
    """Test load/store operations with mask bit"""
    await li.write_register(1, 0x600)  # address
    await li.write_register(2, 1)      # mask register (bit 0 = 1, skip execution)
    await li.write_register(3, 0x99999999)  # value to store
    await li.write_register(4, 0x11111111)  # initial value in destination
    
    program = [
        # This store should be skipped due to mask
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            mask=True,      # Enable mask checking
            use_base=False,
            src_reg=3,      # value to store
            dest_reg=1,     # address
        ),
        # This load should also be skipped due to mask
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            mask=True,      # Enable mask checking
            use_base=False,
            src_reg=1,      # address
            dest_reg=4,     # destination (should remain unchanged)
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Register 4 should still contain its initial value due to mask


async def load_store_mask_execute_test(li: LaneInterface) -> None:
    """Test load/store operations with mask bit allowing execution"""
    await li.write_register(1, 0x700)  # address
    await li.write_register(2, 0)      # mask register (bit 0 = 0, execute normally)
    await li.write_register(3, 0x87654321)  # value to store
    
    program = [
        # This store should execute normally
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            mask=True,      # Enable mask checking
            use_base=False,
            src_reg=3,      # value to store
            dest_reg=1,     # address
        ),
        # This load should also execute normally
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            mask=True,      # Enable mask checking
            use_base=False,
            src_reg=1,      # address
            dest_reg=4,     # destination
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()


async def zero_offset_test(li: LaneInterface) -> None:
    """Test load/store with zero offset"""
    await li.write_register(1, 0x800)  # base address
    await li.write_register(2, 0)      # zero offset
    await li.write_register(3, 0x55AA55AA)  # test value
    
    program = [
        # Store with zero offset
        LoadStoreInstruction(
            mode=LoadStoreModes.STORE,
            use_base=True,
            offset_reg=2,   # zero offset
            src_reg=3,      # value
            dest_reg=1,     # base address
        ),
        # Load with zero offset
        LoadStoreInstruction(
            mode=LoadStoreModes.LOAD,
            use_base=True,
            offset_reg=2,   # zero offset
            src_reg=1,      # base address
            dest_reg=4,     # destination
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()


@cocotb.test()
async def lane_ldst_test(dut: HierarchyObject, seed=0) -> None:
    test_utils.configure_logging_sim("DEBUG")
    rnd = Random(seed)
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())
    
    # Create the lane interface
    li = LaneInterface(dut, rnd, 1, 2)
    li.initialize_signals()
    await li.start()
    
    # Run load/store tests
    await load_basic_test(li)
    await store_basic_test(li)
    await load_without_base_test(li)
    await store_without_base_test(li)
    await load_store_sequence_test(li)
    await load_store_mask_test(li)
    await load_store_mask_execute_test(li)
    await zero_offset_test(li)


def test_lane_ldst(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "NewLane"
    module = "fmvpu.lane_test.test_ldst"
    
    test_params = {
        "seed": seed,
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
        
        # Generate NewLane with lane parameters
        filenames = generate_rtl.generate("NewLane", working_dir, [config_file])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, "lane_verilog.sv")
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_lane_ldst(concat_filename, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) >= 2:
        # Called from Bazel with verilog_file
        verilog_file = sys.argv[1]
        test_lane_ldst(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_lane_ldst()