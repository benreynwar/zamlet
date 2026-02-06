"""
Test vid.v -> vse32.v -> scalar read pattern.

This tests that vector store of vid.v results can be correctly read back via scalar reads.
"""

import os

import pytest

from zamlet.geometries import GEOMETRIES
from zamlet.kernel_tests.conftest import build_if_needed, run_kernel


KERNEL_DIR = os.path.dirname(__file__)


def generate_test_params():
    """Generate test parameter combinations."""
    params = []
    for geom_name, geom_params in GEOMETRIES.items():
        id_str = f"vid_{geom_name}"
        params.append(pytest.param(geom_params, id=id_str))
    return params


@pytest.mark.parametrize("params", generate_test_params())
def test_vid(params):
    """Run vid kernel and verify it passes."""
    binary_path = build_if_needed(KERNEL_DIR, 'vid.riscv')
    exit_code, _monitor = run_kernel(binary_path, params=params)
    if exit_code != 0:
        if exit_code & 0x10000:
            index = (exit_code >> 8) & 0xFF
            actual = exit_code & 0xFF
            pytest.fail(f"Mismatch at index {index}: expected {index}, got {actual}")
    assert exit_code == 0, f"Kernel failed with exit code {exit_code}"


if __name__ == '__main__':
    import argparse
    import logging

    parser = argparse.ArgumentParser(description='Run vid test')
    parser.add_argument('-g', '--geometry', default='k2x1_j1x2',
                        help='Geometry name (default: k2x1_j1x2)')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries')
    parser.add_argument('--log-level', default='WARNING',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Log level (default: WARNING)')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        for name in GEOMETRIES:
            print(f"  {name}")
    else:
        logging.basicConfig(level=getattr(logging, args.log_level), format='%(message)s')

        if args.geometry not in GEOMETRIES:
            print(f"Unknown geometry: {args.geometry}")
            print("Use --list-geometries to see available options")
            exit(1)

        params = GEOMETRIES[args.geometry]
        binary_path = build_if_needed(KERNEL_DIR, 'vid.riscv')
        exit_code, _monitor = run_kernel(binary_path, params=params)
        print(f"Exit code: {exit_code}")
        if exit_code != 0 and exit_code & 0x10000:
            index = (exit_code >> 8) & 0xFF
            actual = exit_code & 0xFF
            print(f"Mismatch at index {index}: expected {index}, got {actual}")
        exit(exit_code)
