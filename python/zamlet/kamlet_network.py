"""Kamlet-network coordinate helpers.

A kcoord is an (x, y) coordinate in the coarse Kamlet packet network,
not in the fine-grained Jamlet router grid.
"""

from zamlet.params import ZamletParams


def lamlet_kcoord(params: ZamletParams) -> tuple[int, int]:
    return (params.k_cols // 2, 0)


def kamlet_kcoord(params: ZamletParams, kamlet_index: int) -> tuple[int, int]:
    assert 0 <= kamlet_index < params.k_in_l
    k_col = kamlet_index % params.k_cols
    k_row = kamlet_index // params.k_cols
    return (params.k_cols // 2 + k_col, k_row + 1)


def kamlet_memlet_kcoord(params: ZamletParams, kamlet_index: int) -> tuple[int, int]:
    assert 0 <= kamlet_index < params.k_in_l
    k_col = kamlet_index % params.k_cols
    k_row = kamlet_index // params.k_cols
    if k_col < params.k_cols // 2:
        return (k_col, k_row + 1)
    return (params.k_cols + k_col, k_row + 1)


def kamlet_network_dims(params: ZamletParams) -> tuple[int, int]:
    return (2 * params.k_cols, params.k_rows + 1)
