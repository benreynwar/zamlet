"""
Pytest tests for the readwritebyte kernel.
"""

import os

import pytest

from zamlet.geometries import GEOMETRIES
from zamlet.kernel_tests.conftest import build_if_needed, run_kernel


KERNEL_DIR = os.path.dirname(__file__)


def get_binaries():
    """Get list of readwritebyte binaries to test."""
    return [
        'simple_vpu_test.riscv',
        'write_then_read_many_bytes.riscv',
        'should_fail.riscv',
    ]


def generate_test_params():
    """Generate test parameter combinations."""
    params = []
    for binary in get_binaries():
        for geom_name, geom_params in GEOMETRIES.items():
            # readwritebyte uses .c files directly without _main suffix
            main_file = binary.replace('.riscv', '.c')
            main_path = os.path.join(KERNEL_DIR, main_file)
            if os.path.exists(main_path):
                id_str = f"{binary.replace('.riscv', '')}_{geom_name}"
                params.append(pytest.param(binary, geom_params, id=id_str))
    return params


@pytest.mark.parametrize("binary,params", generate_test_params())
def test_readwritebyte(binary, params):
    """Run readwritebyte kernel and verify it passes."""
    binary_path = build_if_needed(KERNEL_DIR, binary)
    exit_code = run_kernel(binary_path, params=params)

    # should_fail.riscv is expected to return non-zero
    if 'should_fail' in binary:
        assert exit_code != 0, f"Kernel {binary} should have failed but returned 0"
    else:
        assert exit_code == 0, f"Kernel {binary} failed with exit code {exit_code}"
