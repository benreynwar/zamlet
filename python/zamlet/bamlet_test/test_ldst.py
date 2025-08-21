import os
import sys
import tempfile
from typing import Optional
import logging
from random import Random
import json

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject

from zamlet import generate_rtl
from zamlet import test_utils
from zamlet.bamlet.bamlet_interface import BamletInterface
from zamlet.bamlet.bamlet_params import BamletParams
from zamlet.amlet.instruction import VLIWInstruction
from zamlet.amlet.control_instruction import ControlInstruction, ControlModes
from zamlet.amlet.ldst_instruction import LoadStoreInstruction, LoadStoreModes


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def loadstore_basic_test(bi: BamletInterface) -> None:
    """Test basic LOAD and STORE operations"""
    test_value = 0x1234567
    base_addr = 0x08  # Valid address within data memory depth (32)
    
    # Set up addresses and test value
    await bi.write_register('a', 1, base_addr)  # address register
    await bi.write_register('d', 4, test_value) # value to store
    
    # Verify A-register was written correctly
    read_addr = bi.probe_register('a', 1)
    assert read_addr == base_addr, f"A-register write/read failed: expected {base_addr:08x}, got {read_addr:08x}"
    
    program = [
        # First store the test value to memory
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=1,    # address in A-register 1
                d_reg=4,   # value to store from D-register 4
            )
        ),
        # Then load it back from the same address
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=1,    # address in A-register 1
                d_reg=3,   # load result into D-register 3
            )
        ),
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Verify that the loaded value matches what we stored
    loaded_value = bi.probe_register('d', 3)
    assert loaded_value == test_value, f"Store/load roundtrip failed: expected {test_value:08x}, got {loaded_value:08x}"


async def load_store_sequence_test(bi: BamletInterface) -> None:
    """Test sequence of load and store operations"""
    # Initialize registers
    await bi.write_register('a', 3, 0x05)  # base address
    await bi.write_register('a', 2, 0x0A)  # second address
    await bi.write_register('d', 4, 0x00CDEF0)  # test value
    
    program = [
        # Store value to first location
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=3,    # address in A-register 3
                d_reg=4,   # value from D-register 4
            )
        ),
        # Load from first location to B-register 5
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=3,    # address in A-register 3
                d_reg=5,   # load into D-register 5
            )
        ),
        # Store the loaded value to second location
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=2,    # address in A-register 2
                d_reg=5,   # value from D-register 5
            )
        ),
        # Load from second location to verify the sequence worked
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=2,    # address in A-register 2
                d_reg=6,   # load into D-register 6
            )
        ),
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Verify the sequence: original value -> first load -> second store -> final load
    original_value = 0x00CDEF0
    first_loaded = bi.probe_register('d', 5)
    final_loaded = bi.probe_register('d', 6)
    
    assert first_loaded == original_value, f"First load failed: expected {original_value:08x}, got {first_loaded:08x}"
    assert final_loaded == original_value, f"Store-load sequence failed: expected {original_value:08x}, got {final_loaded:08x}"


async def multiple_addresses_test(bi: BamletInterface) -> None:
    """Test load/store operations with multiple different addresses"""
    test_values = [0x11111111, 0x22222222, 0x33333333]
    addresses = [0x10, 0x15, 0x18]  # Valid addresses within data memory depth (32)
    for address in addresses:
        assert address < bi.params.amlet.data_memory_depth
    
    # Set up addresses and test values
    for i, (addr, val) in enumerate(zip(addresses, test_values)):
        await bi.write_register('a', i + 1, addr)  # addresses in A-registers 1,2,3
        await bi.write_register('d', i + 4, val)   # values in D-registers 4,5,6
    
    program = [
        # Store all three values
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=1,    # address in A-register 1
                d_reg=4,   # value from D-register 4
            )
        ),
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=2,    # address in A-register 2
                d_reg=5,   # value from D-register 5
            )
        ),
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=3,    # address in A-register 3
                d_reg=6,   # value from D-register 6
            )
        ),
        # Load all three values back
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=1,    # address in A-register 1
                d_reg=7,   # load into D-register 7
            )
        ),
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=2,    # address in A-register 2
                d_reg=8,   # load into D-register 8
            )
        ),
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=3,    # address in A-register 3
                d_reg=9,   # load into D-register 9
            )
        ),
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Verify all loaded values match what we stored
    for i, expected_value in enumerate(test_values):
        loaded_value = bi.probe_register('d', i + 7)
        assert loaded_value == expected_value, f"Multi-address test failed for value {i}: expected {expected_value:08x}, got {loaded_value:08x}"


