"""
Direct lamlet-level test for strided vector load/store operations.

This test bypasses instruction decoding and directly calls lamlet.vload/vstore
with stride_bytes parameter to test strided memory access:

1. Initialize source memory with elements at strided locations
2. Load with stride into contiguous register
3. Store from register back to memory with stride
4. Verify results

Parameters:
- ew: Element width (8, 16, 32, 64)
- vl: Vector length (number of elements)
- stride: Byte stride between elements (can be > ew/8 for sparse, or negative)
- j_rows: Number of jamlet rows per kamlet
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


def allocate_strided_memory(
    lamlet: Lamlet,
    base_addr: int,
    n_pages: int,
    page_bytes: int,
    ews: list[int],
    mem_ew: int | None,
    is_vpu: bool = True,
    use_scalar: bool = False,
):
    """
    Allocate memory pages for strided access.

    Args:
        use_scalar: If True, alternate between VPU and scalar pages
    """
    for page_idx in range(n_pages):
        if mem_ew is not None:
            page_ew = mem_ew
        else:
            page_ew = ews[page_idx % len(ews)]
        ordering = Ordering(WordOrder.STANDARD, page_ew)

        page_is_vpu = is_vpu and (not use_scalar or (page_idx % 2 == 0))
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=(base_addr + page_idx * page_bytes) * 8, params=lamlet.params),
            page_bytes,
            is_vpu=page_is_vpu,
            ordering=ordering if page_is_vpu else None
        )


def verify_results(
    result_list: list[int],
    src_list: list[int],
    mask_bits: list[bool] | None,
    use_mask: bool,
) -> int:
    """
    Verify test results against expected values.

    Returns 0 on success, 1 on failure.
    """
    errors = []
    for i in range(len(result_list)):
        actual_val = result_list[i]
        if use_mask and mask_bits is not None:
            if mask_bits[i]:
                expected_val = src_list[i]
            else:
                expected_val = 0
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


def get_vpu_base_addr(element_width: int) -> int:
    """Get the VPU memory base address for a given element width."""
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


async def run_strided_load_test(
    clock: Clock,
    ew: int,
    vl: int,
    stride: int,
    params: LamletParams,
    seed: int,
    mem_ew: int | None = None,
    use_mask: bool = True,
    use_scalar: bool = True,
):
    """
    Test strided vector load operations.

    Creates source data with elements at strided locations, loads into register
    with stride, then stores contiguously to verify.

    Args:
        use_mask: If True, use a random mask pattern
        use_scalar: If True, mix scalar and VPU pages for source memory
    """
    lamlet = await setup_lamlet(clock, params)

    # When using masks, vl is limited by mask register size (j_in_l * word_bits)
    if use_mask:
        max_vl = params.j_in_l * params.word_bytes * 8
        assert vl <= max_vl, f"vl={vl} exceeds max {max_vl} for masked operation"

    # Generate test data
    rnd = Random(seed)
    element_bytes = ew // 8
    src_list = [rnd.getrandbits(ew) for i in range(vl)]
    mask_bits = [rnd.choice([True, False]) for i in range(vl)] if use_mask else None

    logger.info(f"Test parameters: ew={ew}, vl={vl}, stride={stride}")
    logger.info(f"  use_mask={use_mask}, use_scalar={use_scalar}")
    if mask_bits:
        logger.info(f"  mask_bits: {mask_bits[:16]}{'...' if len(mask_bits) > 16 else ''}")

    # Calculate memory layout
    src_base = get_vpu_base_addr(ew)
    dst_base = get_vpu_base_addr(ew) + 0x10000
    mem_size = (vl - 1) * stride + element_bytes + 64
    page_bytes = params.page_bytes
    alloc_size = ((max(1024, mem_size) + page_bytes - 1) // page_bytes) * page_bytes
    n_pages = alloc_size // page_bytes

    # Allocate source memory (mixed VPU/scalar if use_scalar)
    ews = [8, 16, 32, 64]
    allocate_strided_memory(lamlet, get_vpu_base_addr(ew), n_pages, page_bytes,
                            ews, mem_ew, use_scalar=use_scalar)
    # Allocate destination memory (always VPU)
    allocate_strided_memory(lamlet, get_vpu_base_addr(ew) + 0x10000, n_pages,
                            page_bytes, [ew], ew)

    # Write source data at strided locations
    for i, val in enumerate(src_list):
        addr = src_base + i * stride
        await lamlet.set_memory(addr, pack_elements([val], ew))

    # Set up vl and vtype
    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[ew]

    # Set up mask register if using masks
    # Calculate how many registers the data uses and put mask after that
    elements_per_vline = lamlet.params.vline_bytes * 8 // ew
    n_data_regs = (vl + elements_per_vline - 1) // elements_per_vline
    assert n_data_regs <= lamlet.params.n_vregs, \
        f'n_data_regs {n_data_regs} exceeds n_vregs {lamlet.params.n_vregs}'
    mask_reg = None
    if use_mask:
        mask_reg = n_data_regs  # First register after data
        assert mask_reg < lamlet.params.n_vregs, \
            f'mask_reg {mask_reg} exceeds n_vregs {lamlet.params.n_vregs}'
        mask_mem_addr = get_vpu_base_addr(64) + 0x30000
        await setup_mask_register(lamlet, mask_reg, mask_bits, page_bytes, mask_mem_addr)

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_strided_load")

    # Load from source with stride into v0
    reg_ordering = Ordering(WordOrder.STANDARD, ew)
    await lamlet.vload(
        vd=0,
        addr=src_base,
        ordering=reg_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=mask_reg,
        parent_span_id=span_id,
        stride_bytes=stride,
    )

    # Store from v0 to destination contiguously (unit stride)
    dst_ordering = Ordering(WordOrder.STANDARD, ew)
    await lamlet.vstore(
        vs=0,
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
        result_list.append(unpack_elements(future.result(), ew)[0])

    lamlet.monitor.print_summary()
    return verify_results(result_list, src_list, mask_bits, use_mask)


async def run_strided_store_test(
    clock: Clock,
    ew: int,
    vl: int,
    stride: int,
    params: LamletParams,
    seed: int,
    mem_ew: int | None = None,
    use_mask: bool = True,
    use_scalar: bool = True,
):
    """
    Test strided vector store operations.

    1. Write source data contiguously in memory
    2. Load contiguously into register
    3. Store from register with stride (optionally masked)
    4. Read back at strided locations and verify

    Args:
        use_mask: If True, use a random mask pattern
        use_scalar: If True, mix scalar and VPU pages for destination memory
    """
    lamlet = await setup_lamlet(clock, params)

    # When using masks, vl is limited by mask register size (j_in_l * word_bits)
    if use_mask:
        max_vl = params.j_in_l * params.word_bytes * 8
        assert vl <= max_vl, f"vl={vl} exceeds max {max_vl} for masked operation"

    # Generate test data
    rnd = Random(seed)
    element_bytes = ew // 8
    src_list = [rnd.getrandbits(ew) for i in range(vl)]
    mask_bits = [rnd.choice([True, False]) for i in range(vl)] if use_mask else None

    logger.info(f"Strided Store Test: ew={ew}, vl={vl}, stride={stride}")
    logger.info(f"  use_mask={use_mask}, use_scalar={use_scalar}")
    if mask_bits:
        logger.info(f"  mask_bits: {mask_bits[:16]}{'...' if len(mask_bits) > 16 else ''}")

    # Calculate memory layout
    src_base = get_vpu_base_addr(ew)
    dst_base = get_vpu_base_addr(ew) + 0x10000
    mem_size = (vl - 1) * stride + element_bytes + 64
    page_bytes = params.page_bytes
    alloc_size = ((max(1024, mem_size) + page_bytes - 1) // page_bytes) * page_bytes
    n_pages = alloc_size // page_bytes

    # Allocate source memory (always VPU, uniform ew)
    allocate_strided_memory(lamlet, get_vpu_base_addr(ew), n_pages, page_bytes, [ew], ew)
    # Allocate destination memory (mixed VPU/scalar if use_scalar)
    ews = [8, 16, 32, 64]
    allocate_strided_memory(lamlet, get_vpu_base_addr(ew) + 0x10000, n_pages,
                            page_bytes, ews, mem_ew, use_scalar=use_scalar)

    # Initialize destination memory to zeros (so masked elements read back as 0)
    for i in range(vl):
        addr = dst_base + i * stride
        await lamlet.set_memory(addr, bytes(element_bytes))

    # Write source data contiguously
    for i, val in enumerate(src_list):
        addr = src_base + i * element_bytes
        await lamlet.set_memory(addr, pack_elements([val], ew))

    # Set up vl and vtype
    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[ew]

    # Set up mask register if using masks
    # Calculate how many registers the data uses and put mask after that
    elements_per_vline = lamlet.params.vline_bytes * 8 // ew
    n_data_regs = (vl + elements_per_vline - 1) // elements_per_vline
    assert n_data_regs <= lamlet.params.n_vregs, \
        f'n_data_regs {n_data_regs} exceeds n_vregs {lamlet.params.n_vregs}'
    mask_reg = None
    if use_mask:
        mask_reg = n_data_regs  # First register after data
        assert mask_reg < lamlet.params.n_vregs, \
            f'mask_reg {mask_reg} exceeds n_vregs {lamlet.params.n_vregs}'
        mask_mem_addr = get_vpu_base_addr(64) + 0x30000
        await setup_mask_register(lamlet, mask_reg, mask_bits, page_bytes, mask_mem_addr)

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_strided_store")

    # Load contiguously into v0
    src_ordering = Ordering(WordOrder.STANDARD, ew)
    await lamlet.vload(
        vd=0,
        addr=src_base,
        ordering=src_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=None,
        parent_span_id=span_id,
    )

    # Store from v0 to destination with stride
    reg_ordering = Ordering(WordOrder.STANDARD, ew)
    await lamlet.vstore(
        vs=0,
        addr=dst_base,
        ordering=reg_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=mask_reg,
        parent_span_id=span_id,
        stride_bytes=stride,
    )

    lamlet.monitor.finalize_children(span_id)

    # Read back results at strided locations
    result_list = []
    for i in range(vl):
        addr = dst_base + i * stride
        future = await lamlet.get_memory(addr, element_bytes)
        await future
        result_list.append(unpack_elements(future.result(), ew)[0])

    lamlet.monitor.print_summary()

    # For strided store with mask, unmasked elements should be 0 (not written)
    return verify_results(result_list, src_list, mask_bits, use_mask)


async def main(
    clock,
    ew: int,
    vl: int,
    stride: int,
    params: LamletParams,
    seed: int,
    test_store: bool = False,
    mem_ew: int | None = None,
    use_mask: bool = True,
    use_scalar: bool = True,
):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)

    clock.register_main()

    clock_driver_task = clock.create_task(clock.clock_driver())
    if test_store:
        exit_code = await run_strided_store_test(
            clock, ew, vl, stride, params, seed, mem_ew, use_mask, use_scalar)
    else:
        exit_code = await run_strided_load_test(
            clock, ew, vl, stride, params, seed, mem_ew, use_mask, use_scalar)

    logger.warning(f"Test completed with exit_code: {exit_code}")
    clock.running = False

    return exit_code


def run_test(ew: int, vl: int, stride: int, params: LamletParams = None, seed: int = 0,
             test_store: bool = False, use_mask: bool = True, use_scalar: bool = True):
    """Helper to run a single test configuration."""
    if params is None:
        params = LamletParams()
    clock = Clock(max_cycles=10000)
    exit_code = asyncio.run(main(clock, ew, vl, stride, params, seed, test_store,
                                  use_mask=use_mask, use_scalar=use_scalar))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def random_test_config(rnd: Random):
    """Generate a random test configuration."""
    geom_name = rnd.choice(list(GEOMETRIES.keys()))
    geom_params = GEOMETRIES[geom_name]
    ew = rnd.choice([8, 16, 32, 64])
    vl = rnd.randint(1, 64)
    element_bytes = ew // 8
    # Stride must be at least element size to avoid overlapping elements
    stride = rnd.randint(element_bytes, 64)
    return geom_name, geom_params, ew, vl, stride


def generate_test_params(n_tests: int = 64, seed: int = 42):
    """Generate random test parameter combinations."""
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name, geom_params, ew, vl, stride = random_test_config(rnd)
        id_str = f"{i}_{geom_name}_ew{ew}_vl{vl}_stride{stride}"
        test_params.append(pytest.param(geom_params, ew, vl, stride, id=id_str))
    return test_params


@pytest.mark.parametrize("params,ew,vl,stride", generate_test_params(n_tests=scale_n_tests(32)))
def test_strided_load(params, ew, vl, stride):
    run_test(ew, vl, stride, params=params, test_store=False)


@pytest.mark.parametrize("params,ew,vl,stride", generate_test_params(n_tests=scale_n_tests(32)))
def test_strided_store(params, ew, vl, stride):
    run_test(ew, vl, stride, params=params, test_store=True)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test strided vector load/store operations')
    parser.add_argument('--ew', type=int, default=64,
                        help='Element width in bits (8, 16, 32, 64) (default: 64)')
    parser.add_argument('--vl', type=int, default=8,
                        help='Vector length - number of elements (default: 8)')
    parser.add_argument('--stride', type=int, default=16,
                        help='Byte stride between elements (default: 16)')
    parser.add_argument('--geometry', '-g', default='k2x1_j1x1',
                        help='Geometry name (default: k2x1_j1x1)')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries and exit')
    parser.add_argument('--seed', '-s', type=int, default=0,
                        help='Random seed for test data generation (default: 0)')
    parser.add_argument('--store', action='store_true',
                        help='Test strided store (default: test strided load)')
    parser.add_argument('--mem-ew', type=int, default=None,
                        help='Memory element width. If set, all pages use this ew. '
                             'If not set, pages cycle through [8, 16, 32, 64].')
    parser.add_argument('--max-cycles', type=int, default=10000,
                        help='Maximum simulation cycles (default: 10000)')
    parser.add_argument('--no-mask', action='store_true',
                        help='Disable mask testing (default: use random mask)')
    parser.add_argument('--no-scalar', action='store_true',
                        help='Disable scalar memory pages (default: mix VPU/scalar)')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    # Validate element width
    valid_ews = [8, 16, 32, 64]
    if args.ew not in valid_ews:
        print(f"Error: ew must be one of {valid_ews}", file=sys.stderr)
        sys.exit(1)

    params = get_geometry(args.geometry)
    use_mask = not args.no_mask
    use_scalar = not args.no_scalar

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
            f'Starting with ew={args.ew}, vl={args.vl}, stride={args.stride}, '
            f'geometry={args.geometry}, seed={args.seed}, store={args.store}, '
            f'mem_ew={args.mem_ew}, use_mask={use_mask}, use_scalar={use_scalar}'
        )
        exit_code = asyncio.run(main(clock, args.ew, args.vl, args.stride, params,
                                     args.seed, args.store, args.mem_ew,
                                     use_mask, use_scalar))
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
