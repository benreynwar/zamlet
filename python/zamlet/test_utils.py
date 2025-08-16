import os
import json
import logging
from typing import Any, Dict, List
import sys
import shutil
from pathlib import Path

import cocotb

# Version-compatible imports for cocotb 1.9.2 and 2.0.0
try:
    # cocotb 2.0.0+
    from cocotb_tools.check_results import get_results
    from cocotb_tools.runner import get_runner
except ImportError:
    # cocotb 1.9.2 and earlier
    try:
        from cocotb.runner import get_results, get_runner
    except ImportError:
        # If neither works, create dummy functions
        def get_results(*args, **kwargs):
            raise NotImplementedError("get_results not available in this cocotb version")
        def get_runner(*args, **kwargs):
            raise NotImplementedError("get_runner not available in this cocotb version")


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
    # Version-compatible logging configuration
    try:
        # cocotb 2.0.0+
        import cocotb.logging
        cocotb.logging.default_config()
    except ImportError:
        # cocotb 1.9.2 and earlier
        try:
            import cocotb.log
            cocotb.log.default_config()
        except (ImportError, AttributeError):
            # Fallback to basic logging configuration
            pass

    # Set the desired log level
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {level}')
    logging.getLogger().setLevel(numeric_level)


def get_test_params() -> Dict[str, Any]:
    """Get test parameters from bazel environment variables."""
    config_filename = os.environ['ZAMLET_TEST_CONFIG_FILENAME']
    seed = int(os.environ.get('ZAMLET_TEST_SEED', '0'))
    return {
        "seed": seed,
        "params_file": config_filename,
    }


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
    
    # Copy VCD file to test outputs directory (regardless of test outcome)
    vcd_file = Path(runner.build_dir) / 'dump.vcd'
    if vcd_file.exists():
        try:
            # Use Bazel's test undeclared outputs directory
            output_dir = os.environ.get('TEST_UNDECLARED_OUTPUTS_DIR', '.')
            output_path = os.path.join(output_dir, 'dump.vcd')
            shutil.copy(str(vcd_file), output_path)
            logger.info(f"Copied {vcd_file} to {output_path}")
        except Exception as e:
            logger.warning(f"Failed to copy VCD file: {e}")
    else:
        logger.info(f"No VCD file found at {vcd_file}")
    
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


def find_signals_by_prefix(dut_obj, prefix: str) -> Dict[str, Any]:
    """Find all signals in a DUT object that start with the given prefix.
    
    Args:
        dut_obj: The DUT object or hierarchy to search
        prefix: The prefix to match signal names against
        
    Returns:
        Dictionary mapping signal names to signal objects, with _0 suffixed
        signals filtered out if a signal of the same name without _0 exists
    """
    matching_signals = {}
    
    # Get all attributes of the DUT object
    for attr_name in dir(dut_obj):
        if attr_name.startswith(prefix):
            signal_obj = getattr(dut_obj, attr_name)
            matching_signals[attr_name] = signal_obj
    
    # Filter out _0 suffixed signals if the base name exists
    filtered_signals = {}
    for signal_name, signal_obj in matching_signals.items():
        if signal_name.endswith('_0'):
            base_name = signal_name[:-2]  # Remove '_0' suffix
            if base_name in matching_signals:
                # Skip the _0 version since base name exists
                continue
        filtered_signals[signal_name] = signal_obj
    
    return filtered_signals
