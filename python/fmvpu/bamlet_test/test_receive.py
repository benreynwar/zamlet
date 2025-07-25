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

from fmvpu import generate_rtl
from fmvpu import test_utils
from fmvpu.bamlet.bamlet_interface import BamletInterface
from fmvpu.bamlet.bamlet_params import BamletParams
from fmvpu.bamlet_kernels import receive as receive_kernel, kernel_utils


logger = logging.getLogger(__name__)
this_dir = os.path.abspath(os.path.dirname(__file__))


async def first_test(bi: BamletInterface) -> None:
    regs = receive_kernel.ReceiveKernelRegs()

    base_address = 0
    n = 6 * bi.params.n_amlets
    side = 'w'
    channel = 0

    data = list(range(n))

    args = receive_kernel.make_receive_kernel_args(bi.params, base_address, n, side)

    program = receive_kernel.receive_kernel(bi.params, regs, side, channel)
    vliw_program = kernel_utils.instructions_into_vliw(bi.params, program)

    logger.info('Writing args')
    bi.write_args(args, regs, side, channel)
    logger.info('Writing program')
    bi.write_program(vliw_program, base_address=0)
    logger.info('Waiting for packets to send')
    await bi.wait_to_send_packets()
    logger.info('Starting program')
    await bi.start_program(pc=0)
    logger.info('Sending data')
    receive_kernel.send_data(bi, side, data, channel)
    await bi.wait_for_program_to_run()

    logger.info('Checking output')
    # Now Check that the data is in the expected places in the data_memory
    for index, value in enumerate(data):
        amlet_x = index % bi.params.n_amlet_columns
        amlet_y = (index // bi.params.n_amlet_columns) % bi.params.n_amlet_rows
        addr = base_address + index // bi.params.n_amlets
        probed_data = bi.probe_vdm_data(amlet_x, amlet_y, addr)
        if value != probed_data:
            raise Exception(f'Expected value {value} does not match the value probed from VDM {probed_data}. amlet {amlet_x} {amlet_y} addr={addr}')


@cocotb.test()
async def receive_test(dut: HierarchyObject) -> None:
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
    
    await first_test(bi)


def test_bamlet_alu(verilog_file: str, params_file: str, seed: int = 0) -> None:
    """Main test procedure using pre-generated Verilog."""
    filenames = [verilog_file]
    
    toplevel = "Bamlet"
    module = "fmvpu.bamlet_test.test_receive"
    
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


def main():
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


if __name__ == "__main__":
    main()
