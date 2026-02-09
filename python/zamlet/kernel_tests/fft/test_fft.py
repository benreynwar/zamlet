"""
Tests for the FFT kernel.

Run directly: PYTHONPATH=. python zamlet/kernel_tests/fft/test_fft.py
Run with pytest: python -m pytest zamlet/kernel_tests/fft/test_fft.py -v

Requires j_in_l >= 4 so that LMUL=2 gives vlmax >= 8 for SEW=64. See comment on
FFT_GEOMETRIES for why we use LMUL=2.
"""

import logging
import os

import pytest

from zamlet.geometries import GEOMETRIES
from zamlet.kernel_tests.conftest import build_if_needed, run_kernel


KERNEL_DIR = os.path.dirname(__file__)

# Filter to geometries with j_in_l >= 4 (needed for vlmax >= 8 with LMUL=2, SEW=64).
# We use LMUL=2 instead of LMUL=4 to avoid register spills. With LMUL=4 the compiler spills
# vector registers to the scalar stack, which doesn't work because scalar memory uses a
# different address space than VPU memory.
FFT_GEOMETRIES = {name: params for name, params in GEOMETRIES.items() if 4 <= params.j_in_l <= 4}


@pytest.mark.parametrize("params", [
    pytest.param(params, id=name) for name, params in FFT_GEOMETRIES.items()
])
def test_fft8(params):
    """Run 8-point FFT kernel and verify it passes."""
    binary_path = build_if_needed(KERNEL_DIR, 'vec-fft8.riscv')
    exit_code, _monitor = run_kernel(binary_path, params=params, max_cycles=500000)
    assert exit_code == 0, f"FFT kernel failed with exit code {exit_code}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
    geom_name = "k2x2_j1x1"  # j_in_l=4, vlmax=8 with LMUL=2
    params = GEOMETRIES[geom_name]
    print(f"Running FFT test with geometry: {geom_name}")
    test_fft8(params)
    print("PASSED")
