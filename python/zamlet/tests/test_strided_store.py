"""
Test strided vector store operations with page fault handling.

Tests StoreStride instruction with mixed page types:
- VPU pages (various ew, always idempotent)
- Idempotent scalar pages
- Non-idempotent scalar pages
- Unallocated pages (trigger faults)

Key test: For non-idempotent pages, we must not write past a fault.
"""

import asyncio
import logging
from enum import Enum
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import LamletParams
from zamlet.addresses import GlobalAddress, MemoryType, Ordering, WordOrder
from zamlet.geometries import GEOMETRIES, scale_n_tests
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, unpack_elements, get_vpu_base_addr
)

logger = logging.getLogger(__name__)


class PageType(Enum):
    VPU_EW8 = 'vpu_ew8'
    VPU_EW16 = 'vpu_ew16'
    VPU_EW32 = 'vpu_ew32'
    VPU_EW64 = 'vpu_ew64'
    SCALAR_IDEMPOTENT = 'scalar_idempotent'
    SCALAR_NON_IDEMPOTENT = 'scalar_non_idempotent'
    UNALLOCATED = 'unallocated'


PAGE_TYPE_EW = {
    PageType.VPU_EW8: 8,
    PageType.VPU_EW16: 16,
    PageType.VPU_EW32: 32,
    PageType.VPU_EW64: 64,
}


def allocate_page(lamlet, base_addr: int, page_idx: int, page_type: PageType):
    """Allocate a single page with the specified type."""
    page_bytes = lamlet.params.page_bytes
    page_addr = base_addr + page_idx * page_bytes
    g_addr = GlobalAddress(bit_addr=page_addr * 8, params=lamlet.params)

    if page_type == PageType.UNALLOCATED:
        return
    elif page_type in PAGE_TYPE_EW:
        ew = PAGE_TYPE_EW[page_type]
        ordering = Ordering(WordOrder.STANDARD, ew)
        lamlet.allocate_memory(g_addr, page_bytes, memory_type=MemoryType.VPU, ordering=ordering)
    elif page_type == PageType.SCALAR_IDEMPOTENT:
        lamlet.allocate_memory(g_addr, page_bytes, memory_type=MemoryType.SCALAR_IDEMPOTENT,
                               ordering=None)
    elif page_type == PageType.SCALAR_NON_IDEMPOTENT:
        lamlet.allocate_memory(g_addr, page_bytes, memory_type=MemoryType.SCALAR_NON_IDEMPOTENT,
                               ordering=None)


def generate_page_types(n_pages: int, rnd: Random) -> list[PageType]:
    """Generate a random mix of page types."""
    all_types = list(PageType)
    return [rnd.choice(all_types) for _ in range(n_pages)]


async def run_strided_store_test(
    clock: Clock,
    ew: int,
    vl: int,
    stride: int,
    params: LamletParams,
    seed: int,
):
    """Test strided vector store operations with mixed page types.

    1. Write source data contiguously to VPU memory
    2. Load into register
    3. Store with stride to mixed page types
    4. Read back at strided locations and verify
    5. Check faults and non-idempotent write ordering
    """
    lamlet = await setup_lamlet(clock, params)

    rnd = Random(seed)
    element_bytes = ew // 8
    src_list = [rnd.getrandbits(ew) for i in range(vl)]

    logger.info(f"Test parameters: ew={ew}, vl={vl}, stride={stride}, seed={seed}")

    # Calculate memory layout
    src_base = get_vpu_base_addr(ew)
    dst_base = get_vpu_base_addr(ew) + 0x100000
    mem_size = (vl - 1) * stride + element_bytes + 64
    page_bytes = params.page_bytes
    alloc_size = ((max(1024, mem_size) + page_bytes - 1) // page_bytes) * page_bytes
    n_pages = alloc_size // page_bytes

    # Generate random page types for destination
    page_types = generate_page_types(n_pages, rnd)

    logger.info(f"Destination page types ({n_pages} pages):")
    for i, pt in enumerate(page_types):
        logger.info(f"  Page {i}: {pt.value}")

    # Allocate source pages as VPU (contiguous)
    src_ordering = Ordering(WordOrder.STANDARD, ew)
    src_alloc_size = vl * element_bytes
    src_n_pages = (src_alloc_size + page_bytes - 1) // page_bytes
    for i in range(src_n_pages):
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
        await lamlet.set_memory(addr, pack_elements([val], ew))

    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[ew]

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_strided_store")

    # Load source data into register (contiguous)
    await lamlet.vload(
        vd=0,
        addr=src_base,
        ordering=src_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=None,
        parent_span_id=span_id,
    )

    # Clear non-idempotent write log before the strided store
    lamlet.scalar.non_idempotent_write_log.clear()

    # Store with stride to mixed page types
    reg_ordering = Ordering(WordOrder.STANDARD, ew)
    result = await lamlet.vstore(
        vs=0,
        addr=dst_base,
        ordering=reg_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=None,
        parent_span_id=span_id,
        stride_bytes=stride,
    )

    # Calculate expected fault element (first element hitting unallocated page)
    expected_fault_element = None
    for i in range(vl):
        addr = dst_base + i * stride
        page_idx = (addr - dst_base) // page_bytes
        if page_idx < len(page_types) and page_types[page_idx] == PageType.UNALLOCATED:
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

    # Verify non-idempotent writes: all elements before fault that target non-idempotent pages
    # should have been written (order doesn't matter for unordered stores)
    expected_non_idemp_addrs = set()
    for i in range(n_expected_correct):
        global_addr = dst_base + i * stride
        page_idx = (global_addr - dst_base) // page_bytes
        if page_idx < len(page_types) and page_types[page_idx] == PageType.SCALAR_NON_IDEMPOTENT:
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

    # Verify correct elements were stored (only to allocated pages)
    errors = []
    for i in range(n_expected_correct):
        addr = dst_base + i * stride
        page_idx = (addr - dst_base) // page_bytes
        if page_idx >= len(page_types):
            continue
        pt = page_types[page_idx]

        if pt == PageType.UNALLOCATED:
            continue

        future = await lamlet.get_memory(addr, element_bytes)
        await future
        result = unpack_elements(future.result(), ew)[0]
        if result != src_list[i]:
            errors.append(f"  [{i}] expected={src_list[i]} actual={result} page_type={pt.value}")

    if errors:
        logger.error(f"FAIL: {len(errors)} elements do not match")
        for err in errors[:16]:
            logger.error(err)
        return 1

    logger.info(f"PASS: {n_expected_correct} elements correct"
                f"{f', fault at {expected_fault_element}' if expected_fault_element else ''}")
    lamlet.monitor.finalize_children(span_id)
    return 0


async def main(clock, **kwargs):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)
    clock.register_main()
    clock.create_task(clock.clock_driver())

    exit_code = await run_strided_store_test(clock, **kwargs)
    clock.running = False
    return exit_code


