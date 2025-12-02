"""
Pytest tests for the conditional kernel.

Runs vec-conditional RISC-V binaries through the lamlet simulator.
"""

import os

import pytest

from zamlet.kernel_tests.conftest import build_if_needed, run_kernel


KERNEL_DIR = os.path.dirname(__file__)


def get_binaries():
    """Get list of conditional binaries to test."""
    return [
        'vec-conditional-tiny.riscv',
        'vec-conditional-small.riscv',
        'vec-conditional.riscv',
    ]


def generate_test_params():
    """Generate test parameter combinations."""
    params = []
    for binary in get_binaries():
        for j_rows in [1, 2]:
            # Check if the corresponding main file exists
            main_file = binary.replace('.riscv', '_main.c')
            main_path = os.path.join(KERNEL_DIR, main_file)
            if os.path.exists(main_path):
                id_str = f"{binary.replace('.riscv', '')}_jrows{j_rows}"
                params.append(pytest.param(binary, j_rows, id=id_str))
    return params


@pytest.mark.parametrize("binary,j_rows", generate_test_params())
def test_conditional(binary, j_rows):
    """Run conditional kernel and verify it passes."""
    binary_path = build_if_needed(KERNEL_DIR, binary)
    exit_code = run_kernel(binary_path, j_rows=j_rows)
    assert exit_code == 0, f"Kernel {binary} failed with exit code {exit_code}"
