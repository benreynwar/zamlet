import os
import json
import logging
from typing import Any, Dict, List
import sys
from pathlib import Path

import cocotb
import cocotb.logging
from cocotb_tools.check_results import get_results
from cocotb_tools.runner import get_runner


logger = logging.getLogger(__name__)


def configure_logging_pre_sim(level: str = 'INFO') -> None:
    """Configure logging for tests before simulation starts."""
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {level}')
    logging.basicConfig(
        level=numeric_level,
        format='%(levelname)-8s %(name)-34s %(message)s',
        force=True
    )


def configure_logging_sim(level: str = 'INFO') -> None:
    """Configure logging for tests during simulation using cocotb's format."""
    cocotb.logging.default_config()

    # Set the desired log level
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {level}')
    logging.getLogger().setLevel(numeric_level)


def write_params(working_dir: str, params: Dict[str, Any]) -> None:
    """Write test parameters to JSON file and set environment variable."""
    params_filename = os.path.abspath(os.path.join(working_dir, 'test_params.json'))
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
    
    # Check test results using cocotb's check_results function
    results_file = Path(runner.build_dir) / 'results.xml'
    
    try:
        num_tests, num_failed = get_results(results_file)
        if num_failed > 0:
            print(f"Test failed: {num_failed} out of {num_tests} tests failed", file=sys.stderr)
            sys.exit(1)
        print(f"All tests passed: {num_tests} tests completed successfully")
    except RuntimeError as e:
        print(f"Test failed: {e}", file=sys.stderr)
        sys.exit(1)


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


def concatenate_sv_files(input_filenames: List[str], output_filename: str) -> None:
    """Concatenate SystemVerilog files into a single file.
    
    Args:
        input_filenames: List of input .sv files to concatenate
        output_filename: Path to output concatenated file
    """
    with open(output_filename, 'w', encoding='utf-8') as output_file:
        for filename in input_filenames:
            if filename.endswith('.sv'):
                with open(filename, 'r', encoding='utf-8') as input_file:
                    output_file.write(input_file.read())
                    output_file.write('\n')