async def zero_value_test(bi: BamletInterface) -> None:
    """Test load/store with zero values"""
    await bi.write_register('a', 1, 0x12)  # address
    await bi.write_register('d', 2, 0)      # zero value
    
    program = [
        # Store zero value
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=1,    # address in A-register 1
                d_reg=2,   # zero value from D-register 2
            )
        ),
        # Load zero value back
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=1,    # address in A-register 1
                d_reg=3,   # load into D-register 3
            )
        ),
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Verify that zero value works correctly
    loaded_value = bi.probe_register('d', 3)
    assert loaded_value == 0, f"Zero value test failed: expected 0, got {loaded_value:08x}"


async def large_value_test(bi: BamletInterface) -> None:
    """Test load/store with maximum values"""
    max_value = 0xFFFFFFFF  # Maximum 32-bit value
    await bi.write_register('a', 1, 0x18)  # address
    await bi.write_register('d', 2, max_value)  # max value
    
    program = [
        # Store max value
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=1,    # address in A-register 1
                d_reg=2,   # max value from D-register 2
            )
        ),
        # Load max value back
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=1,    # address in A-register 1
                d_reg=3,   # load into D-register 3
            )
        ),
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Verify that large value works correctly
    loaded_value = bi.probe_register('d', 3)
    assert loaded_value == max_value, f"Large value test failed: expected {max_value:08x}, got {loaded_value:08x}"


async def a_register_test(bi: BamletInterface) -> None:
    """Test A-register read/write functionality independently"""
    test_addresses = [0x1000, 0x2000, 0x3000, 0xFFFF]
    
    # Test writing and reading back various values to A-registers
    for i, addr in enumerate(test_addresses):
        await bi.write_register('a', i + 1, addr)
        read_back = bi.probe_register('a', i + 1)
        assert read_back == addr, f"A-register {i+1} test failed: wrote {addr:08x}, read {read_back:08x}"
    
    # Test that registers don't interfere with each other
    for i, addr in enumerate(test_addresses):
        read_back = bi.probe_register('a', i + 1)
        assert read_back == addr, f"A-register {i+1} interference test failed: expected {addr:08x}, got {read_back:08x}"


async def a_register_loadstore_test(bi: BamletInterface) -> None:
    """Test load/store operations with A-registers as data destination/source"""
    test_value = 0x55AA  # 16-bit value (within A-register limits)
    memory_addr = 0x1C  # Valid address within data memory depth (32)
    
    # Set up memory address and test value
    await bi.write_register('a', 1, memory_addr)  # memory address
    await bi.write_register('a', 2, test_value)   # value to store
    
    program = [
        # Store value from A-register 2 to memory
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=1,    # memory address in A-register 1
                a_reg=2,   # value to store from A-register 2
            )
        ),
        # Load value from memory into A-register 3
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=1,    # memory address in A-register 1
                a_reg=3,   # load result into A-register 3
            )
        ),
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Verify that the loaded value matches what we stored
    loaded_value = bi.probe_register('a', 3)
    assert loaded_value == test_value, f"A-register store/load roundtrip failed: expected {test_value:08x}, got {loaded_value:08x}"


async def mixed_register_loadstore_test(bi: BamletInterface) -> None:
    """Test load/store operations mixing A-registers and D-registers"""
    d_test_value = 0x11223344  # D-registers can handle 32-bit values
    a_test_value = 0x5678      # 16-bit value (within A-register limits)
    memory_addr1 = 0x1D  # Valid address within data memory depth (32)
    memory_addr2 = 0x1E  # Valid address within data memory depth (32)
    
    # Set up memory addresses and test values
    await bi.write_register('a', 1, memory_addr1)  # first memory address
    await bi.write_register('a', 2, memory_addr2)  # second memory address
    await bi.write_register('d', 3, d_test_value)  # D-register value
    await bi.write_register('a', 4, a_test_value)  # A-register value
    
    program = [
        # Store D-register value to first memory location
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=1,    # memory address in A-register 1
                d_reg=3,   # value from D-register 3
            )
        ),
        # Store A-register value to second memory location
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=2,    # memory address in A-register 2
                a_reg=4,   # value from A-register 4
            )
        ),
        # Load from first location into A-register 5
        VLIWInstruction(
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=1,    # memory address in A-register 1
                a_reg=5,   # load into A-register 5
            )
        ),
        # Load from second location into D-register 6
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=2,    # memory address in A-register 2
                d_reg=6,   # load into D-register 6
            )
        ),
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Verify cross-register type loading worked correctly
    loaded_a_value = bi.probe_register('a', 5)  # Should have D-register value (truncated to 16 bits)
    loaded_d_value = bi.probe_register('d', 6)  # Should have A-register value (zero-padded to 32 bits)
    
    # When storing from D-register to memory and loading to A-register, value gets truncated to 16 bits
    expected_a_value = d_test_value & 0xFFFF  # Truncate to 16 bits
    assert loaded_a_value == expected_a_value, f"D->memory->A failed: expected {expected_a_value:08x}, got {loaded_a_value:08x}"
    
    # When storing from A-register to memory and loading to D-register, value gets zero-padded to 32 bits
    expected_d_value = a_test_value  # A-register value should be zero-padded in memory
    assert loaded_d_value == expected_d_value, f"A->memory->D failed: expected {expected_d_value:08x}, got {loaded_d_value:08x}"


