"""
Test ordered indexed (scatter) stores with page fault handling.

Tests vstore_indexed_ordered with mixed page types:
- VPU pages (various ew, always idempotent)
- Idempotent scalar pages
- Non-idempotent scalar pages
- Unallocated pages (trigger faults)

Key difference from unordered: writes must happen in element order,
and a fault at element N means elements 0..N-1 were written in order,
and elements N+ were not written at all.
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
    setup_mask_register,
    PageType, allocate_page, generate_page_types, generate_indices, setup_index_register,
    random_vl, max_vl_for_indexed, random_start_index, choose_mask_pattern, generate_mask_pattern,
)

logger = logging.getLogger(__name__)


async def setup_data_register(lamlet, data_reg: int, values: list[int], data_ew: int,
                               base_addr: int):
    """Write values to memory and load into a vector register."""
    element_bytes = data_ew // 8
    data_mem_addr = base_addr + 0x300000
    page_bytes = lamlet.params.page_bytes

    data_size = len(values) * element_bytes + 64
    n_pages = (max(1024, data_size) + page_bytes - 1) // page_bytes
    data_ordering = Ordering(WordOrder.STANDARD, data_ew)

    for page_idx in range(n_pages):
        page_addr = data_mem_addr + page_idx * page_bytes
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=page_addr * 8, params=lamlet.params),
            page_bytes, memory_type=MemoryType.VPU, ordering=data_ordering)

    for i, val in enumerate(values):
        addr = data_mem_addr + i * element_bytes
        await lamlet.set_memory(addr, pack_elements([val], data_ew))

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="setup_data")
    await lamlet.vload(
        vd=data_reg,
        addr=data_mem_addr,
        ordering=data_ordering,
        n_elements=len(values),
        mask_reg=None,
        start_index=0,
        parent_span_id=span_id,
    )
    lamlet.monitor.finalize_children(span_id)


async def run_ordered_indexed_store_test(
    clock: Clock,
    data_ew: int,
    index_ew: int,
    vl: int,
    n_pages: int,
    params: LamletParams,
    seed: int,
    start_index: int = 0,
    use_mask: bool = True,
):
    """Test ordered indexed store with mixed page types and fault handling."""
    lamlet = await setup_lamlet(clock, params)

    rnd = Random(seed)
    element_bytes = data_ew // 8
    page_bytes = params.page_bytes

    # When using masks, vl is limited by mask register size
    if use_mask:
        max_vl = params.j_in_l * params.word_bytes * 8
        assert vl <= max_vl, f"vl={vl} exceeds max {max_vl} for masked operation"

    logger.info(f"Test parameters: data_ew={data_ew}, index_ew={index_ew}, vl={vl}, "
                f"n_pages={n_pages}, seed={seed}, start_index={start_index}, use_mask={use_mask}")

    dst_base = get_vpu_base_addr(data_ew)

    page_types = generate_page_types(n_pages, rnd)
    indices = generate_indices(vl, data_ew, n_pages, page_bytes, rnd, allow_duplicates=True)
    values = [rnd.getrandbits(data_ew) for _ in range(vl)]
    mask_bits = generate_mask_pattern(vl, choose_mask_pattern(rnd), rnd) if use_mask else None

    logger.info(f"Page types ({n_pages} pages):")
    for i, pt in enumerate(page_types):
        logger.info(f"  Page {i}: {pt.value}")
    logger.info(f"Indices: {indices[:16]}{'...' if len(indices) > 16 else ''}")
    logger.info(f"Values: {[hex(v) for v in values[:8]]}{'...' if len(values) > 8 else ''}")
    if mask_bits:
        logger.info(f"Mask bits: {mask_bits[:16]}{'...' if len(mask_bits) > 16 else ''}")

    # Allocate destination pages
    for i, pt in enumerate(page_types):
        allocate_page(lamlet, dst_base, i, pt)

    # Initialize destination memory to zeros (for masked element verification)
    for offset in set(indices):
        page_idx = offset // page_bytes
        if page_types[page_idx] != PageType.UNALLOCATED:
            await lamlet.set_memory(dst_base + offset, bytes(element_bytes))

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
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_ordered_indexed_store")

    await setup_index_register(lamlet, index_reg, indices, index_ew, dst_base)
    await setup_data_register(lamlet, data_reg, values, data_ew, dst_base)

    # Set up mask register if using masks
    mask_reg = None
    if use_mask:
        mask_reg = index_reg + n_index_regs
        assert mask_reg < lamlet.params.n_vregs, \
            f'mask_reg {mask_reg} exceeds n_vregs {lamlet.params.n_vregs}'
        mask_mem_addr = dst_base + 0x400000
        await setup_mask_register(lamlet, mask_reg, mask_bits, page_bytes, mask_mem_addr)

    # Clear non-idempotent write log before the store
    lamlet.scalar.non_idempotent_write_log.clear()

    result = await lamlet.vstore_indexed_ordered(
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

    # Wait for ordered buffer to complete
    while any(buf is not None for buf in lamlet._ordered_buffers):
        await clock.next_cycle

    # Calculate expected fault element (first ACTIVE element hitting unallocated page)
    # Only elements >= start_index are processed
    expected_fault_element = None
    for i in range(start_index, vl):
        is_masked = use_mask and not mask_bits[i]
        if is_masked:
            continue  # Masked elements don't cause faults
        offset = indices[i]
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

    # Verify non-idempotent writes happen in ORDER for elements in [start_index, fault)
    # Only active (unmasked) elements should be written
    expected_write_order = []
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
            expected_write_order.append(local_addr)

    actual_write_order = lamlet.scalar.non_idempotent_write_log

    if expected_write_order or actual_write_order:
        logger.info(f"Non-idempotent writes: expected {len(expected_write_order)}, "
                    f"actual {len(actual_write_order)}")
        if actual_write_order != expected_write_order:
            logger.error("Write order mismatch!")
            logger.error(f"  Expected: {expected_write_order[:16]}...")
            logger.error(f"  Actual:   {actual_write_order[:16]}...")
            lamlet.monitor.print_summary()
            return 1
        else:
            logger.info("Write order verified correct")

    # Verify memory state for elements before fault
    # Build expected byte values, processing in element order
    expected_bytes = {}  # byte_offset -> expected_value

    # Prestart elements (0 to start_index) should remain zero
    for i in range(start_index):
        offset = indices[i]
        page_idx = offset // page_bytes
        if page_types[page_idx] == PageType.UNALLOCATED:
            continue  # Can't verify unallocated pages
        for b_idx in range(element_bytes):
            byte_offset = offset + b_idx
            if byte_offset not in expected_bytes:
                expected_bytes[byte_offset] = 0

    # Active elements (start_index to n_expected_correct)
    for i in range(start_index, n_expected_correct):
        is_masked = use_mask and not mask_bits[i]
        offset = indices[i]
        page_idx = offset // page_bytes
        if page_types[page_idx] == PageType.UNALLOCATED:
            continue  # Can't verify unallocated pages
        val_bytes = values[i].to_bytes(element_bytes, byteorder='little')
        for b_idx in range(element_bytes):
            byte_offset = offset + b_idx
            if is_masked:
                if byte_offset not in expected_bytes:
                    expected_bytes[byte_offset] = 0
            else:
                expected_bytes[byte_offset] = val_bytes[b_idx]

    errors = []
    for byte_offset, expected_byte in expected_bytes.items():
        global_addr = dst_base + byte_offset
        actual_data = await lamlet.get_memory_blocking(global_addr, 1)
        actual_byte = actual_data[0]
        if actual_byte != expected_byte:
            errors.append(f"Byte at offset {byte_offset}: expected {expected_byte:#x}, "
                          f"got {actual_byte:#x}")

    if errors:
        logger.error(f"FAIL: {len(errors)} bytes do not match")
        for err in errors[:16]:
            logger.error(err)
        return 1

    logger.info(f"PASS: {n_expected_correct} elements correct")
    lamlet.monitor.finalize_children(span_id)
    lamlet.monitor.print_summary()
    return 0


async def main(clock, data_ew, index_ew, vl, n_pages, params, seed, start_index=0, use_mask=True):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)
    clock.register_main()
    clock.create_task(clock.clock_driver())

    exit_code = await run_ordered_indexed_store_test(
        clock, data_ew=data_ew, index_ew=index_ew, vl=vl,
        n_pages=n_pages, params=params, seed=seed, start_index=start_index, use_mask=use_mask)
    clock.running = False
    return exit_code


def run_test(data_ew: int, index_ew: int, vl: int, n_pages: int, params: LamletParams, seed: int,
             start_index: int = 0, use_mask: bool = True):
    """Helper to run a single test configuration."""
    clock = Clock(max_cycles=100000)
    exit_code = asyncio.run(main(clock, data_ew=data_ew, index_ew=index_ew, vl=vl,
                                  n_pages=n_pages, params=params, seed=seed,
                                  start_index=start_index, use_mask=use_mask))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def random_test_config(rnd: Random):
    """Generate a random test configuration."""
    geom_name = rnd.choice(list(GEOMETRIES.keys()))
    geom_params = GEOMETRIES[geom_name]
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
def test_ordered_indexed_store(params, data_ew, index_ew, vl, n_pages, start_index, seed):
    """Ordered indexed store with random mix of page types."""
    run_test(data_ew=data_ew, index_ew=index_ew, vl=vl, n_pages=n_pages, params=params, seed=seed,
             start_index=start_index)


if __name__ == '__main__':
    import sys
    import argparse

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test ordered indexed store with page faults')
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
             start_index=args.start_index, use_mask=use_mask)
