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

from zamlet import generate_rtl
from zamlet import test_utils
from zamlet.bamlet.bamlet_interface import BamletInterface
from zamlet.amlet.packet_utils import make_coord_register
from zamlet.bamlet.bamlet_params import BamletParams
from zamlet.amlet.instruction import VLIWInstruction
from zamlet.amlet.control_instruction import ControlInstruction, ControlModes
from zamlet.amlet.packet_instruction import PacketInstruction, PacketModes


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def setup_amlet_predicates(bi: BamletInterface) -> None:
    """Set pReg1=1 for amlet (0,0) and pReg1=0 for all other amlets"""
    for offset_x in range(bi.params.n_amlet_columns):
        for offset_y in range(bi.params.n_amlet_rows):
            if offset_x == 0 and offset_y == 0:
                await bi.write_register('p', 1, 1, offset_x=offset_x, offset_y=offset_y)
            else:
                await bi.write_register('p', 1, 0, offset_x=offset_x, offset_y=offset_y)


async def echo_packet_test(bi: BamletInterface) -> None:
    """Echo packet test using VLIW instructions for Bamlet"""

    await setup_amlet_predicates(bi)
    # Set up destination coordinates (echo back to source)
    dest_x = 0
    dest_y = 0
    coord_word = make_coord_register(dest_x, dest_y, bi.params.amlet)
    await bi.write_register('a', 1, coord_word)

    # Create VLIW program for packet echo
    program = [
        # First instruction: Receive packet and get length
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.RECEIVE,
                result=5,  # Store length in A-register 5
                channel=0,
                predicate=1,
            )
        ),
        # Second instruction: Start sending packet with same length
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.SEND,
                target=1,   # Destination coordinates in A-register 1
                length=5,   # Length from A-register 5
                channel=0,
                predicate=1,
            )
        ),
        # Third instruction: Get first word and put in send buffer
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                result=0,   # Put word directly in send buffer
                channel=0,
                predicate=1,
            )
        ),
        # Fourth instruction: Get second word and put in send buffer
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                result=0,   # Put word directly in send buffer
                channel=0,
                predicate=1,
            )
        ),
        # Fifth instruction: Halt
        VLIWInstruction(
            control=ControlInstruction(
                mode=ControlModes.HALT,
            )
        )
    ]
    
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    
    # Send test data
    data = [1, 2]
    await bi.send_packet(data)
    
    # Get echoed packet
    packet = await bi.get_packet(expected_length=len(data))
    assert packet[1:] == data, f"Expected {data}, got {packet[1:]}"


@cocotb.test()
async def bamlet_basic_test(dut: HierarchyObject) -> None:
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
    
    # Run tests
    await echo_packet_test(bi)


def test_bamlet_basic(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "Bamlet"
    module = "zamlet.bamlet_test.test_basic"
    
    test_params = {
        "seed": seed,
        "params_file": params_file,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_bamlet_basic(temp_dir: Optional[str] = None, seed: int = 0) -> None:
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
        
        test_bamlet_basic(concat_filename, config_file, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        assert len(sys.argv) >= 3
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_bamlet_basic(verilog_file, config_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_bamlet_basic()
