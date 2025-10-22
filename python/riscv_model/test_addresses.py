"""
Some tests to make sure address conversion is working.
"""

import logging
from params import LamletParams
from lamlet import Lamlet
from addresses import GlobalAddress, TLB, make_basic_ordering, Ordering, WordOrder


def test_addresses():
    params = LamletParams(
        k_cols=2,
        k_rows=2,
        j_cols=2,
        j_rows=2,
        )
    lamlet = Lamlet(clock=None, params=params)
    allocation_size = params.page_bytes * 16
    base_addr = params.page_bytes * 8
    lamlet.allocate_memory(
            GlobalAddress(bit_addr=base_addr*8), allocation_size, is_vpu=True,
            ordering=Ordering(WordOrder.STANDARD, 32))

    # Check that we get the correct vpu address when we convert.
    address0 = GlobalAddress(bit_addr=base_addr*8)
    address1 = GlobalAddress(bit_addr=base_addr*8 + 32)
    address2 = GlobalAddress(bit_addr=base_addr*8 + 97)

    lamlet.require_cache(address0)

    vpu_address0 = lamlet.to_vpu_addr(address0)
    k_maddr0 = lamlet.to_k_maddr(address0)
    j_saddr0 = lamlet.to_j_saddr(address0)
    vpu_address1 = lamlet.to_vpu_addr(address1)
    k_maddr1 = lamlet.to_k_maddr(address1)
    j_saddr1 = lamlet.to_j_saddr(address1)
    vpu_address2 = lamlet.to_vpu_addr(address2)
    k_maddr2 = lamlet.to_k_maddr(address2)
    j_saddr2 = lamlet.to_j_saddr(address2)

    ww = params.word_bytes * 8

    assert vpu_address0.bit_addr == 0
    assert k_maddr0.k_index == 0
    assert k_maddr0.bit_addr == 0
    assert j_saddr0.k_index == 0
    assert j_saddr0.j_in_k_index == 0
    assert j_saddr0.bit_addr == 0

    assert vpu_address1.bit_addr == 32
    assert k_maddr1.k_index == 0
    assert k_maddr1.bit_addr == ww
    assert j_saddr1.k_index == 0
    assert j_saddr1.j_in_k_index == 1
    assert j_saddr1.bit_addr == 0

    assert vpu_address2.bit_addr == 97
    assert k_maddr2.k_index == 1
    assert k_maddr2.bit_addr == ww + 1
    assert j_saddr2.k_index == 1
    assert j_saddr2.j_in_k_index == 1
    assert j_saddr2.bit_addr == 1


if __name__ == '__main__':
    import sys
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    test_addresses()


