"""
Test indexed vector store operations with page fault handling.

Tests StoreIndexedUnordered instruction with mixed page types:
- VPU pages (various ew, always idempotent)
- Idempotent scalar pages
- Non-idempotent scalar pages
- Unallocated pages (trigger faults)
"""

import asyncio
import logging
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import LamletParams
from zamlet.addresses import GlobalAddress, MemoryType, Ordering, WordOrder
from zamlet.geometries import SMALL_GEOMETRIES, scale_n_tests
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, unpack_elements, get_vpu_base_addr,
    setup_mask_register, dump_span_trees,
    PageType, allocate_page, generate_page_types, generate_indices, setup_index_register,
    random_vl, max_vl_for_indexed, random_start_index, choose_mask_pattern, generate_mask_pattern,
)

logger = logging.getLogger(__name__)


async def run_indexed_store_test(
    clock: Clock,
    data_ew: int,
    index_ew: int,
    vl: int,
    n_pages: int,
    params: LamletParams,
    seed: int,
    start_index: int = 0,
    use_mask: bool = True,
    dump_spans: bool = False,
):
    """Test indexed vector store operations with mixed page types."""
    lamlet = await setup_lamlet(clock, params)

    try:
        return await _run_indexed_store_test_inner(
            lamlet, clock, data_ew, index_ew, vl, n_pages, params, seed, start_index, use_mask)
    finally:
        if dump_spans:
            dump_span_trees(lamlet.monitor)


