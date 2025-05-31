import os
import tempfile
from random import Random
from typing import Dict, List, Optional

import cocotb
from cocotb import triggers
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject
from cocotb_tools.runner import get_runner

import generate_rtl
import test_utils
from test_utils import clog2

this_dir = os.path.abspath(os.path.dirname(__file__))


async def reads_and_writes(seed: int, dut: HierarchyObject, contents: Dict[int, int], width: int, depth: int, n_read_ports: int, n_write_ports: int) -> None:
    """Perform random read and write operations on the register file."""
    rnd = Random(seed)
    r_valids = [rnd.getrandbits(1) for i in range(n_read_ports)]
    r_addresses = [rnd.getrandbits(clog2(depth)) for i in range(n_read_ports)]
    expected_datas = []
    for read_port in range(n_read_ports):
        expected_datas.append(contents.get(r_addresses[read_port], None))
        valid_port = getattr(dut, f'io_reads_{read_port}_enable')
        address_port = getattr(dut, f'io_reads_{read_port}_address')
        valid_port.value = r_valids[read_port]
        address_port.value = r_addresses[read_port]

    w_valids = [rnd.getrandbits(1) for i in range(n_write_ports)]
    w_addresses = [rnd.getrandbits(clog2(depth)) for i in range(n_write_ports)]
    w_datas = [rnd.getrandbits(width) for i in range(n_write_ports)]
    for write_port in range(n_write_ports):
        clash = sum(address == w_addresses[write_port] and valid for valid, address in zip(w_valids, w_addresses)) > 1
        if w_valids[write_port] and not clash:
            contents[w_addresses[write_port]] = w_datas[write_port]
        valid_port = getattr(dut, f'io_writes_{write_port}_enable')
        data_port = getattr(dut, f'io_writes_{write_port}_data')
        addr_port = getattr(dut, f'io_writes_{write_port}_address')
        valid_port.value = w_valids[write_port]
        data_port.value = w_datas[write_port]
        addr_port.value = w_addresses[write_port]
    await triggers.ReadOnly()
    for read_port in range(n_read_ports):
        expected_data = expected_datas[read_port]
        if expected_data is not None:
            data_port = getattr(dut, f'io_reads_{read_port}_data')
            assert data_port.value == expected_data, f"Expected {expected_data}, got {data_port.value}"


@cocotb.test()
async def register_file_test(dut: HierarchyObject) -> None:
    """Test RegisterFile module with random read/write operations."""
    params = test_utils.read_params()
    seed = params['seed']
    rnd = Random(seed)
    
    # Start clock
    clock_gen = Clock(dut.clock, 1, 'ns')
    cocotb.start_soon(clock_gen.start())
    
    # Apply reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0
    n_write_ports = params['n_write_ports']
    depth = params['depth']
    width = params['width']
    n_read_ports = params['n_read_ports']
    n_write_ports = params['n_write_ports']
    contents = {}
    for i in range(100):
        await triggers.RisingEdge(dut.clock)
        cocotb.start_soon(reads_and_writes(test_utils.make_seed(rnd), dut, contents, width, depth, n_read_ports, n_write_ports))


def test_register_file_main(width: int = 4, depth: int = 8, n_read_ports: int = 2, n_write_ports: int = 2, temp_dir: Optional[str] = None) -> None:
    """Generate RTL and run the RegisterFile test."""
    with tempfile.TemporaryDirectory() as working_dir:
        if temp_dir is not None:
            working_dir = temp_dir
        filenames = generate_rtl.generate(
                'RegisterFile', working_dir, [str(width), str(depth), str(n_read_ports), str(n_write_ports)])
        test_params = {
            'seed': 0,
            'width': width,
            'depth': depth,
            'n_read_ports': n_read_ports,
            'n_write_ports': n_write_ports,
        }
        toplevel = 'RegisterFile'
        module = 'test_register_file'
        test_utils.run_test(working_dir, filenames, test_params, toplevel, module)


if __name__ == '__main__':
    test_register_file_main(temp_dir=os.path.abspath('deleteme'))
