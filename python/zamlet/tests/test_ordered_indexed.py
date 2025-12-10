"""
Test for ordered indexed (gather) loads from scalar memory.

The key difference from unordered VPU loads:
- Source memory is scalar (not VPU)
- ordered=True is passed to vload_indexed
- Lamlet buffers requests, syncs, then reads in element order
"""

import asyncio
import logging
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import LamletParams
from zamlet.geometries import GEOMETRIES, scale_n_tests
from zamlet.lamlet.lamlet import Lamlet
from zamlet.addresses import GlobalAddress, Ordering, WordOrder
from zamlet.monitor import CompletionType, SpanType

logger = logging.getLogger(__name__)


async def update(clock, lamlet):
    """Update loop for the lamlet"""
    while True:
        await clock.next_update
        lamlet.update()


async def setup_lamlet(clock: Clock, params: LamletParams) -> Lamlet:
    """Create and initialize a lamlet with update loop."""
    lamlet = Lamlet(clock, params)
    clock.create_task(update(clock, lamlet))
    clock.create_task(lamlet.run())
    clock.on_timeout = lambda: lamlet.monitor.print_summary()
    await clock.next_cycle
    return lamlet


def allocate_vpu_pages(lamlet: Lamlet, base_addr: int, n_pages: int, page_bytes: int, ew: int):
    """Allocate VPU memory pages."""
    ordering = Ordering(WordOrder.STANDARD, ew)
    for page_idx in range(n_pages):
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=(base_addr + page_idx * page_bytes) * 8, params=lamlet.params),
            page_bytes,
            is_vpu=True,
            ordering=ordering
        )


def allocate_scalar_pages(lamlet: Lamlet, base_addr: int, n_pages: int, page_bytes: int):
    """Allocate scalar memory pages."""
    for page_idx in range(n_pages):
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=(base_addr + page_idx * page_bytes) * 8, params=lamlet.params),
            page_bytes,
            is_vpu=False,
            ordering=None
        )


