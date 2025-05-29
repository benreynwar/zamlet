import os
from random import Random
import json
import tempfile

import cocotb
from cocotb import triggers, clock
from cocotb_tools.runner import get_runner

from fmpvu import generate_rtl, test_utils
from fmpvu.test_utils import clog2

this_dir = os.path.abspath(os.path.dirname(__file__))


async def reads_and_writes(seed, dut, contents, width, depth, n_read_ports, n_write_ports):
    rnd = Random(seed)
    r_valids = [rnd.getrandbits(1) for i in range(n_read_ports)]
    r_addresses = [rnd.getrandbits(clog2(depth)) for i in range(n_read_ports)]
    expected_datas = []
    for read_port in range(n_read_ports):
        expected_datas.append(contents.get(r_addresses[read_port], None))
        valid_port = getattr(dut, f'reads_{read_port}_enable')
        address_port = getattr(dut, f'reads_{read_port}_address')
        valid_port.value = r_valids[read_port]
        address_port.value = r_addresses[read_port]

    w_valids = [rnd.getrandbits(1) for i in range(n_write_ports)]
    w_addresses = [rnd.getrandbits(clog2(depth)) for i in range(n_write_ports)]
    w_datas = [rnd.getrandbits(width) for i in range(n_write_ports)]
    for write_port in range(n_write_ports):
        clash = sum(address == w_addresses[write_port] and valid for valid, address in zip(w_valids, w_addresses)) > 1
        if w_valids[write_port] and not clash:
            contents[w_addresses[write_port]] = w_datas[write_port]
        valid_port = getattr(dut, f'writes_{write_port}_enable')
        data_port = getattr(dut, f'writes_{write_port}_data')
        addr_port = getattr(dut, f'writes_{write_port}_address')
        valid_port.value = w_valids[write_port]
        data_port.value = w_datas[write_port]
        addr_port.value = w_addresses[write_port]
    await triggers.ReadOnly()
    for read_port in range(n_read_ports):
        expected_data = expected_datas[read_port]
        if expected_data is not None:
            data_port = getattr(dut, f'reads_{read_port}_data')
            assert data_port.value == expected_data


@cocotb.test()
async def register_file_test(dut):
    params = test_utils.read_params()
    seed = params['seed']
    rnd = Random(seed)
    cocotb.start_soon(clock.Clock(dut.clock, 1, 'ns').start())
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


def test_proc(width=4, depth=8, n_read_ports=2, n_write_ports=2, temp_dir=None):
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
    test_proc(os.path.abspath('deleteme'))
