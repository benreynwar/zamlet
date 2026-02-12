"""
Geometry configurations for the RISC-V VPU simulator.

This module defines the set of ZamletParams configurations that tests should run against.

Usage:
    from zamlet.geometries import GEOMETRIES, get_geometry, scale_n_tests

    # For pytest parametrization with configurable count
    def generate_test_params(n_tests: int = 128):
        n_tests = scale_n_tests(n_tests)
        ...

Environment variables:
    ZAMLET_TEST_SCALE: Factor to scale test counts (e.g., 0.1 for 10%, 2 for 200%)
"""

import os
from typing import Dict

from zamlet.params import ZamletParams


def scale_n_tests(n: int) -> int:
    """Scale test count by ZAMLET_TEST_SCALE env var. Returns at least 1."""
    scale = float(os.environ.get('ZAMLET_TEST_SCALE', 1.0))
    return max(1, int(n * scale))


# Named geometry configurations.
# Names encode structure: k{cols}x{rows}_j{cols}x{rows}
GEOMETRIES: Dict[str, ZamletParams] = {
    "k2x1_j1x1": ZamletParams(k_cols=2, k_rows=1, j_cols=1, j_rows=1),
    "k2x1_j1x2": ZamletParams(k_cols=2, k_rows=1, j_cols=1, j_rows=2),
    "k2x1_j2x1": ZamletParams(k_cols=2, k_rows=1, j_cols=2, j_rows=1),
    "k2x2_j1x1": ZamletParams(k_cols=2, k_rows=2, j_cols=1, j_rows=1),
    "k2x2_j1x2": ZamletParams(k_cols=2, k_rows=2, j_cols=1, j_rows=2),
    "k2x2_j2x1": ZamletParams(k_cols=2, k_rows=2, j_cols=2, j_rows=1),
    "k2x2_j2x2": ZamletParams(k_cols=2, k_rows=2, j_cols=2, j_rows=2),
    "k2x2_j4x4": ZamletParams(k_cols=2, k_rows=2, j_cols=4, j_rows=4),
    "k4x4_j4x4": ZamletParams(k_cols=4, k_rows=4, j_cols=4, j_rows=4,
                               page_bytes=1 << 12),
}

SMALL_GEOMETRIES: Dict[str, ZamletParams] = {
        k: GEOMETRIES[k] for k in ['k2x1_j1x1', 'k2x1_j1x2', 'k2x1_j2x1', 'k2x2_j1x2', 'k2x2_j1x2', 'k2x2_j2x1', 'k2x2_j2x2']
        }


def get_geometry(name: str) -> ZamletParams:
    """Get a geometry by name. Raises KeyError if not found."""
    return GEOMETRIES[name]


def list_geometries() -> str:
    """Return a formatted string listing all available geometries."""
    lines = []
    for name, params in GEOMETRIES.items():
        lines.append(f"  {name}: k{params.k_cols}x{params.k_rows} j{params.j_cols}x{params.j_rows}"
                     f" ({params.j_in_l} jamlets)")
    return "\n".join(lines)