def generate_random_indices(rnd: Random, vl: int, data_ew: int, index_ew: int,
                            max_region_bytes: int) -> list[int]:
    """Generate random byte offsets for indexed access."""
    element_bytes = data_ew // 8
    max_index = (1 << index_ew) - 1
    max_offset = min(max_index, max_region_bytes - element_bytes)
    max_offset = (max_offset // element_bytes) * element_bytes

    indices = []
    for _ in range(vl):
        offset = rnd.randint(0, max_offset // element_bytes) * element_bytes
        indices.append(offset)
    return indices


async def setup_index_register(lamlet: Lamlet, index_reg: int, indices: list[int],
                               index_ew: int, page_bytes: int, base_addr: int):
    """Write indices to memory and load into a vector register."""
    index_bytes = index_ew // 8
    index_mem_addr = base_addr + 0x20000

    # Allocate memory for index data
    index_size = len(indices) * index_bytes + 64
    n_pages = (max(1024, index_size) + page_bytes - 1) // page_bytes
    allocate_vpu_pages(lamlet, index_mem_addr, n_pages, page_bytes, index_ew)

    # Write indices to memory
    for i, idx in enumerate(indices):
        addr = index_mem_addr + i * index_bytes
        await lamlet.set_memory(addr, idx.to_bytes(index_bytes, byteorder='little'))

    # Load into register
    index_ordering = Ordering(WordOrder.STANDARD, index_ew)
    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="setup_index")
    assert span_id is not None
    await lamlet.vload(
        vd=index_reg,
        addr=index_mem_addr,
        ordering=index_ordering,
        n_elements=len(indices),
        mask_reg=None,
        start_index=0,
        parent_span_id=span_id,
    )
    lamlet.monitor.finalize_children(span_id)


def get_base_addr(element_width: int) -> int:
    """Get the memory base address for a given element width."""
    if element_width == 8:
        return 0x20000000
    elif element_width == 16:
        return 0x20800000
    elif element_width == 32:
        return 0x90080000
    elif element_width == 64:
        return 0x90100000
    else:
        raise ValueError(f"Unsupported element width: {element_width}")


async def run_ordered_scalar_load_test(
    clock: Clock,
    data_ew: int,
    index_ew: int,
    vl: int,
    params: LamletParams,
    seed: int,
):
    """Test ordered indexed (gather) load from scalar memory."""
    lamlet = await setup_lamlet(clock, params)

    rnd = Random(seed)
    element_bytes = data_ew // 8
    page_bytes = params.page_bytes

    src_base = get_base_addr(data_ew)
    dst_base = get_base_addr(data_ew) + 0x10000
    max_region_bytes = page_bytes * 4

    indices = generate_random_indices(rnd, vl, data_ew, index_ew, max_region_bytes)

    logger.info(f"Ordered Scalar Load Test: data_ew={data_ew}, index_ew={index_ew}, vl={vl}")
    logger.info(f"  indices: {indices[:16]}{'...' if len(indices) > 16 else ''}")

    # Allocate source memory as SCALAR
    n_src_pages = (max_region_bytes + page_bytes - 1) // page_bytes
    allocate_scalar_pages(lamlet, src_base, n_src_pages, page_bytes)

    # Allocate destination memory as VPU
    dst_size = vl * element_bytes + 64
    n_dst_pages = (max(1024, dst_size) + page_bytes - 1) // page_bytes
    allocate_vpu_pages(lamlet, dst_base, n_dst_pages, page_bytes, data_ew)

    # Write random data at each unique index location in scalar memory
    index_to_value = {}
    for offset in set(indices):
        val = rnd.getrandbits(data_ew)
        index_to_value[offset] = val
        global_addr = src_base + offset
        g_addr = GlobalAddress(bit_addr=global_addr * 8, params=params)
        local_addr = lamlet.to_scalar_addr(g_addr)
        val_bytes = val.to_bytes(element_bytes, byteorder='little')
        for i, b in enumerate(val_bytes):
            lamlet.scalar.set_memory(local_addr + i, b)

    src_list = [index_to_value[idx] for idx in indices]

    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[data_ew]

    elements_per_vline = lamlet.params.vline_bytes * 8 // data_ew
    n_data_regs = (vl + elements_per_vline - 1) // elements_per_vline
    index_elements_per_vline = lamlet.params.vline_bytes * 8 // index_ew
    n_index_regs = (vl + index_elements_per_vline - 1) // index_elements_per_vline

    data_reg = 0
    index_reg = n_data_regs

    await setup_index_register(lamlet, index_reg, indices, index_ew, page_bytes, src_base)

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_ordered_scalar_load")

    # Ordered indexed load from scalar memory
    await lamlet.vload_indexed_ordered(
        vd=data_reg,
        base_addr=src_base,
        index_reg=index_reg,
        index_ew=index_ew,
        data_ew=data_ew,
        n_elements=vl,
        mask_reg=None,
        start_index=0,
        parent_span_id=span_id,
    )

    # Store contiguously to verify
    dst_ordering = Ordering(WordOrder.STANDARD, data_ew)
    await lamlet.vstore(
        vs=data_reg,
        addr=dst_base,
        ordering=dst_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=None,
        parent_span_id=span_id,
    )

    lamlet.monitor.finalize_children(span_id)

    # Read back results
    result_list = []
    for i in range(vl):
        addr = dst_base + i * element_bytes
        data = await lamlet.get_memory_blocking(addr, element_bytes)
        val = int.from_bytes(data, byteorder='little')
        result_list.append(val)

    # Verify values
    errors = 0
    for i in range(vl):
        expected = src_list[i]
        actual = result_list[i]
        if actual != expected:
            logger.error(f"Element {i}: expected {expected:#x}, got {actual:#x}")
            errors += 1

    # Verify access order - reads should happen in element order
    # Build expected access addresses in element order
    expected_access_order = []
    for i in range(vl):
        global_addr = src_base + indices[i]
        g_addr = GlobalAddress(bit_addr=global_addr * 8, params=params)
        local_addr = lamlet.to_scalar_addr(g_addr)
        expected_access_order.append(local_addr)

    actual_access_order = lamlet.scalar.access_log

    if actual_access_order != expected_access_order:
        logger.error(f"Access order mismatch!")
        logger.error(f"  Expected: {expected_access_order[:16]}...")
        logger.error(f"  Actual:   {actual_access_order[:16]}...")
        errors += 1
    else:   
        logger.info(f"Access order verified: {len(actual_access_order)} accesses in correct order")

    if errors > 0:
        logger.error(f"FAILED with {errors} errors")
        lamlet.monitor.print_summary()
        # Dump full span trees to file for debugging (exclude SETUP spans)
        with open('span_trees.txt', 'w') as f:
            for span in lamlet.monitor.spans.values():
                if span.parent is None and span.span_type != SpanType.SETUP:
                    f.write(lamlet.monitor.format_span_tree(span.span_id, max_depth=20))
                    f.write('\n\n')
        logger.info("Span trees written to span_trees.txt")
        return 1
    else:
        logger.info("PASSED")
        return 0


async def main(clock, data_ew: int, index_ew: int, vl: int, params: LamletParams, seed: int):
    """Main wrapper that sets up clock properly."""
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)

    clock.register_main()
    clock.create_task(clock.clock_driver())

    exit_code = await run_ordered_scalar_load_test(clock, data_ew, index_ew, vl, params, seed)

    clock.running = False
    return exit_code


