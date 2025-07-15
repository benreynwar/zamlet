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
from fmvpu.new_lane.instructions import PacketInstruction, PacketModes, HaltInstruction, ALUInstruction, ALUModes


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def alu_add_test(li: LaneInterface) -> None:
    """Test ADD operation: reg1 + reg2 -> reg3"""
    await li.write_register(1, 15)
    await li.write_register(2, 7)
    
    program = [
        ALUInstruction(
            mode=ALUModes.ADD,
            src1_reg=1,
            src2_reg=2,
            result_reg=3,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Check result in register 3
    assert await li.read_register(3) == 22


async def alu_addi_test(li: LaneInterface) -> None:
    """Test ADDI operation: reg1 + immediate -> reg3"""
    await li.write_register(1, 10)
    await li.write_register(2, 5)  # immediate value in reg2
    
    program = [
        ALUInstruction(
            mode=ALUModes.ADDI,
            src1_reg=1,
            src2_reg=2,  # immediate value
            result_reg=3,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Check result in register 3
    assert await li.read_register(3) == 15


async def alu_sub_test(li: LaneInterface) -> None:
    """Test SUB operation: reg1 - reg2 -> reg3"""
    await li.write_register(1, 20)
    await li.write_register(2, 8)
    
    program = [
        ALUInstruction(
            mode=ALUModes.SUB,
            src1_reg=1,
            src2_reg=2,
            result_reg=3,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Check result in register 3
    assert await li.read_register(3) == 12


async def alu_subi_test(li: LaneInterface) -> None:
    """Test SUBI operation: reg1 - immediate -> reg3"""
    await li.write_register(1, 25)
    await li.write_register(2, 3)  # immediate value in reg2
    
    program = [
        ALUInstruction(
            mode=ALUModes.SUBI,
            src1_reg=1,
            src2_reg=2,  # immediate value
            result_reg=3,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Check result in register 3
    assert await li.read_register(3) == 22


async def alu_mult_test(li: LaneInterface) -> None:
    """Test MULT operation: reg1 * reg2 -> reg3"""
    await li.write_register(1, 6)
    await li.write_register(2, 7)
    
    program = [
        ALUInstruction(
            mode=ALUModes.MULT,
            src1_reg=1,
            src2_reg=2,
            result_reg=3,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Check result in register 3
    assert await li.read_register(3) == 42


async def alu_mult_acc_test(li: LaneInterface) -> None:
    """Test MULT_ACC operation: reg1 + (reg2 * reg3) -> reg1"""
    await li.write_register(1, 10)  # accumulator initial value (reg 1 is accumulator)
    await li.write_register(2, 4)
    await li.write_register(3, 5)
    
    program = [
        ALUInstruction(
            mode=ALUModes.MULT_ACC,
            src1_reg=2,
            src2_reg=3,
            result_reg=1,  # Write result back to accumulator register
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Check result in register 1: 10 + (4 * 5) = 30
    assert await li.read_register(1) == 30


async def alu_mult_acc_chain_test(li: LaneInterface) -> None:
    """Test multiple MULT_ACC operations in sequence to verify local accumulator"""
    await li.write_register(1, 5)   # accumulator initial value (reg 1 is accumulator)
    await li.write_register(2, 3)   # first multiply operand
    await li.write_register(3, 2)   # second multiply operand
    await li.write_register(4, 4)   # third multiply operand
    await li.write_register(5, 1)   # fourth multiply operand
    
    program = [
        # First MULT_ACC: reg1 = 5 + (3 * 2) = 5 + 6 = 11
        ALUInstruction(
            mode=ALUModes.MULT_ACC,
            src1_reg=2,
            src2_reg=3,
            result_reg=1,  # Write result back to accumulator register
        ),
        # Second MULT_ACC: reg1 = 11 + (4 * 1) = 11 + 4 = 15
        ALUInstruction(
            mode=ALUModes.MULT_ACC,
            src1_reg=4,
            src2_reg=5,
            result_reg=1,  # Write result back to accumulator register
        ),
        # Third MULT_ACC: reg1 = 15 + (2 * 3) = 15 + 6 = 21
        ALUInstruction(
            mode=ALUModes.MULT_ACC,
            src1_reg=3,
            src2_reg=2,
            result_reg=1,  # Write result back to accumulator register
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Check final result in register 1: 5 + 6 + 4 + 6 = 21
    assert await li.read_register(1) == 21


async def alu_chain_operations_test(li: LaneInterface) -> None:
    """Test chained ALU operations with dependencies"""
    await li.write_register(1, 3)
    await li.write_register(2, 4)
    
    program = [
        # reg4 = reg1 + reg2 (3 + 4 = 7)
        ALUInstruction(
            mode=ALUModes.ADD,
            src1_reg=1,
            src2_reg=2,
            result_reg=4,
        ),
        # reg5 = reg4 * reg1 (7 * 3 = 21)
        ALUInstruction(
            mode=ALUModes.MULT,
            src1_reg=4,
            src2_reg=1,
            result_reg=5,
        ),
        # reg6 = reg5 - reg2 (21 - 4 = 17)
        ALUInstruction(
            mode=ALUModes.SUB,
            src1_reg=5,
            src2_reg=2,
            result_reg=6,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Check intermediate and final results
    assert await li.read_register(4) == 7
    assert await li.read_register(5) == 21
    assert await li.read_register(6) == 17


async def alu_mask_test(li: LaneInterface) -> None:
    """Test ALU operation with mask bit set to skip execution"""
    await li.write_register(1, 10)
    await li.write_register(2, 1)  # Set mask register (bit 0 = 1 means skip execution)
    await li.write_register(3, 99)  # Initial value that should remain unchanged
    await li.write_register(4, 5)   # Second operand
    
    program = [
        ALUInstruction(
            mode=ALUModes.ADD,
            mask=True,  # Enable mask checking (instruction bit 9 = 1)
            src1_reg=1,
            src2_reg=4,
            result_reg=3,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Register 3 should remain unchanged due to mask
    assert await li.read_register(3) == 99


async def alu_mask_execute_test(li: LaneInterface) -> None:
    """Test ALU operation with mask bit set to execute normally"""
    await li.write_register(1, 10)
    await li.write_register(2, 0)  # Set mask register (bit 0 = 0 means execute normally)
    await li.write_register(3, 99)  # Initial value that should be changed
    await li.write_register(4, 5)   # Second operand
    
    program = [
        ALUInstruction(
            mode=ALUModes.ADD,
            mask=True,  # Enable mask checking (instruction bit 9 = 1)
            src1_reg=1,
            src2_reg=4,
            result_reg=3,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    # Register 3 should be updated to 10 + 5 = 15
    assert await li.read_register(3) == 15


async def alu_zero_operands_test(li: LaneInterface) -> None:
    """Test ALU operations with zero operands"""
    await li.write_register(1, 0)
    await li.write_register(2, 15)
    
    program = [
        # 0 + 15 = 15
        ALUInstruction(
            mode=ALUModes.ADD,
            src1_reg=1,
            src2_reg=2,
            result_reg=3,
        ),
        # 0 * 15 = 0
        ALUInstruction(
            mode=ALUModes.MULT,
            src1_reg=1,
            src2_reg=2,
            result_reg=4,
        ),
        # 15 - 0 = 15
        ALUInstruction(
            mode=ALUModes.SUB,
            src1_reg=2,
            src2_reg=1,
            result_reg=5,
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    assert await li.read_register(3) == 15
    assert await li.read_register(4) == 0
    assert await li.read_register(5) == 15


async def alu_with_packet_io_test(li: LaneInterface) -> None:
    """Test ALU operations combined with packet I/O"""
    program = [
        PacketInstruction(
            mode=PacketModes.RECEIVE,
            result_reg=5,  # packet length
        ),
        PacketInstruction(
            mode=PacketModes.SEND,
            location_reg=0,  # coordinate
            send_length_reg=5,  # same length
        ),
        # Get two operands from packet
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=1,
        ),
        PacketInstruction(
            mode=PacketModes.GET_WORD,
            result_reg=2,
        ),
        # Perform ALU operations and send results
        ALUInstruction(
            mode=ALUModes.ADD,
            src1_reg=1,
            src2_reg=2,
            result_reg=0,  # send sum
        ),
        ALUInstruction(
            mode=ALUModes.MULT,
            src1_reg=1,
            src2_reg=2,
            result_reg=0,  # send product
        ),
        HaltInstruction(),
    ]
    await li.write_program(program)
    await li.start_program()
    
    data = [12, 3]
    await li.send_packet(data)
    packet = await li.get_packet(expected_length=2)
    assert packet[1:] == [15, 36]  # 12+3=15, 12*3=36


@cocotb.test()
async def lane_alu_test(dut: HierarchyObject, seed=0) -> None:
    test_utils.configure_logging_sim("DEBUG")
    rnd = Random(seed)
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, "ns")
    cocotb.start_soon(clock_gen.start())
    
    # Create the lane interface
    li = LaneInterface(dut, rnd, 1, 2)
    li.initialize_signals()
    await li.start()
    
    # Run ALU tests
    await alu_add_test(li)
    await alu_addi_test(li)
    await alu_sub_test(li)
    await alu_subi_test(li)
    await alu_mult_test(li)
    await alu_mult_acc_test(li)
    await alu_mult_acc_chain_test(li)
    await alu_chain_operations_test(li)
    await alu_mask_test(li)
    await alu_mask_execute_test(li)
    await alu_zero_operands_test(li)
    await alu_with_packet_io_test(li)


def test_lane_alu(verilog_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "NewLane"
    module = "fmvpu.lane_test.test_lane_alu"
    
    test_params = {
        "seed": seed,
    }
    
    verilog_dir = os.path.dirname(verilog_file)
    test_utils.run_test(verilog_dir, filenames, test_params, toplevel, module)


def generate_and_test_lane_alu(temp_dir: Optional[str] = None, seed: int = 0) -> None:
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
        
        test_lane_alu(concat_filename, seed)


if __name__ == "__main__":
    test_utils.configure_logging_pre_sim("INFO")
    
    if len(sys.argv) >= 2:
        # Called from Bazel with verilog_file
        verilog_file = sys.argv[1]
        test_lane_alu(verilog_file)
    else:
        # Called directly - generate Verilog and test
        generate_and_test_lane_alu()
