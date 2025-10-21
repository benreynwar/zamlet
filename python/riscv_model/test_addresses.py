"""
Some tests to make sure address conversion is working.
"""

from params import LamletParams
from addresses import GlobalAddress, TLB, make_basic_ordering


def test_addresses():
    params = LamletParams(
        k_cols=2,
        k_rows=2,
        j_cols=2,
        j_rows=2,
        )
    tlb = TLB(params)
    # Check the location after a cache line
    base_address = GlobalAddress(bit_addr=0)
    global_address = GlobalAddress(bit_addr=params.cache_line_bytes * 8 * params.k_in_l)
    tlb.allocate_memory(base_address, size=64 * params.page_bytes, is_vpu=True, ordering=make_basic_ordering(params, 16))
    vpu_address = global_address.to_vpu_addr(params, tlb)
    assert vpu_address.addr == global_address.addr
    k_maddr = global_address.to_k_maddr(params, tlb)
    assert k_maddr.k_index == 0
    assert k_maddr.bit_addr == global_address.bit_addr//params.k_in_l

if __name__ == '__main__':
    test_addresses()


