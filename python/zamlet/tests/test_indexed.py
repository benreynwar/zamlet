"""
Direct lamlet-level test for indexed (gather/scatter) vector load/store operations.

This test bypasses instruction decoding and directly calls lamlet.vload_indexed/vstore_indexed
to test gather/scatter memory access:

1. Initialize source memory with elements at random locations specified by index vector
2. Load with index into contiguous register (gather)
3. Store from register with index (scatter)
4. Verify results

Parameters:
- data_ew: Data element width (8, 16, 32, 64)
- index_ew: Index element width (8, 16, 32, 64)
- vl: Vector length (number of elements)
"""

import asyncio
import logging
import struct
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import LamletParams
from zamlet.geometries import GEOMETRIES, scale_n_tests
from zamlet.lamlet.lamlet import Lamlet
from zamlet.addresses import GlobalAddress, Ordering, WordOrder
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests.test_utils import setup_mask_register

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
    await clock.next_cycle
    return lamlet


def allocate_memory_pages(
    lamlet: Lamlet,
    base_addr: int,
    n_pages: int,
    page_bytes: int,
    ew: int,
):
    """Allocate memory pages for indexed access."""
    ordering = Ordering(WordOrder.STANDARD, ew)
    for page_idx in range(n_pages):
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=(base_addr + page_idx * page_bytes) * 8, params=lamlet.params),
            page_bytes,
            is_vpu=True,
            ordering=ordering
        )


async def setup_index_register(
    lamlet: Lamlet,
    index_reg: int,
    indices: list[int],
    index_ew: int,
    page_bytes: int,
    base_addr: int,
) -> None:
    """Write index values to memory and load into a vector register."""
    index_mem_addr = base_addr + 0x40000
    index_ordering = Ordering(WordOrder.STANDARD, index_ew)
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=index_mem_addr * 8, params=lamlet.params),
        page_bytes, is_vpu=True, ordering=index_ordering
    )

    index_bytes = pack_elements(indices, index_ew)
    await lamlet.set_memory(index_mem_addr, index_bytes)
    logger.info(f"Index bytes written to 0x{index_mem_addr:x}: {index_bytes.hex()[:64]}...")

    index_span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="load_index")
    await lamlet.vload(
        vd=index_reg,
        addr=index_mem_addr,
        ordering=index_ordering,
        n_elements=len(indices),
        start_index=0,
        mask_reg=None,
        parent_span_id=index_span_id,
    )
    lamlet.monitor.finalize_children(index_span_id)
    logger.info(f"Index register loaded into v{index_reg}")


def verify_results(
    result_list: list[int],
    src_list: list[int],
    mask_bits: list[bool] | None,
    use_mask: bool,
) -> int:
    """Verify test results against expected values. Returns 0 on success, 1 on failure."""
    errors = []
    for i in range(len(result_list)):
        actual_val = result_list[i]
        if use_mask and mask_bits is not None:
            expected_val = src_list[i] if mask_bits[i] else 0
        else:
            expected_val = src_list[i]

        if actual_val != expected_val:
            mask_str = f" mask={mask_bits[i]}" if use_mask and mask_bits else ""
            errors.append(f"  [{i}] expected={expected_val} actual={actual_val}{mask_str}")

    if not errors:
        logger.warning("TEST PASSED: Results match expected values!")
        return 0
    else:
        logger.error("TEST FAILED: Results do not match expected values")
        for err in errors[:32]:
            logger.error(err)
        if len(errors) > 32:
            logger.error(f"  ... and {len(errors) - 32} more errors")
        return 1


def pack_elements(values: list[int], element_width: int) -> bytes:
    """Pack a list of integer values into bytes based on element width."""
    if element_width == 8:
        return bytes(v & 0xFF for v in values)
    elif element_width == 16:
        return struct.pack(f'<{len(values)}H', *[v & 0xFFFF for v in values])
    elif element_width == 32:
        return struct.pack(f'<{len(values)}I', *[v & 0xFFFFFFFF for v in values])
    elif element_width == 64:
        return struct.pack(f'<{len(values)}Q', *[v & 0xFFFFFFFFFFFFFFFF for v in values])
    else:
        raise ValueError(f"Unsupported element width: {element_width}")


