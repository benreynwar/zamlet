"""
Geometry configurations for the RISC-V VPU simulator.

This module defines the set of LamletParams configurations that tests should run against.

Usage:
    from zamlet.geometries import GEOMETRIES, get_geometry

    # Get a specific geometry by name
    params = get_geometry("small")

    # For pytest parametrization
    @pytest.mark.parametrize("name,params", GEOMETRIES.items())
    def test_something(name, params):
        ...
"""

from typing import Dict

from zamlet.params import LamletParams


# Named geometry configurations.
# Names encode structure: k{cols}x{rows}_j{cols}x{rows}
GEOMETRIES: Dict[str, LamletParams] = {
    "k2x1_j1x1": LamletParams(k_cols=2, k_rows=1, j_cols=1, j_rows=1),
    "k2x1_j1x2": LamletParams(k_cols=2, k_rows=1, j_cols=1, j_rows=2),
    "k2x1_j2x1": LamletParams(k_cols=2, k_rows=1, j_cols=2, j_rows=1),
    "k2x2_j1x1": LamletParams(k_cols=2, k_rows=2, j_cols=1, j_rows=1),
    "k2x2_j1x2": LamletParams(k_cols=2, k_rows=2, j_cols=1, j_rows=2),
    "k2x2_j2x2": LamletParams(k_cols=2, k_rows=2, j_cols=2, j_rows=2),
}


def get_geometry(name: str) -> LamletParams:
    """Get a geometry by name. Raises KeyError if not found."""
    return GEOMETRIES[name]


def list_geometries() -> str:
    """Return a formatted string listing all available geometries."""
    lines = []
    for name, params in GEOMETRIES.items():
        lines.append(f"  {name}: k{params.k_cols}x{params.k_rows} j{params.j_cols}x{params.j_rows}"
                     f" ({params.j_in_l} jamlets)")
    return "\n".join(lines)
