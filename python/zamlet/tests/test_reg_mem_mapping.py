"""
Test that RegMemMapping generated from reg→mem matches mappings generated from mem→reg.

For each configuration (src_ew, dst_ew, offsets, etc.), we:
1. Generate all mappings from reg side (for each jamlet and each byte offset in word)
2. Generate all mappings from mem side (for each jamlet and each byte offset in word)
3. Verify they produce the same set of mappings
"""

import logging
import argparse
from dataclasses import dataclass
from typing import List, Set, Tuple

import pytest

from zamlet.params import LamletParams
from zamlet.geometries import GEOMETRIES
from zamlet.addresses import Ordering, WordOrder, KMAddr
from zamlet.kamlet import kinstructions
from zamlet.transactions.j2j_mapping import RegMemMapping, get_mapping_from_reg, get_mapping_from_mem


logger = logging.getLogger(__name__)


def create_test_params(k_cols: int = 2, k_rows: int = 1,
                       j_cols: int = 1, j_rows: int = 1) -> LamletParams:
    return LamletParams(
        k_cols=k_cols,
        k_rows=k_rows,
        j_cols=j_cols,
        j_rows=j_rows,
    )


def create_load_instr(params: LamletParams, mem_ew: int, reg_ew: int,
                      start_index: int, n_elements: int,
                      mem_offset: int = 0) -> kinstructions.Load:
    mem_ordering = Ordering(word_order=WordOrder.STANDARD, ew=mem_ew)
    reg_ordering = Ordering(word_order=WordOrder.STANDARD, ew=reg_ew)

    k_maddr = KMAddr(
        k_index=0,
        ordering=mem_ordering,
        bit_addr=mem_offset * 8,
        params=params,
    )

    return kinstructions.Load(
        dst=0,
        k_maddr=k_maddr,
        start_index=start_index,
        n_elements=n_elements,
        dst_ordering=reg_ordering,
        mask_reg=None,
        writeset_ident=0,
        instr_ident=0,
    )


def mapping_to_tuple(m: RegMemMapping) -> Tuple[int, int, int, int, int, int, int]:
    return (m.reg_v, m.reg_vw, m.reg_wb, m.mem_v, m.mem_vw, m.mem_wb, m.n_bits)


def get_all_mappings_from_reg(params: LamletParams,
                               instr: kinstructions.Load) -> Set[Tuple]:
    """Generate all mappings by iterating over reg-side coordinates."""
    mappings = set()
    word_bits = params.word_bytes * 8

    for reg_y in range(params.k_rows * params.j_rows):
        for reg_x in range(params.k_cols * params.j_cols):
            for reg_wb in range(0, word_bits, 8):
                result = get_mapping_from_reg(
                    params=params,
                    k_maddr=instr.k_maddr,
                    reg_ordering=instr.dst_ordering,
                    start_index=instr.start_index,
                    n_elements=instr.n_elements,
                    reg_wb=reg_wb,
                    reg_x=reg_x,
                    reg_y=reg_y,
                )
                for m in result:
                    mappings.add(mapping_to_tuple(m))

    return mappings


def get_all_mappings_from_mem(params: LamletParams,
                               instr: kinstructions.Load) -> Set[Tuple]:
    """Generate all mappings by iterating over mem-side coordinates."""
    mappings = set()
    word_bits = params.word_bytes * 8

    for mem_y in range(params.k_rows * params.j_rows):
        for mem_x in range(params.k_cols * params.j_cols):
            for mem_wb in range(0, word_bits, 8):
                result = get_mapping_from_mem(
                    params=params,
                    k_maddr=instr.k_maddr,
                    reg_ordering=instr.dst_ordering,
                    start_index=instr.start_index,
                    n_elements=instr.n_elements,
                    mem_wb=mem_wb,
                    mem_x=mem_x,
                    mem_y=mem_y,
                )
                for m in result:
                    mappings.add(mapping_to_tuple(m))

    return mappings


def check_mapping_consistency(params: LamletParams, mem_ew: int, reg_ew: int,
                              start_index: int, n_elements: int,
                              mem_offset: int = 0) -> bool:
    """Test that reg→mem and mem→reg produce the same mappings."""
    instr = create_load_instr(params, mem_ew, reg_ew, start_index, n_elements, mem_offset)

    reg_mappings = get_all_mappings_from_reg(params, instr)
    mem_mappings = get_all_mappings_from_mem(params, instr)

    if reg_mappings != mem_mappings:
        logger.error(f"MISMATCH for mem_ew={mem_ew}, reg_ew={reg_ew}, "
                     f"start_index={start_index}, n_elements={n_elements}, "
                     f"mem_offset={mem_offset}")
        only_in_reg = reg_mappings - mem_mappings
        only_in_mem = mem_mappings - reg_mappings
        if only_in_reg:
            logger.error(f"  Only in reg mappings: {sorted(only_in_reg)}")
            assert False
        if only_in_mem:
            logger.error(f"  Only in mem mappings: {sorted(only_in_mem)}")
            assert False
        return False

    logger.info(f"OK: mem_ew={mem_ew}, reg_ew={reg_ew}, start_index={start_index}, "
                f"n_elements={n_elements}, mem_offset={mem_offset} -> {len(reg_mappings)} mappings")
    return True