def run_test(ew: int, vl: int, stride: int, params: LamletParams, seed: int):
    """Helper to run a single test configuration."""
    clock = Clock(max_cycles=10000)
    exit_code = asyncio.run(main(clock, ew=ew, vl=vl, stride=stride, params=params, seed=seed))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def random_stride(rnd: Random, element_bytes: int, page_bytes: int) -> int:
    """Generate a random stride with roughly logarithmic distribution.

    Ranges from element_bytes+1 to several page_bytes, using multiple linear
    ranges to approximate logarithmic distribution. We avoid stride == element_bytes
    because that triggers the unit-stride path which has incomplete scalar memory support.
    """
    range_choice = rnd.randint(0, 3)
    if range_choice == 0:
        # Small: element_bytes+1 to 4x element_bytes
        return rnd.randint(element_bytes + 1, element_bytes * 4)
    elif range_choice == 1:
        # Medium: 4x element_bytes to 64 bytes
        return rnd.randint(element_bytes * 4, max(element_bytes * 4, 64))
    elif range_choice == 2:
        # Large: 64 bytes to page_bytes
        return rnd.randint(64, page_bytes)
    else:
        # Very large: page_bytes to 4x page_bytes
        return rnd.randint(page_bytes, page_bytes * 4)


def random_test_config(rnd: Random):
    """Generate a random test configuration."""
    geom_name = rnd.choice(list(GEOMETRIES.keys()))
    geom_params = GEOMETRIES[geom_name]
    ew = rnd.choice([8, 16, 32, 64])
    vl = rnd.randint(1, 32)
    element_bytes = ew // 8
    stride = random_stride(rnd, element_bytes, geom_params.page_bytes)
    return geom_name, geom_params, ew, vl, stride


def generate_test_params(n_tests: int = 64, seed: int = 42):
    """Generate random test parameter combinations."""
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name, geom_params, ew, vl, stride = random_test_config(rnd)
        # Use i as the seed for each test so page types vary
        id_str = f"{i}_{geom_name}_ew{ew}_vl{vl}_s{stride}"
        test_params.append(pytest.param(geom_params, ew, vl, stride, i, id=id_str))
    return test_params


@pytest.mark.parametrize("params,ew,vl,stride,seed", generate_test_params(n_tests=scale_n_tests(32)))
def test_strided_store(params, ew, vl, stride, seed):
    """Strided store with random mix of page types."""
    run_test(ew=ew, vl=vl, stride=stride, params=params, seed=seed)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test strided vector store with page faults')
    parser.add_argument('--ew', type=int, default=64, help='Element width in bits')
    parser.add_argument('--vl', type=int, default=16, help='Vector length')
    parser.add_argument('--stride', type=int, default=None, help='Stride in bytes (default: 2*ew/8)')
    parser.add_argument('--seed', type=int, default=0, help='Random seed')
    parser.add_argument('--geometry', '-g', default='k2x1_j1x1',
                        help='Geometry name (default: k2x1_j1x1)')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries and exit')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    params = get_geometry(args.geometry)
    stride = args.stride if args.stride is not None else args.ew // 8 * 2
    run_test(ew=args.ew, vl=args.vl, stride=stride, params=params, seed=args.seed)