async def _run_indexed_store_test_inner(
    lamlet,
    clock: Clock,
    data_ew: int,
    index_ew: int,
    vl: int,
    n_pages: int,
    params: LamletParams,
    seed: int,
    start_index: int,
    use_mask: bool,
):
    rnd = Random(seed)
    element_bytes = data_ew // 8

    # When using masks, vl is limited by mask register size
    if use_mask:
        max_vl = params.j_in_l * params.word_bytes * 8
        assert vl <= max_vl, f"vl={vl} exceeds max {max_vl} for masked operation"

    logger.info(f"Test parameters: data_ew={data_ew}, index_ew={index_ew}, vl={vl}, "
                f"n_pages={n_pages}, seed={seed}, start_index={start_index}, use_mask={use_mask}")

    src_base = get_vpu_base_addr(data_ew)
    dst_base = get_vpu_base_addr(data_ew) + 0x100000
    page_bytes = params.page_bytes

    page_types = generate_page_types(n_pages, rnd)
    indices = generate_indices(vl, data_ew, n_pages, page_bytes, rnd)
    mask_bits = generate_mask_pattern(vl, choose_mask_pattern(rnd), rnd) if use_mask else None

    # Generate source values - one per element
    src_list = [rnd.getrandbits(data_ew) for _ in range(vl)]

    logger.info(f"Destination page types ({n_pages} pages):")
    for i, pt in enumerate(page_types):
        logger.info(f"  Page {i}: {pt.value}")
    logger.info(f"Indices ({len(indices)}): {indices}")
    if mask_bits:
        logger.info(f"Mask bits: {mask_bits[:16]}{'...' if len(mask_bits) > 16 else ''}")

    # Allocate source pages (contiguous VPU)
    src_ordering = Ordering(WordOrder.STANDARD, data_ew)
    src_size = vl * element_bytes + 64
    n_src_pages = (max(1024, src_size) + page_bytes - 1) // page_bytes
    for i in range(n_src_pages):
        page_addr = src_base + i * page_bytes
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=page_addr * 8, params=params),
            page_bytes, memory_type=MemoryType.VPU, ordering=src_ordering)

    # Allocate destination pages with mixed types
    for i, pt in enumerate(page_types):
        allocate_page(lamlet, dst_base, i, pt)

    # Write source data contiguously
    for i, val in enumerate(src_list):
        addr = src_base + i * element_bytes
        await lamlet.set_memory(addr, pack_elements([val], data_ew))

    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[data_ew]

    elements_per_vline = params.vline_bytes * 8 // data_ew
    n_data_regs = (vl + elements_per_vline - 1) // elements_per_vline
    index_elements_per_vline = params.vline_bytes * 8 // index_ew
    n_index_regs = (vl + index_elements_per_vline - 1) // index_elements_per_vline

    data_reg = 0
    index_reg = n_data_regs

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_indexed_store")

    # Load source data into register (contiguous)
    await lamlet.vload(
        vd=data_reg,
        addr=src_base,
        ordering=src_ordering,
        n_elements=vl,
        mask_reg=None,
        start_index=0,
        parent_span_id=span_id,
    )

    # Setup index register
    await setup_index_register(lamlet, index_reg, indices, index_ew, dst_base)

    # Set up mask register if using masks
    mask_reg = None
    if use_mask:
        mask_reg = index_reg + n_index_regs
        assert mask_reg < lamlet.params.n_vregs, \
            f'mask_reg {mask_reg} exceeds n_vregs {lamlet.params.n_vregs}'
        mask_mem_addr = dst_base + 0x400000
        await setup_mask_register(lamlet, mask_reg, mask_bits, page_bytes, mask_mem_addr)

    # Initialize destination memory to zeros (for masked element verification)
    for offset in set(indices):
        page_idx = offset // page_bytes
        if page_types[page_idx] != PageType.UNALLOCATED:
            await lamlet.set_memory(dst_base + offset, bytes(element_bytes))

    # Clear non-idempotent write log before the indexed store
    lamlet.scalar.non_idempotent_write_log.clear()

    # Store to indexed destinations
    result = await lamlet.vstore_indexed_unordered(
        vs=data_reg,
        base_addr=dst_base,
        index_reg=index_reg,
        index_ew=index_ew,
        data_ew=data_ew,
        n_elements=vl,
        mask_reg=mask_reg,
        start_index=start_index,
        parent_span_id=span_id,
    )

    # Calculate expected fault element (first ACTIVE element hitting unallocated page)
    # Only elements >= start_index are processed
    expected_fault_element = None
    for i in range(start_index, vl):
        offset = indices[i]
        is_masked = use_mask and not mask_bits[i]
        if is_masked:
            continue  # Masked elements don't cause faults
        page_idx = offset // page_bytes
        assert page_idx < len(page_types)
        if page_types[page_idx] == PageType.UNALLOCATED:
            expected_fault_element = i
            break

    # Check fault matches expectation
    if expected_fault_element is not None:
        assert not result.success, \
            f"Expected fault at element {expected_fault_element}, but no fault returned"
        assert result.element_index == expected_fault_element, \
            f"Expected fault at element {expected_fault_element}, " \
            f"got {result.element_index}"
        logger.info(f"Fault correctly detected at element {expected_fault_element}")
        n_expected_correct = expected_fault_element
    else:
        assert result.success, f"Unexpected fault: {result}"
        n_expected_correct = vl

    # Verify non-idempotent writes: all ACTIVE elements in [start_index, fault) that target
    # non-idempotent pages should have been written (order doesn't matter for unordered stores)
    expected_non_idemp_addrs = set()
    for i in range(start_index, n_expected_correct):
        is_masked = use_mask and not mask_bits[i]
        if is_masked:
            continue
        offset = indices[i]
        page_idx = offset // page_bytes
        if page_idx < len(page_types) and page_types[page_idx] == PageType.SCALAR_NON_IDEMPOTENT:
            global_addr = dst_base + offset
            g_addr = GlobalAddress(bit_addr=global_addr * 8, params=params)
            local_addr = lamlet.to_scalar_addr(g_addr)
            expected_non_idemp_addrs.add(local_addr)

    actual_non_idemp_addrs = set(lamlet.scalar.non_idempotent_write_log)
    if expected_non_idemp_addrs or actual_non_idemp_addrs:
        logger.info(f"Non-idempotent writes: expected {len(expected_non_idemp_addrs)}, "
                    f"actual {len(actual_non_idemp_addrs)}")
        assert actual_non_idemp_addrs == expected_non_idemp_addrs, \
            f"Non-idempotent write mismatch: expected {expected_non_idemp_addrs}, " \
            f"got {actual_non_idemp_addrs}"

    # Verify correct elements were stored
    errors = []

    # Verify prestart elements (0 to start_index) remain zero (unchanged)
    for i in range(start_index):
        offset = indices[i]
        page_idx = offset // page_bytes
        if page_types[page_idx] == PageType.UNALLOCATED:
            continue
        addr = dst_base + offset
        future = await lamlet.get_memory(addr, element_bytes)
        await future
        actual = unpack_elements(future.result(), data_ew)[0]
        if actual != 0:
            errors.append(f"  [{i}] prestart: offset={offset} expected=0 actual={actual:#x}")

    # Verify active elements (start_index to n_expected_correct)
    for i in range(start_index, n_expected_correct):
        offset = indices[i]
        page_idx = offset // page_bytes
        if page_types[page_idx] == PageType.UNALLOCATED:
            continue
        addr = dst_base + offset
        future = await lamlet.get_memory(addr, element_bytes)
        await future
        actual = unpack_elements(future.result(), data_ew)[0]
        is_masked = use_mask and not mask_bits[i]
        if is_masked:
            # Masked elements should remain zero
            if actual != 0:
                errors.append(f"  [{i}] masked: offset={offset} expected=0 actual={actual:#x}")
        else:
            if actual != src_list[i]:
                errors.append(f"  [{i}] offset={offset} expected={src_list[i]:#x} actual={actual:#x}")

    if errors:
        logger.error(f"FAIL: {len(errors)} elements do not match")
        for err in errors[:16]:
            logger.error(err)
        return 1

    logger.info(f"PASS: {n_expected_correct} elements correct")
    lamlet.monitor.finalize_children(span_id)
    lamlet.monitor.print_summary()
    return 0


