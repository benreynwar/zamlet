"""
Pytest tests for the bitreverse reorder kernel.
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
        id_str = f"bitreverse_{geom_name}"
        params.append(pytest.param(geom_params, id=id_str))
    return params


@pytest.mark.parametrize("params", generate_test_params())
def test_bitreverse(params):
    """Run bitreverse kernel and verify it passes."""
    binary_path = build_if_needed(KERNEL_DIR, 'bitreverse-reorder.riscv')
    exit_code = run_kernel(binary_path, params=params)
    assert exit_code == 0, f"Kernel failed with exit code {exit_code}"


@pytest.mark.parametrize("params", generate_test_params())
def test_bitreverse64(params):
    """Run 64-bit bitreverse kernel and verify it passes."""
    binary_path = build_if_needed(KERNEL_DIR, 'bitreverse-reorder64.riscv')
    exit_code = run_kernel(binary_path, params=params)
    assert exit_code == 0, f"Kernel failed with exit code {exit_code}"


if __name__ == '__main__':
    import argparse
    import logging

    parser = argparse.ArgumentParser(description='Run bitreverse reorder test')
    parser.add_argument('-g', '--geometry', default='k2x1_j1x2',
                        help='Geometry name (default: k2x1_j1x2)')
    parser.add_argument('--e64', action='store_true',
                        help='Run 64-bit element width version')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries')
    parser.add_argument('--log-level', default='WARNING',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Log level (default: WARNING)')
    parser.add_argument('--max-cycles', type=int, default=100000,
                        help='Maximum simulation cycles (default: 100000)')
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
        binary_name = 'bitreverse-reorder64.riscv' if args.e64 else 'bitreverse-reorder.riscv'
        binary_path = build_if_needed(KERNEL_DIR, binary_name)
        exit_code = run_kernel(binary_path, params=params, max_cycles=args.max_cycles)
        print(f"Exit code: {exit_code}")
        exit(exit_code)
