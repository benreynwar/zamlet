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
from zamlet.amlet.alu_instruction import ALUInstruction, ALUModes
from zamlet.amlet.packet_instruction import PacketInstruction, PacketModes
from zamlet.amlet import packet_utils
from zamlet.bamlet_kernels.kernel_utils import instructions_into_vliw


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def alu_add_test(bi: BamletInterface) -> None:
    """Test ADD operation: reg1 + reg2 -> reg3"""
    await bi.write_register('d', 1, 15)
    await bi.write_register('d', 2, 7)
    
    instrs = [
        ALUInstruction(
            mode=ALUModes.ADD,
            src1=1,
            src2=2,
            d_dst=3,  # D-register 3
        ),
        ControlInstruction(mode=ControlModes.HALT),
        ]
    program = instructions_into_vliw(bi.params, instrs)
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check result in register 3
    result = bi.probe_register('d', 3)
    assert result == 22, f"Expected 22, got {result}"


async def alu_addi_test(bi: BamletInterface) -> None:
    """Test ADDI operation: reg1 + immediate -> reg3"""
    await bi.write_register('d', 1, 10)
    await bi.write_register('d', 2, 5)  # immediate value in reg2
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(
                mode=ALUModes.ADDI,
                src1=1,
                src2=2,  # immediate value
                d_dst=3,  # D-register 3
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check result in register 3
    result = bi.probe_register('d', 3)
    assert result == 12, f"Expected 12, got {result}"


async def alu_sub_test(bi: BamletInterface) -> None:
    """Test SUB operation: reg1 - reg2 -> reg3"""
    await bi.write_register('d', 1, 20)
    await bi.write_register('d', 2, 8)
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(
                mode=ALUModes.SUB,
                src1=1,
                src2=2,
                d_dst=3,  # D-register 3
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check result in register 3
    result = bi.probe_register('d', 3)
    assert result == 12, f"Expected 12, got {result}"


async def alu_subi_test(bi: BamletInterface) -> None:
    """Test SUBI operation: reg1 - immediate -> reg3"""
    await bi.write_register('d', 1, 25)
    await bi.write_register('d', 2, 3)  # immediate value in reg2
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(
                mode=ALUModes.SUBI,
                src1=1,
                src2=2,  # immediate value
                d_dst=3,  # D-register 3
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check result in register 3
    result = bi.probe_register('d', 3)
    assert result == 23, f"Expected 23, got {result}"


async def alu_mult_test(bi: BamletInterface) -> None:
    """Test MULT operation: reg1 * reg2 -> reg3"""
    await bi.write_register('d', 1, 6)
    await bi.write_register('d', 2, 7)
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(
                mode=ALUModes.MULT,
                src1=1,
                src2=2,
                d_dst=3,  # D-register 3
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check result in register 3
    result = bi.probe_register('d', 3)
    assert result == 42, f"Expected 42, got {result}"


async def alu_mult_acc_test(bi: BamletInterface) -> None:
    """Test MULT_ACC operation: accumulator + (src1 * src2) -> dst"""
    await bi.write_register('d', 2, 4)
    await bi.write_register('d', 3, 5)
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(
                mode=ALUModes.MULT_ACC_INIT,
                src1=2,
                src2=3,
                d_dst=1,  # D-register 1
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check result in register 1: 4 * 5 = 20 (MULT_ACC_INIT initializes accumulator)
    result = bi.probe_register('d', 1)
    assert result == 20, f"Expected 20, got {result}"


async def alu_mult_acc_chain_test(bi: BamletInterface) -> None:
    """Test multiple MULT_ACC operations in sequence to verify accumulator chaining"""
    await bi.write_register('d', 2, 3)   # first multiply operand
    await bi.write_register('d', 3, 2)   # second multiply operand
    await bi.write_register('d', 4, 4)   # third multiply operand
    await bi.write_register('d', 5, 1)   # fourth multiply operand
    
    program = [
        # First MULT_ACC_INIT: acc = 3 * 2 = 6
        VLIWInstruction(
            alu=ALUInstruction(
                mode=ALUModes.MULT_ACC_INIT,
                src1=2,
                src2=3,
                d_dst=1,  # D-register 1
            )
        ),
        # Second MULT_ACC: acc = 6 + (4 * 1) = 10
        VLIWInstruction(
            alu=ALUInstruction(
                mode=ALUModes.MULT_ACC,
                src1=4,
                src2=5,
                d_dst=1,  # D-register 1
            )
        ),
        # Third MULT_ACC: acc = 10 + (2 * 3) = 16
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(
                mode=ALUModes.MULT_ACC,
                src1=3,
                src2=2,
                d_dst=1,  # D-register 1
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check final result in register 1: 6 + 4 + 6 = 16
    result = bi.probe_register('d', 1)
    assert result == 16, f"Expected 16, got {result}"


async def alu_chain_operations_test(bi: BamletInterface) -> None:
    """Test chained ALU operations with dependencies"""
    await bi.write_register('d', 1, 3)
    await bi.write_register('d', 2, 4)
    
    program = [
        # reg4 = reg1 + reg2 (3 + 4 = 7)
        VLIWInstruction(
            alu=ALUInstruction(
                mode=ALUModes.ADD,
                src1=1,
                src2=2,
                d_dst=4,  # D-register 4
            )
        ),
        # reg5 = reg4 * reg1 (7 * 3 = 21)
        VLIWInstruction(
            alu=ALUInstruction(
                mode=ALUModes.MULT,
                src1=4,
                src2=1,
                d_dst=5,  # D-register 5
            )
        ),
        # reg6 = reg5 - reg2 (21 - 4 = 17)
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(
                mode=ALUModes.SUB,
                src1=5,
                src2=2,
                d_dst=6,  # D-register 6
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check intermediate and final results
    result4 = bi.probe_register('d', 4)
    assert result4 == 7, f"Expected 7 in register 4, got {result4}"
    result5 = bi.probe_register('d', 5)
    assert result5 == 21, f"Expected 21 in register 5, got {result5}"
    result6 = bi.probe_register('d', 6)
    assert result6 == 17, f"Expected 17 in register 6, got {result6}"


async def alu_zero_operands_test(bi: BamletInterface) -> None:
    """Test ALU operations with zero operands"""
    await bi.write_register('d', 1, 0)
    await bi.write_register('d', 2, 15)
    
    program = [
        # 0 + 15 = 15
        VLIWInstruction(
            alu=ALUInstruction(
                mode=ALUModes.ADD,
                src1=1,
                src2=2,
                d_dst=3,  # D-register 3
            )
        ),
        # 0 * 15 = 0
        VLIWInstruction(
            alu=ALUInstruction(
                mode=ALUModes.MULT,
                src1=1,
                src2=2,
                d_dst=4,  # D-register 4
            )
        ),
        # 15 - 0 = 15
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(
                mode=ALUModes.SUB,
                src1=2,
                src2=1,
                d_dst=5,  # D-register 5
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    result3 = bi.probe_register('d', 3)
    assert result3 == 15, f"Expected 15 in register 3, got {result3}"
    result4 = bi.probe_register('d', 4)
    assert result4 == 0, f"Expected 0 in register 4, got {result4}"
    result5 = bi.probe_register('d', 5)
    assert result5 == 15, f"Expected 15 in register 5, got {result5}"


async def alu_predicate_test(bi: BamletInterface) -> None:
    """Test ALU instruction predicate field - operations should only execute when predicate is true"""
    # Initialize source registers
    await bi.write_register('d', 1, 10)
    await bi.write_register('d', 2, 5)
    await bi.write_register('d', 3, 0)  # Clear destination register
    
    # Test 1: Set predicate register 1 to false (0), ALU should not execute
    await bi.write_register('p', 1, 0)  # Predicate false
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(
                mode=ALUModes.ADD,
                src1=1,
                src2=2,
                d_dst=3,
                predicate=1,  # Use P-register 1 as predicate
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check that destination register wasn't modified (predicate was false)
    result = bi.probe_register('d', 3)
    assert result == 0, f"Expected 0 (no execution), got {result}"
    
    # Test 2: Set predicate register 1 to true (1), ALU should execute
    await bi.write_register('p', 1, 1)  # Predicate true
    
    program = [
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(
                mode=ALUModes.ADD,
                src1=1,
                src2=2,
                d_dst=3,
                predicate=1,  # Use P-register 1 as predicate
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    # Check that operation executed (10 + 5 = 15)
    result = bi.probe_register('d', 3)
    assert result == 15, f"Expected 15 (executed), got {result}"


async def alu_with_packet_io_test(bi: BamletInterface) -> None:
    """Test ALU operations combined with packet I/O"""
    # Set up destination coordinates (echo back to source)
    dest_x = 0
    dest_y = 0
    coord_word = packet_utils.make_coord_register(dest_x, dest_y, bi.params.amlet)
    await bi.write_register('a', 0, coord_word)
    
    program = [
        # Receive packet and get length
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.RECEIVE,
                a_dst=5,  # Store length in A-register 5
                channel=0
            )
        ),
        # Start sending packet with same length
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.SEND,
                target=0,   # Destination coordinates in A-register 0
                length=5,   # Length from A-register 5
                channel=0
            )
        ),
        # Get two operands from packet
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                d_dst=1,  # D-register 1 (encoded as cutoff+1 = 16+1 = 17)
                channel=0
            )
        ),
        VLIWInstruction(
            packet=PacketInstruction(
                mode=PacketModes.GET_WORD,
                d_dst=2,  # D-register 2 (encoded as cutoff+2 = 16+2 = 18)
                channel=0
            )
        ),
        # Perform ALU operations and send results
        VLIWInstruction(
            alu=ALUInstruction(
                mode=ALUModes.ADD,
                src1=1,
                src2=2,
                a_dst=0,  # Send sum (A-register 0 goes to send buffer)
            )
        ),
        VLIWInstruction(
            control=ControlInstruction(mode=ControlModes.HALT),
            alu=ALUInstruction(
                mode=ALUModes.MULT,
                src1=1,
                src2=2,
                a_dst=0,  # Send product (A-register 0 goes to send buffer)
            )
        )
    ]
    bi.write_program(program, base_address=0)
    await bi.wait_to_send_packets()
    await bi.start_program(pc=0)
    await bi.wait_for_program_to_run()
    
    data = [12, 3]
    await bi.send_packet(data)
    packet = await bi.get_packet(expected_length=2)
    expected = [15, 36]  # 12+3=15, 12*3=36
    actual = packet[1:]
    assert actual == expected, f"Expected {expected}, got {actual}"


@cocotb.test()
async def bamlet_alu_test(dut: HierarchyObject) -> None:
    test_utils.configure_logging_sim("DEBUG")
    test_params = test_utils.read_params()
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
    
    # Run ALU tests
    await alu_add_test(bi)
    await alu_addi_test(bi)
    await alu_sub_test(bi)
    await alu_subi_test(bi)
    await alu_mult_test(bi)
    await alu_mult_acc_test(bi)
    await alu_mult_acc_chain_test(bi)
    await alu_chain_operations_test(bi)
    await alu_zero_operands_test(bi)
    await alu_with_packet_io_test(bi)
    await alu_predicate_test(bi)


def test_bamlet_alu(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "Bamlet"
    module = "zamlet.bamlet_test.test_alu"
    
    test_params = {
        "seed": seed,
        "params_file": params_file,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_bamlet_alu(temp_dir: Optional[str] = None, seed: int = 0) -> None:
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
        
        test_bamlet_alu(concat_filename, config_file, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) > 1:
        # Called from Bazel with verilog_file
        assert len(sys.argv) >= 3
        verilog_file = os.path.abspath(sys.argv[1])
        config_file = os.path.abspath(sys.argv[2])
        test_bamlet_alu(verilog_file, config_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_bamlet_alu()