async def main(clock, data_ew, index_ew, vl, n_pages, params, seed, start_index=0,
               use_mask=True, dump_spans=False):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)
    clock.register_main()
    clock.create_task(clock.clock_driver())

    exit_code = await run_indexed_store_test(
        clock, data_ew=data_ew, index_ew=index_ew, vl=vl,
        n_pages=n_pages, params=params, seed=seed, start_index=start_index,
        use_mask=use_mask, dump_spans=dump_spans)
    clock.running = False
    return exit_code


def run_test(data_ew: int, index_ew: int, vl: int, n_pages: int, params: LamletParams, seed: int,
             start_index: int = 0, use_mask: bool = True, dump_spans: bool = False):
    """Helper to run a single test configuration."""
    clock = Clock(max_cycles=50000)
    exit_code = asyncio.run(main(clock, data_ew=data_ew, index_ew=index_ew, vl=vl,
                                  n_pages=n_pages, params=params, seed=seed,
                                  start_index=start_index, use_mask=use_mask,
                                  dump_spans=dump_spans))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def random_test_config(rnd: Random):
    """Generate a random test configuration."""
    geom_name = rnd.choice(list(SMALL_GEOMETRIES.keys()))
    geom_params = SMALL_GEOMETRIES[geom_name]
    data_ew = rnd.choice([8, 16, 32, 64])
    n_pages = rnd.randint(2, 6)
    # index_ew must be large enough to hold max offset (n_pages * page_bytes)
    max_offset = n_pages * geom_params.page_bytes
    if max_offset <= 256:
        index_ew = rnd.choice([8, 16, 32, 64])
    elif max_offset <= 65536:
        index_ew = rnd.choice([16, 32, 64])
    else:
        index_ew = rnd.choice([32, 64])
    # Limit vl by mask capacity and register availability
    max_vl_mask = geom_params.j_in_l * geom_params.word_bytes * 8
    max_vl_regs = max_vl_for_indexed(geom_params, data_ew, index_ew)
    vl = random_vl(rnd, min(max_vl_mask, max_vl_regs))
    start_index = random_start_index(rnd, vl)
    return geom_name, geom_params, data_ew, index_ew, vl, n_pages, start_index


def generate_test_params(n_tests: int = 64, seed: int = 42):
    """Generate random test parameter combinations."""
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name, geom_params, data_ew, index_ew, vl, n_pages, start_index = random_test_config(rnd)
        id_str = f"{i}_{geom_name}_dew{data_ew}_iew{index_ew}_vl{vl}_p{n_pages}_si{start_index}"
        test_params.append(pytest.param(
            geom_params, data_ew, index_ew, vl, n_pages, start_index, i, id=id_str))
    return test_params


@pytest.mark.parametrize("params,data_ew,index_ew,vl,n_pages,start_index,seed",
                         generate_test_params(n_tests=scale_n_tests(32)))
def test_indexed_store(params, data_ew, index_ew, vl, n_pages, start_index, seed):
    """Indexed store with random mix of page types."""
    run_test(data_ew=data_ew, index_ew=index_ew, vl=vl, n_pages=n_pages, params=params, seed=seed,
             start_index=start_index)


if __name__ == '__main__':
    import sys
    import argparse

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test indexed vector store with page faults')
    parser.add_argument('--data-ew', type=int, default=64, help='Data element width in bits')
    parser.add_argument('--index-ew', type=int, default=32, help='Index element width in bits')
    parser.add_argument('--vl', type=int, default=8, help='Vector length')
    parser.add_argument('--n-pages', type=int, default=4, help='Number of pages to allocate')
    parser.add_argument('--start-index', type=int, default=0, help='Start index (vstart)')
    parser.add_argument('--seed', type=int, default=0, help='Random seed')
    parser.add_argument('--geometry', '-g', default='k2x1_j1x1',
                        help='Geometry name (default: k2x1_j1x1)')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries and exit')
    parser.add_argument('--no-mask', action='store_true',
                        help='Disable mask testing (default: use random mask)')
    parser.add_argument('--dump-spans', action='store_true',
                        help='Dump span trees to span_trees.txt')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    params = get_geometry(args.geometry)
    use_mask = not args.no_mask
    run_test(data_ew=args.data_ew, index_ew=args.index_ew, vl=args.vl,
             n_pages=args.n_pages, params=params, seed=args.seed,
             start_index=args.start_index, use_mask=use_mask, dump_spans=args.dump_spans)