def run_tests(k_cols: int = 2, k_rows: int = 1,
              j_cols: int = 1, j_rows: int = 1) -> int:
    """Run a suite of tests with various configurations."""
    params = create_test_params(k_cols, k_rows, j_cols, j_rows)

    logger.info(f"Testing with k_cols={k_cols}, k_rows={k_rows}, "
                f"j_cols={j_cols}, j_rows={j_rows}")
    logger.info(f"  j_in_l={params.j_in_l}, word_bytes={params.word_bytes}, "
                f"vline_bytes={params.vline_bytes}")

    failures = 0
    tests = 0

    ew_values = [8, 16, 32, 64]
    offset_values = [0, 8, 16]

    for mem_ew in ew_values:
        for reg_ew in ew_values:
            for start_index in [0, 1, 4]:
                for n_elements in [1, 4, 8, 16]:
                    for mem_offset in offset_values:
                        if mem_offset % (mem_ew // 8) != 0:
                            continue
                        tests += 1
                        if not check_mapping_consistency(
                            params, mem_ew, reg_ew, start_index, n_elements, mem_offset
                        ):
                            failures += 1

    logger.info(f"\nTotal: {tests} tests, {failures} failures")
    return failures


def random_test_config(rnd):
    """Generate a random test configuration."""
    geom_name = rnd.choice(list(GEOMETRIES.keys()))
    geom_params = GEOMETRIES[geom_name]
    mem_ew = rnd.choice([8, 16, 32, 64])
    reg_ew = rnd.choice([8, 16, 32, 64])
    start_index = rnd.randint(0, 8)
    n_elements = rnd.randint(1, 32)
    mem_offset = rnd.randint(0, 128)
    return geom_name, geom_params, mem_ew, reg_ew, start_index, n_elements, mem_offset


def generate_test_params(n_tests: int = 128, seed: int = 42):
    """Generate random test parameter combinations for pytest."""
    from random import Random
    rnd = Random(seed)
    params_list = []
    for i in range(n_tests):
        geom_name, geom_params, mem_ew, reg_ew, start_index, n_elements, mem_offset = \
            random_test_config(rnd)
        id_str = (f"{i}_{geom_name}_mem{mem_ew}_reg{reg_ew}_start{start_index}"
                  f"_n{n_elements}_off{mem_offset}")
        params_list.append(pytest.param(
            geom_params, mem_ew, reg_ew, start_index, n_elements, mem_offset, id=id_str))
    return params_list


@pytest.mark.parametrize("params,mem_ew,reg_ew,start_index,n_elements,mem_offset", generate_test_params())
def test_mapping_consistency(params, mem_ew, reg_ew, start_index, n_elements, mem_offset):
    """Pytest test for mapping consistency."""
    assert check_mapping_consistency(params, mem_ew, reg_ew, start_index, n_elements, mem_offset)


def main():
    parser = argparse.ArgumentParser(description='Test RegMemMapping consistency')
    parser.add_argument('--k-cols', type=int, default=2)
    parser.add_argument('--k-rows', type=int, default=1)
    parser.add_argument('--j-cols', type=int, default=1)
    parser.add_argument('--j-rows', type=int, default=1)
    parser.add_argument('--mem-ew', type=int, default=None,
                        help='Test only this mem element width')
    parser.add_argument('--reg-ew', type=int, default=None,
                        help='Test only this reg element width')
    parser.add_argument('--start-index', type=int, default=None)
    parser.add_argument('--n-elements', type=int, default=None)
    parser.add_argument('--mem-offset', type=int, default=None)
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format='%(message)s')

    if args.mem_ew is not None and args.reg_ew is not None:
        params = create_test_params(args.k_cols, args.k_rows, args.j_cols, args.j_rows)
        start_index = args.start_index if args.start_index is not None else 0
        n_elements = args.n_elements if args.n_elements is not None else 16
        mem_offset = args.mem_offset if args.mem_offset is not None else 0

        success = check_mapping_consistency(
            params, args.mem_ew, args.reg_ew, start_index, n_elements, mem_offset
        )
        return 0 if success else 1

    failures = run_tests(args.k_cols, args.k_rows, args.j_cols, args.j_rows)
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    exit(main())
