"""
Some tests for memory to position functions
"""

from params import LamletParams
from memlet import m_router_coords, memlet_coords_to_index

def test_params():
    return (
        LamletParams(
            k_cols = 2,
            k_rows = 1,
            j_cols = 1,
            j_rows = 2,
            ),
        LamletParams(
            k_cols = 2,
            k_rows = 2,
            j_cols = 2,
            j_rows = 2,
            ),
        )


def test():
    for params in test_params():
        if (params.k_rows * params.j_rows * 2) > params.k_in_l:
            # We have more edge spaces than kamlets
            assert (params.k_rows * params.j_rows * 2) % params.k_in_l == 0
            routers_in_memlet = params.k_rows * params.j_rows * 2 // params.k_in_l
        else:
            routers_in_memlet = 1
        for m_index in range(params.k_in_l):
            for router_index in range(routers_in_memlet):
                x, y = m_router_coords(params, m_index, router_index)
                new_m_index, new_router_index = memlet_coords_to_index(params, x, y)
                assert m_index == new_m_index
                assert router_index == new_router_index


if __name__ == '__main__':
    test()