async def ldst_predicate_test(bi: BamletInterface) -> None:
    """Test Load/Store instruction predicate field - operations should only execute when predicate is true"""
    test_value = 0xABCDEF12
    memory_addr = 0x0C  # Valid address within data memory depth (32)
    
    # Initialize registers
    await bi.write_register('a', 1, memory_addr)  # memory address
    await bi.write_register('d', 2, test_value)   # value to store
    await bi.write_register('d', 3, 0)            # clear destination register
    
    # Test 1: Set predicate register 1 to false (0), STORE should not execute
    await bi.write_register('p', 1, 0)  # Predicate false
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=1,       # memory address in A-register 1
                d_reg=2,      # value from D-register 2
                predicate=1,  # Use P-register 1 as predicate
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Now try to load from that address - should get 0 (no store happened)
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=1,    # memory address in A-register 1
                d_reg=3,   # load into D-register 3
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check that no store occurred (memory should be 0)
    result = bi.probe_register('d', 3)
    assert result == 0, f"Expected 0 (no store), got {result:08x}"
    
    # Test 2: Set predicate register 1 to true (1), STORE should execute
    await bi.write_register('p', 1, 1)  # Predicate true
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.STORE,
                addr=1,       # memory address in A-register 1
                d_reg=2,      # value from D-register 2
                predicate=1,  # Use P-register 1 as predicate
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Now load back the stored value
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=1,    # memory address in A-register 1
                d_reg=4,   # load into D-register 4
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check that store executed and value was stored
    result = bi.probe_register('d', 4)
    assert result == test_value, f"Expected {test_value:08x} (stored), got {result:08x}"
    
    # Test 3: Test predicate on LOAD operation - set predicate false for load
    await bi.write_register('p', 2, 0)  # Different predicate register, false
    await bi.write_register('d', 5, 0)  # Clear destination register
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            load_store=LoadStoreInstruction(
                mode=LoadStoreModes.LOAD,
                addr=1,       # memory address in A-register 1
                d_reg=5,      # load into D-register 5
                predicate=2,  # Use P-register 2 as predicate (false)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check that load didn't execute (destination should remain 0)
    result = bi.probe_register('d', 5)
    assert result == 0, f"Expected 0 (no load), got {result:08x}"


@cocotb.test()
async def bamlet_ldst_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    test_params = test_utils.get_test_params()
    seed = test_params['seed']
    with open(test_params['params_file']) as f:
        params = BamletParams.from_dict(json.load(f))

    rnd = Random(seed)
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())
    
    # Create the bamlet interface
    bi = BamletInterface(dut, params, rnd, 1, 1)
    bi.initialize_signals()
    await bi.start()
    
    # Run load/store tests
    await a_register_test(bi)
    await loadstore_basic_test(bi)
    await a_register_loadstore_test(bi)
    await mixed_register_loadstore_test(bi)
    await load_store_sequence_test(bi)
    await multiple_addresses_test(bi)
    await zero_value_test(bi)
    await large_value_test(bi)
    await ldst_predicate_test(bi)


def test_bamlet_ldst(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "Bamlet"
    module = "zamlet.bamlet_test.test_ldst"
    
    test_params = {
        "seed": seed,
        "params_file": params_file,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_bamlet_ldst(temp_dir: Optional[str] = None, seed: int = 0) -> None:
    """Generate Verilog and run test (for non-Bazel usage)."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        
        # Find the bamlet config file
        config_file = os.path.join(
            os.path.dirname(this_dir), "..", "..", "configs", "bamlet_default.json"
        )
        config_file = os.path.abspath(config_file)
        
        # Generate Bamlet with bamlet parameters
        filenames = generate_rtl.generate("Bamlet", working_dir, [config_file])
        
        # Concatenate all generated .sv files into a single file
        concat_filename = os.path.join(working_dir, "bamlet_verilog.sv")
        test_utils.concatenate_sv_files(filenames, concat_filename)
        
        test_bamlet_ldst(concat_filename, config_file, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        assert len(sys.argv) >= 3
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_bamlet_ldst(verilog_file, config_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_bamlet_ldst()
