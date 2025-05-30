import os
import json
from typing import Any, Dict, List

from cocotb_tools.runner import get_runner


def write_params(working_dir: str, params: Dict[str, Any]) -> None:
    """Write test parameters to JSON file and set environment variable."""
    params_filename = os.path.join(working_dir, 'test_params.json')
    os.environ['FMPVU_TEST_PARAMS_FILENAME'] = params_filename
    with open(params_filename, 'w', encoding='utf-8') as params_file:
        params_file.write(json.dumps(params))


def read_params() -> Dict[str, Any]:
    """Read test parameters from JSON file specified in environment variable."""
    params_filename = os.environ['FMPVU_TEST_PARAMS_FILENAME']
    with open(params_filename, 'r', encoding='utf-8') as params_file:
        params = json.loads(params_file.read())
    return params


def run_test(working_dir: str, filenames: List[str], params: Dict[str, Any], toplevel: str, module: str) -> None:
    """Run cocotb test with Verilator simulator."""
    sim = 'verilator'
    runner = get_runner(sim)
    write_params(working_dir, params)
    runner.build(
        sources=filenames,
        hdl_toplevel=toplevel,
        always=True,
        waves=True,
        build_args=['--trace', '--trace-structs'],
        )
    runner.test(hdl_toplevel=toplevel, test_module=module, waves=True)


def clog2(value: int) -> int:
    """Calculate ceiling log2 - how many bits are required to represent 'value-1'."""
    value = value - 1
    bits = 0
    while value > 0:
        value = value >> 1
        bits += 1
    return bits


def make_seed(rnd: Any) -> int:
    """Generate a 32-bit random seed."""
    return rnd.getrandbits(32)
