"""
Test strided vector load operations with page fault handling.

Tests LoadStride instruction with mixed page types:
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
from zamlet.geometries import GEOMETRIES, scale_n_tests
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, unpack_elements, get_vpu_base_addr,
    setup_mask_register, zero_register, dump_span_trees,
    PageType, allocate_page, generate_page_types, random_stride, random_vl,
    random_start_index, choose_mask_pattern, generate_mask_pattern,
)

logger = logging.getLogger(__name__)


async def run_strided_load_test(
    clock: Clock,
    ew: int,
    vl: int,
    stride: int,
    params: LamletParams,
    seed: int,
    start_index: int = 0,
    use_mask: bool = True,
    dump_spans: bool = False,
):
    """Test strided vector load operations with mixed page types."""
    lamlet = await setup_lamlet(clock, params)

    try:
        return await _run_strided_load_test_inner(
            lamlet, clock, ew, vl, stride, params, seed, start_index, use_mask)
    finally:
        if dump_spans:
            dump_span_trees(lamlet.monitor)


async def _run_strided_load_test_inner(
    lamlet,
    clock: Clock,
    ew: int,
    vl: int,
    stride: int,
    params: LamletParams,
    seed: int,
    start_index: int,
    use_mask: bool,
):
    rnd = Random(seed)
    element_bytes = ew // 8
    src_list = [rnd.getrandbits(ew) for i in range(vl)]

    # When using masks, vl is limited by mask register size
    if use_mask:
        max_vl = params.j_in_l * params.word_bytes * 8
        assert vl <= max_vl, f"vl={vl} exceeds max {max_vl} for masked operation"

    logger.info(f"Test parameters: ew={ew}, vl={vl}, stride={stride}, seed={seed}, "
                f"start_index={start_index}, use_mask={use_mask}")

    # Calculate memory layout
    src_base = get_vpu_base_addr(ew)
    mem_size = (vl - 1) * stride + element_bytes + 64
    # Ensure dst_base doesn't overlap with source
    dst_offset = ((mem_size + 0xFFFFF) // 0x100000) * 0x100000  # Round up to 1MB boundary
    dst_base = src_base + dst_offset
    page_bytes = params.page_bytes
    alloc_size = ((max(1024, mem_size) + page_bytes - 1) // page_bytes) * page_bytes
    n_pages = alloc_size // page_bytes

    # Generate random page types
    page_types = generate_page_types(n_pages, rnd)
    mask_bits = generate_mask_pattern(vl, choose_mask_pattern(rnd), rnd) if use_mask else None

    logger.info(f"Page types ({n_pages} pages):")
    for i, pt in enumerate(page_types):
        logger.info(f"  Page {i}: {pt.value}")
    if mask_bits:
        logger.info(f"Mask bits: {mask_bits[:16]}{'...' if len(mask_bits) > 16 else ''}")

    # Allocate source pages
    for i, pt in enumerate(page_types):
        allocate_page(lamlet, src_base, i, pt)

    # Allocate all destination pages as VPU
    dst_ordering = Ordering(WordOrder.STANDARD, ew)
    for i in range(n_pages):
        page_addr = dst_base + i * page_bytes
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=page_addr * 8, params=params),
            page_bytes, memory_type=MemoryType.VPU, ordering=dst_ordering)

    # Write source data at strided locations (only to allocated pages)
    # Write byte-by-byte to handle elements spanning page boundaries
    for i, val in enumerate(src_list):
        offset = i * stride
        val_bytes = pack_elements([val], ew)
        for byte_off, byte_val in enumerate(val_bytes):
            page_idx = (offset + byte_off) // page_bytes
            if page_idx < len(page_types) and page_types[page_idx] != PageType.UNALLOCATED:
                await lamlet.set_memory(src_base + offset + byte_off, bytes([byte_val]))

    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[ew]

    elements_per_vline = params.vline_bytes * 8 // ew
    n_data_regs = (vl + elements_per_vline - 1) // elements_per_vline
    data_reg = 0

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_strided_load")

    # Set up mask register if using masks
    mask_reg = None
    if use_mask:
        mask_reg = n_data_regs
        assert mask_reg < lamlet.params.n_vregs, \
            f'mask_reg {mask_reg} exceeds n_vregs {lamlet.params.n_vregs}'
        mask_mem_addr = src_base + 0x400000
        await setup_mask_register(lamlet, mask_reg, mask_bits, page_bytes, mask_mem_addr)

        # Initialize data register to zeros so we can verify masked elements unchanged
        zero_mem_addr = src_base + 0x500000
        await zero_register(lamlet, data_reg, vl, ew, page_bytes, zero_mem_addr)

    # Clear non-idempotent access log before the load
    lamlet.scalar.non_idempotent_access_log.clear()

    reg_ordering = Ordering(WordOrder.STANDARD, ew)
    result = await lamlet.vload(
        vd=data_reg,
        addr=src_base,
        ordering=reg_ordering,
        n_elements=vl,
        start_index=start_index,
        mask_reg=mask_reg,
        parent_span_id=span_id,
        stride_bytes=stride,
    )

    # Calculate expected fault element (first ACTIVE element hitting unallocated page)
    # Check all pages the element spans, not just the starting page
    # Only elements >= start_index are processed
    expected_fault_element = None
    for i in range(start_index, vl):
        is_masked = use_mask and not mask_bits[i]
        if is_masked:
            continue  # Masked elements don't cause faults
        offset = i * stride
        start_page = offset // page_bytes
        end_page = (offset + element_bytes - 1) // page_bytes
        for page_idx in range(start_page, end_page + 1):
            assert page_idx < len(page_types)
            if page_types[page_idx] == PageType.UNALLOCATED:
                expected_fault_element = i
                break
        if expected_fault_element is not None:
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

    # Verify non-idempotent reads: all ACTIVE elements in [start_index, fault) that target
    # non-idempotent pages should have been read
    expected_non_idemp_addrs = set()
    for i in range(start_index, n_expected_correct):
        is_masked = use_mask and not mask_bits[i]
        if is_masked:
            continue
        global_addr = src_base + i * stride
        page_idx = (global_addr - src_base) // page_bytes
        if page_idx < len(page_types) and page_types[page_idx] == PageType.SCALAR_NON_IDEMPOTENT:
            g_addr = GlobalAddress(bit_addr=global_addr * 8, params=params)
            local_addr = lamlet.to_scalar_addr(g_addr)
            expected_non_idemp_addrs.add(local_addr)

    actual_non_idemp_addrs = set(lamlet.scalar.non_idempotent_access_log)
    if expected_non_idemp_addrs or actual_non_idemp_addrs:
        logger.info(f"Non-idempotent reads: expected {len(expected_non_idemp_addrs)}, "
                    f"actual {len(actual_non_idemp_addrs)}")
        assert actual_non_idemp_addrs == expected_non_idemp_addrs, \
            f"Non-idempotent read mismatch: expected {expected_non_idemp_addrs}, " \
            f"got {actual_non_idemp_addrs}"

    # Verify correct elements were loaded
    if n_expected_correct > 0:
        await lamlet.vstore(
            vs=data_reg,
            addr=dst_base,
            ordering=dst_ordering,
            n_elements=n_expected_correct,
            start_index=0,
            mask_reg=None,
            parent_span_id=span_id,
        )

        errors = []

        # Verify prestart elements (0 to start_index) remain zero in the register
        for i in range(start_index):
            addr = dst_base + i * element_bytes
            future = await lamlet.get_memory(addr, element_bytes)
            await future
            actual = unpack_elements(future.result(), ew)[0]
            if actual != 0:
                errors.append(f"  [{i}] prestart: expected=0 actual={actual:#x}")

        # Verify active elements (start_index to n_expected_correct)
        for i in range(start_index, n_expected_correct):
            addr = dst_base + i * element_bytes
            future = await lamlet.get_memory(addr, element_bytes)
            await future
            actual = unpack_elements(future.result(), ew)[0]
            is_masked = use_mask and not mask_bits[i]
            if is_masked:
                # Masked elements should remain zero
                if actual != 0:
                    errors.append(f"  [{i}] masked: expected=0 actual={actual:#x}")
            else:
                if actual != src_list[i]:
                    errors.append(f"  [{i}] expected={src_list[i]:#x} actual={actual:#x}")

        if errors:
            logger.error(f"FAIL: {len(errors)} elements do not match")
            for err in errors[:16]:
                logger.error(err)
            return 1

    logger.info(f"PASS: {n_expected_correct} elements correct")
    lamlet.monitor.finalize_children(span_id)
    lamlet.monitor.print_summary()
    return 0


async def main(clock, **kwargs):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)
    clock.register_main()
    clock.create_task(clock.clock_driver())

    exit_code = await run_strided_load_test(clock, **kwargs)
    clock.running = False
    return exit_code


def run_test(ew: int, vl: int, stride: int, params: LamletParams, seed: int,
             start_index: int = 0, use_mask: bool = True, dump_spans: bool = False):
    """Helper to run a single test configuration."""
    clock = Clock(max_cycles=50000)
    exit_code = asyncio.run(main(clock, ew=ew, vl=vl, stride=stride, params=params, seed=seed,
                                  start_index=start_index, use_mask=use_mask, dump_spans=dump_spans))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def random_test_config(rnd: Random):
    """Generate a random test configuration."""
    geom_name = rnd.choice(list(GEOMETRIES.keys()))
    geom_params = GEOMETRIES[geom_name]
    ew = rnd.choice([8, 16, 32, 64])
    # Limit vl to mask register capacity
    max_vl = geom_params.j_in_l * geom_params.word_bytes * 8
    vl = random_vl(rnd, max_vl)
    element_bytes = ew // 8
    stride = random_stride(rnd, element_bytes, geom_params.page_bytes)
    start_index = random_start_index(rnd, vl)
    return geom_name, geom_params, ew, vl, stride, start_index


def generate_test_params(n_tests: int = 64, seed: int = 42):
    """Generate random test parameter combinations."""
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name, geom_params, ew, vl, stride, start_index = random_test_config(rnd)
        # Use i as the seed for each test so page types vary
        id_str = f"{i}_{geom_name}_ew{ew}_vl{vl}_s{stride}_si{start_index}"
        test_params.append(pytest.param(geom_params, ew, vl, stride, start_index, i, id=id_str))
    return test_params


@pytest.mark.parametrize("params,ew,vl,stride,start_index,seed",
                         generate_test_params(n_tests=scale_n_tests(32)))
def test_strided_load(params, ew, vl, stride, start_index, seed):
    """Strided load with random mix of page types."""
    run_test(ew=ew, vl=vl, stride=stride, params=params, seed=seed, start_index=start_index)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test strided vector load with page faults')
    parser.add_argument('--ew', type=int, default=64, help='Element width in bits')
    parser.add_argument('--vl', type=int, default=16, help='Vector length')
    parser.add_argument('--stride', type=int, default=None, help='Stride in bytes (default: 2*ew/8)')
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
    stride = args.stride if args.stride is not None else args.ew // 8 * 2
    use_mask = not args.no_mask
    run_test(ew=args.ew, vl=args.vl, stride=stride, params=params, seed=args.seed,
             start_index=args.start_index, use_mask=use_mask, dump_spans=args.dump_spans)