def unpack_elements(data: bytes, element_width: int) -> list[int]:
    """Unpack bytes into a list of integer values based on element width."""
    n_elements = len(data) * 8 // element_width
    if element_width == 8:
        return list(data)
    elif element_width == 16:
        return list(struct.unpack(f'<{n_elements}H', data))
    elif element_width == 32:
        return list(struct.unpack(f'<{n_elements}I', data))
    elif element_width == 64:
        return list(struct.unpack(f'<{n_elements}Q', data))
    else:
        raise ValueError(f"Unsupported element width: {element_width}")


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


def generate_random_indices(
    rnd: Random,
    vl: int,
    data_ew: int,
    index_ew: int,
    max_region_bytes: int,
    unique: bool = False,
) -> list[int]:
    """
    Generate random byte offsets for indexed access.

    Indices must:
    - Fit in index_ew bits
    - Point to valid addresses within max_region_bytes
    - Be aligned to data element size

    Args:
        unique: If True, ensure all indices are unique (required for scatter stores
                to have deterministic results).
    """
    element_bytes = data_ew // 8
    max_index = (1 << index_ew) - 1
    max_offset = min(max_index, max_region_bytes - element_bytes)
    max_offset = (max_offset // element_bytes) * element_bytes
    n_possible = max_offset // element_bytes + 1

    if unique:
        assert vl <= n_possible, \
            f"Cannot generate {vl} unique indices with only {n_possible} possible values"
        slot_indices = rnd.sample(range(n_possible), vl)
        return [i * element_bytes for i in slot_indices]
    else:
        indices = []
        for _ in range(vl):
            offset = rnd.randint(0, max_offset // element_bytes) * element_bytes
            indices.append(offset)
        return indices


async def run_indexed_load_test(
    clock: Clock,
    data_ew: int,
    index_ew: int,
    vl: int,
    params: LamletParams,
    seed: int,
    use_mask: bool = True,
):
    """
    Test indexed (gather) vector load operations.

    Creates source data, generates random indices, loads using gather pattern,
    then stores contiguously to verify.
    """
    lamlet = await setup_lamlet(clock, params)

    if use_mask:
        max_vl = params.j_in_l * params.word_bytes * 8
        assert vl <= max_vl, f"vl={vl} exceeds max {max_vl} for masked operation"

    rnd = Random(seed)
    element_bytes = data_ew // 8
    page_bytes = params.page_bytes

    # Calculate memory layout - need enough space for scattered elements
    src_base = get_base_addr(data_ew)
    dst_base = get_base_addr(data_ew) + 0x10000
    max_region_bytes = page_bytes * 4

    # Generate random indices
    indices = generate_random_indices(rnd, vl, data_ew, index_ew, max_region_bytes)
    mask_bits = [rnd.choice([True, False]) for _ in range(vl)] if use_mask else None

    logger.info(f"Test parameters: data_ew={data_ew}, index_ew={index_ew}, vl={vl}")
    logger.info(f"  use_mask={use_mask}")
    logger.info(f"  indices: {indices[:16]}{'...' if len(indices) > 16 else ''}")
    if mask_bits:
        logger.info(f"  mask_bits: {mask_bits[:16]}{'...' if len(mask_bits) > 16 else ''}")

    # Allocate source memory (for scattered elements)
    n_src_pages = (max_region_bytes + page_bytes - 1) // page_bytes
    allocate_memory_pages(lamlet, src_base, n_src_pages, page_bytes, data_ew)

    # Allocate destination memory (for contiguous store)
    dst_size = vl * element_bytes + 64
    n_dst_pages = (max(1024, dst_size) + page_bytes - 1) // page_bytes
    allocate_memory_pages(lamlet, dst_base, n_dst_pages, page_bytes, data_ew)

    # Write random data at each unique index location
    # Map from index -> value stored at that address
    index_to_value = {}
    for offset in set(indices):
        val = rnd.getrandbits(data_ew)
        index_to_value[offset] = val
        addr = src_base + offset
        await lamlet.set_memory(addr, pack_elements([val], data_ew))

    # Expected values: what each element should load based on its index
    src_list = [index_to_value[idx] for idx in indices]

    # Set up vl and vtype
    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[data_ew]

    # Calculate register allocation
    elements_per_vline = lamlet.params.vline_bytes * 8 // data_ew
    n_data_regs = (vl + elements_per_vline - 1) // elements_per_vline

    index_elements_per_vline = lamlet.params.vline_bytes * 8 // index_ew
    n_index_regs = (vl + index_elements_per_vline - 1) // index_elements_per_vline

    # Register layout: v0-vN = data, then index, then mask
    data_reg = 0
    index_reg = n_data_regs
    mask_reg = None

    assert index_reg + n_index_regs <= lamlet.params.n_vregs, \
        f'index_reg {index_reg} + n_index_regs {n_index_regs} exceeds n_vregs {lamlet.params.n_vregs}'

    # Set up index register
    await setup_index_register(lamlet, index_reg, indices, index_ew, page_bytes, src_base)

    # Set up mask register if using masks
    if use_mask:
        mask_reg = index_reg + n_index_regs
        assert mask_reg < lamlet.params.n_vregs, \
            f'mask_reg {mask_reg} exceeds n_vregs {lamlet.params.n_vregs}'
        mask_mem_addr = src_base + 0x30000
        await setup_mask_register(lamlet, mask_reg, mask_bits, page_bytes, mask_mem_addr)

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_indexed_load")

    # Indexed load (gather) from source into v0
    await lamlet.vload_indexed_unordered(
        vd=data_reg,
        base_addr=src_base,
        index_reg=index_reg,
        index_ew=index_ew,
        data_ew=data_ew,
        n_elements=vl,
        mask_reg=mask_reg,
        start_index=0,
        parent_span_id=span_id,
    )

    # Store from v0 to destination contiguously (unit stride)
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
        future = await lamlet.get_memory(addr, element_bytes)
        await future
        result_list.append(unpack_elements(future.result(), data_ew)[0])

    lamlet.monitor.print_summary()
    return verify_results(result_list, src_list, mask_bits, use_mask)


async def run_indexed_store_test(
    clock: Clock,
    data_ew: int,
    index_ew: int,
    vl: int,
    params: LamletParams,
    seed: int,
    use_mask: bool = True,
):
    """
    Test indexed (scatter) vector store operations.

    1. Write source data contiguously in memory
    2. Load contiguously into register
    3. Store from register with index (scatter, optionally masked)
    4. Read back at indexed locations and verify
    """
    lamlet = await setup_lamlet(clock, params)

    if use_mask:
        max_vl = params.j_in_l * params.word_bytes * 8
        assert vl <= max_vl, f"vl={vl} exceeds max {max_vl} for masked operation"

    rnd = Random(seed)
    element_bytes = data_ew // 8
    page_bytes = params.page_bytes

    # Calculate memory layout
    src_base = get_base_addr(data_ew)
    dst_base = get_base_addr(data_ew) + 0x10000
    max_region_bytes = page_bytes * 4

    # Generate random indices (unique for store to avoid write conflicts) and source values
    indices = generate_random_indices(rnd, vl, data_ew, index_ew, max_region_bytes, unique=True)
    src_list = [rnd.getrandbits(data_ew) for _ in range(vl)]
    mask_bits = [rnd.choice([True, False]) for _ in range(vl)] if use_mask else None

    logger.info(f"Indexed Store Test: data_ew={data_ew}, index_ew={index_ew}, vl={vl}")
    logger.info(f"  use_mask={use_mask}")
    logger.info(f"  indices: {indices[:16]}{'...' if len(indices) > 16 else ''}")
    if mask_bits:
        logger.info(f"  mask_bits: {mask_bits[:16]}{'...' if len(mask_bits) > 16 else ''}")

    # Allocate source memory (for contiguous load)
    src_size = vl * element_bytes + 64
    n_src_pages = (max(1024, src_size) + page_bytes - 1) // page_bytes
    allocate_memory_pages(lamlet, src_base, n_src_pages, page_bytes, data_ew)

    # Allocate destination memory (for scattered store)
    n_dst_pages = (max_region_bytes + page_bytes - 1) // page_bytes
    allocate_memory_pages(lamlet, dst_base, n_dst_pages, page_bytes, data_ew)

    # Initialize destination memory to zeros (so masked elements read back as 0)
    for i, offset in enumerate(indices):
        addr = dst_base + offset
        await lamlet.set_memory(addr, bytes(element_bytes))

    # Write source data contiguously
    for i, val in enumerate(src_list):
        addr = src_base + i * element_bytes
        await lamlet.set_memory(addr, pack_elements([val], data_ew))

    # Set up vl and vtype
    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[data_ew]

    # Calculate register allocation
    elements_per_vline = lamlet.params.vline_bytes * 8 // data_ew
    n_data_regs = (vl + elements_per_vline - 1) // elements_per_vline

    index_elements_per_vline = lamlet.params.vline_bytes * 8 // index_ew
    n_index_regs = (vl + index_elements_per_vline - 1) // index_elements_per_vline

    # Register layout: v0-vN = data, then index, then mask
    data_reg = 0
    index_reg = n_data_regs
    mask_reg = None

    assert index_reg + n_index_regs <= lamlet.params.n_vregs, \
        f'index_reg {index_reg} + n_index_regs {n_index_regs} exceeds n_vregs {lamlet.params.n_vregs}'

    # Set up index register
    await setup_index_register(lamlet, index_reg, indices, index_ew, page_bytes, src_base)

    # Set up mask register if using masks
    if use_mask:
        mask_reg = index_reg + n_index_regs
        assert mask_reg < lamlet.params.n_vregs, \
            f'mask_reg {mask_reg} exceeds n_vregs {lamlet.params.n_vregs}'
        mask_mem_addr = src_base + 0x30000
        await setup_mask_register(lamlet, mask_reg, mask_bits, page_bytes, mask_mem_addr)

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_indexed_store")

    # Load contiguously into v0
    src_ordering = Ordering(WordOrder.STANDARD, data_ew)
    await lamlet.vload(
        vd=data_reg,
        addr=src_base,
        ordering=src_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=None,
        parent_span_id=span_id,
    )

    # Indexed store (scatter) from v0 to destination
    await lamlet.vstore_indexed_unordered(
        vs=data_reg,
        base_addr=dst_base,
        index_reg=index_reg,
        index_ew=index_ew,
        data_ew=data_ew,
        n_elements=vl,
        mask_reg=mask_reg,
        start_index=0,
        parent_span_id=span_id,
    )

    lamlet.monitor.finalize_children(span_id)

    # Read back results at indexed locations
    result_list = []
    for i, offset in enumerate(indices):
        addr = dst_base + offset
        future = await lamlet.get_memory(addr, element_bytes)
        await future
        result_list.append(unpack_elements(future.result(), data_ew)[0])

    lamlet.monitor.print_summary()
    return verify_results(result_list, src_list, mask_bits, use_mask)


async def main(
    clock,
    data_ew: int,
    index_ew: int,
    vl: int,
    params: LamletParams,
    seed: int,
    test_store: bool = False,
    use_mask: bool = True,
):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)

    clock.register_main()

    clock_driver_task = clock.create_task(clock.clock_driver())
    if test_store:
        exit_code = await run_indexed_store_test(
            clock, data_ew, index_ew, vl, params, seed, use_mask)
    else:
        exit_code = await run_indexed_load_test(
            clock, data_ew, index_ew, vl, params, seed, use_mask)

    logger.warning(f"Test completed with exit_code: {exit_code}")
    clock.running = False

    return exit_code


def run_test(data_ew: int, index_ew: int, vl: int, params: LamletParams = None, seed: int = 0,
             test_store: bool = False, use_mask: bool = True):
    """Helper to run a single test configuration."""
    if params is None:
        params = LamletParams()
    clock = Clock(max_cycles=10000)
    exit_code = asyncio.run(main(clock, data_ew, index_ew, vl, params, seed, test_store,
                                  use_mask=use_mask))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def random_test_config(rnd: Random):
    """Generate a random test configuration."""
    geom_name = rnd.choice(list(GEOMETRIES.keys()))
    geom_params = GEOMETRIES[geom_name]
    data_ew = rnd.choice([8, 16, 32, 64])
    index_ew = rnd.choice([8, 16, 32, 64])
    vl = rnd.randint(1, 32)
    return geom_name, geom_params, data_ew, index_ew, vl


def generate_test_params(n_tests: int = 64, seed: int = 42):
    """Generate random test parameter combinations."""
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name, geom_params, data_ew, index_ew, vl = random_test_config(rnd)
        id_str = f"{i}_{geom_name}_dew{data_ew}_iew{index_ew}_vl{vl}"
        test_params.append(pytest.param(geom_params, data_ew, index_ew, vl, id=id_str))
    return test_params


@pytest.mark.parametrize("params,data_ew,index_ew,vl", generate_test_params(n_tests=scale_n_tests(32)))
def test_indexed_load(params, data_ew, index_ew, vl):
    run_test(data_ew, index_ew, vl, params=params, test_store=False)


@pytest.mark.parametrize("params,data_ew,index_ew,vl", generate_test_params(n_tests=scale_n_tests(32)))
def test_indexed_store(params, data_ew, index_ew, vl):
    run_test(data_ew, index_ew, vl, params=params, test_store=True)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test indexed vector load/store operations')
    parser.add_argument('--data-ew', type=int, default=64,
                        help='Data element width in bits (8, 16, 32, 64) (default: 64)')
    parser.add_argument('--index-ew', type=int, default=32,
                        help='Index element width in bits (8, 16, 32, 64) (default: 32)')
    parser.add_argument('--vl', type=int, default=8,
                        help='Vector length - number of elements (default: 8)')
    parser.add_argument('--geometry', '-g', default='k2x1_j1x1',
                        help='Geometry name (default: k2x1_j1x1)')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries and exit')
    parser.add_argument('--seed', '-s', type=int, default=0,
                        help='Random seed for test data generation (default: 0)')
    parser.add_argument('--store', action='store_true',
                        help='Test indexed store (default: test indexed load)')
    parser.add_argument('--max-cycles', type=int, default=10000,
                        help='Maximum simulation cycles (default: 10000)')
    parser.add_argument('--no-mask', action='store_true',
                        help='Disable mask testing (default: use random mask)')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    valid_ews = [8, 16, 32, 64]
    if args.data_ew not in valid_ews:
        print(f"Error: data-ew must be one of {valid_ews}", file=sys.stderr)
        sys.exit(1)
    if args.index_ew not in valid_ews:
        print(f"Error: index-ew must be one of {valid_ews}", file=sys.stderr)
        sys.exit(1)

    params = get_geometry(args.geometry)
    use_mask = not args.no_mask

    level = logging.DEBUG
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    clock = Clock(max_cycles=args.max_cycles)
    exit_code = None
    try:
        logger.info(
            f'Starting with data_ew={args.data_ew}, index_ew={args.index_ew}, vl={args.vl}, '
            f'geometry={args.geometry}, seed={args.seed}, store={args.store}, use_mask={use_mask}'
        )
        exit_code = asyncio.run(main(clock, args.data_ew, args.index_ew, args.vl, params,
                                     args.seed, args.store, use_mask))
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