def run_test(data_ew: int, index_ew: int, vl: int, params: LamletParams = None, seed: int = 0):
    """Helper to run a single test configuration."""
    if params is None:
        params = LamletParams()
    clock = Clock(max_cycles=10000)
    exit_code = asyncio.run(main(clock, data_ew, index_ew, vl, params, seed))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def random_test_config(rnd: Random):
    """Generate a random test configuration."""
    geom_name = rnd.choice(list(GEOMETRIES.keys()))
    geom_params = GEOMETRIES[geom_name]
    data_ew = rnd.choice([8, 16, 32, 64])
    index_ew = rnd.choice([8, 16, 32, 64])
    vl = rnd.randint(1, 32)
    return geom_name, geom_params, data_ew, index_ew, vl


def generate_test_params(n_tests: int = 8, seed: int = 42):
    """Generate random test parameter combinations."""
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name, geom_params, data_ew, index_ew, vl = random_test_config(rnd)
        id_str = f"{i}_{geom_name}_dew{data_ew}_iew{index_ew}_vl{vl}"
        test_params.append(pytest.param(geom_params, data_ew, index_ew, vl, id=id_str))
    return test_params


@pytest.mark.parametrize("params,data_ew,index_ew,vl", generate_test_params(n_tests=scale_n_tests(8)))
def test_ordered_scalar_load(params, data_ew, index_ew, vl):
    run_test(data_ew, index_ew, vl, params=params)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test ordered indexed load from scalar memory')
    parser.add_argument('--data-ew', type=int, default=64,
                        help='Data element width in bits (default: 64)')
    parser.add_argument('--index-ew', type=int, default=32,
                        help='Index element width in bits (default: 32)')
    parser.add_argument('--vl', type=int, default=8,
                        help='Vector length (default: 8)')
    parser.add_argument('--geometry', '-g', default='k2x1_j1x1',
                        help='Geometry name (default: k2x1_j1x1)')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries and exit')
    parser.add_argument('--seed', '-s', type=int, default=0,
                        help='Random seed (default: 0)')
    parser.add_argument('--max-cycles', type=int, default=10000,
                        help='Maximum simulation cycles (default: 10000)')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    params = get_geometry(args.geometry)

    level = logging.DEBUG
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    clock = Clock(max_cycles=args.max_cycles)
    try:
        logger.info(f'Starting with data_ew={args.data_ew}, index_ew={args.index_ew}, '
                    f'vl={args.vl}, geometry={args.geometry}, seed={args.seed}')
        exit_code = asyncio.run(main(
            clock, args.data_ew, args.index_ew, args.vl, params, args.seed))
    except KeyboardInterrupt:
        root_logger.warning('Test interrupted by user')
        sys.exit(1)
    except Exception as e:
        root_logger.error(f'Test FAILED with exception: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)

    if exit_code == 0:
        root_logger.warning('========== TEST PASSED ==========')
    else:
        root_logger.warning(f'========== TEST FAILED (exit code: {exit_code}) ==========')
    sys.exit(exit_code)
