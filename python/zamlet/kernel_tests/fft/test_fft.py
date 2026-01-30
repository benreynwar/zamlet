"""
Tests for the FFT kernel.

Run directly: PYTHONPATH=. python zamlet/kernel_tests/fft/test_fft.py
Run with pytest: python -m pytest zamlet/kernel_tests/fft/test_fft.py -v
"""

import logging
import os

from zamlet.geometries import GEOMETRIES
from zamlet.kernel_tests.conftest import build_if_needed, run_kernel


KERNEL_DIR = os.path.dirname(__file__)


def test_fft8(params):
    """Run 8-point FFT kernel and verify it passes."""
    binary_path = build_if_needed(KERNEL_DIR, 'vec-fft8.riscv')
    exit_code = run_kernel(binary_path, params=params, max_cycles=500000)
    assert exit_code == 0, f"FFT kernel failed with exit code {exit_code}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
    geom_name = "k2x2_j1x2"  # 8 jamlets for 8-point FFT
    params = GEOMETRIES[geom_name]
    print(f"Running FFT test with geometry: {geom_name}")
    test_fft8(params)
    print("PASSED")
