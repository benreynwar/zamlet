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

logger = logging.getLogger(__name__)


async def update(clock, lamlet):
    """Update loop for the lamlet"""
    while True:
        await clock.next_update
        lamlet.update()


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
):
    """
    Test strided vector load/store operations.

    Creates source data with elements at strided locations:
      src[0], src[stride], src[2*stride], ...

    Loads into register (contiguous), then stores back with stride.
    """
    lamlet = Lamlet(clock, params)
    clock.create_task(update(clock, lamlet))
    clock.create_task(lamlet.run())

    await clock.next_cycle

    # Generate test data
    rnd = Random(seed)
    element_bytes = ew // 8
    #src_list = [rnd.getrandbits(ew) for i in range(vl)]
    src_list = [i%256 for i in range(vl)]

    logger.info(f"Test parameters:")
    logger.info(f"  ew={ew}, vl={vl}, stride={stride}")
    logger.info(f"  element_bytes={element_bytes}")
    logger.info(f"  params={params}, seed={seed}")
    logger.info(f"src_list: {src_list[:16]}{'...' if len(src_list) > 16 else ''}")

    # Memory layout for strided access:
    # Element i is at offset i * stride from base
    # Total memory needed: (vl - 1) * stride + element_bytes
    src_base = get_vpu_base_addr(ew)
    dst_base = get_vpu_base_addr(ew) + 0x10000  # Offset to avoid overlap

    # Calculate memory size needed
    if stride >= 0:
        mem_size = (vl - 1) * stride + element_bytes + 64  # Extra padding
    else:
        # Negative stride: first element is at highest address
        mem_size = (vl - 1) * abs(stride) + element_bytes + 64
        # Adjust base to account for negative stride
        src_base += (vl - 1) * abs(stride)
        dst_base += (vl - 1) * abs(stride)

    alloc_size = max(1024, mem_size)
    # Round up to page boundary
    page_bytes = params.page_bytes
    alloc_size = ((alloc_size + page_bytes - 1) // page_bytes) * page_bytes
    n_pages = alloc_size // page_bytes

    # Allocate source with varying ew per page (tests strided load across orderings)
    # Allocate dest with uniform ew (contiguous store requires uniform ordering)
    ews = [8, 16, 32, 64]
    src_alloc_base = get_vpu_base_addr(ew)
    dst_alloc_base = get_vpu_base_addr(ew) + 0x10000
    dst_ordering = Ordering(WordOrder.STANDARD, ew)
    for page_idx in range(n_pages):
        src_page_ew = ews[page_idx % len(ews)]
        src_ordering = Ordering(WordOrder.STANDARD, src_page_ew)
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=(src_alloc_base + page_idx * page_bytes) * 8, params=params),
            page_bytes, is_vpu=True, ordering=src_ordering
        )
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=(dst_alloc_base + page_idx * page_bytes) * 8, params=params),
            page_bytes, is_vpu=True, ordering=dst_ordering
        )

    # Write source data at strided locations
    logger.info(f"Writing source data at strided locations (stride={stride})")
    for i, val in enumerate(src_list):
        addr = src_base + i * stride
        data = pack_elements([val], ew)
        await lamlet.set_memory(addr, data)
        if i < 8 or i == vl - 1:
            logger.info(f"  src[{i}] at 0x{addr:x} = {val}")
        elif i == 8:
            logger.info(f"  ...")

    logger.info(f"Memory initialized at src_base=0x{src_base:x}, dst_base=0x{dst_base:x}")

    # Set up vl and vtype
    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[ew]

    # Load from source with stride into v0 (contiguous in register)
    # ordering parameter specifies element width for register layout
    reg_ordering = Ordering(WordOrder.STANDARD, ew)
    logger.info(f"Loading {vl} elements with stride={stride} into v0")
    await lamlet.vload(
        vd=0,
        addr=src_base,
        ordering=reg_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=None,
        stride_bytes=stride,
    )

    # Store from v0 to destination contiguously (unit stride)
    logger.info(f"Storing {vl} elements contiguously to dst")
    await lamlet.vstore(
        vs=0,
        addr=dst_base,
        ordering=dst_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=None,
    )

    logger.info("Load and store completed")

    # Read back results contiguously and verify
    logger.info("Reading results from memory")
    result_list = []
    for i in range(vl):
        addr = dst_base + i * element_bytes
        future = await lamlet.get_memory(addr, element_bytes)
        await future
        data = future.result()
        val = unpack_elements(data, ew)[0]
        result_list.append(val)
        if i < 8 or i == vl - 1:
            logger.info(f"  dst[{i}] at 0x{addr:x} = {val}")
        elif i == 8:
            logger.info(f"  ...")

    # Compare
    if result_list == src_list:
        logger.warning("TEST PASSED: Results match expected values!")
        return 0
    else:
        logger.error("TEST FAILED: Results do not match expected values")
        for i in range(min(vl, 32)):
            actual_val = result_list[i]
            expected_val = src_list[i]
            match = "✓" if actual_val == expected_val else "✗"
            logger.error(f"  [{i}] expected={expected_val} actual={actual_val} {match}")
        if vl > 32:
            logger.error(f"  ... and {vl - 32} more elements")
        return 1


async def run_strided_store_test(
    clock: Clock,
    ew: int,
    vl: int,
    stride: int,
    params: LamletParams,
    seed: int,
):
    """
    Test strided vector store operations.

    1. Write source data contiguously in memory
    2. Load contiguously into register
    3. Store from register with stride
    4. Read back at strided locations and verify
    """
    lamlet = Lamlet(clock, params)
    clock.create_task(update(clock, lamlet))
    clock.create_task(lamlet.run())

    await clock.next_cycle

    # Generate test data
    rnd = Random(seed)
    element_bytes = ew // 8
    src_list = [rnd.getrandbits(ew) for i in range(vl)]
    src_list = [i%258 for i in range(vl)]

    logger.info(f"Strided Store Test parameters:")
    logger.info(f"  ew={ew}, vl={vl}, stride={stride}")
    logger.info(f"  element_bytes={element_bytes}")
    logger.info(f"  params={params}, seed={seed}")
    logger.info(f"src_list: {src_list[:16]}{'...' if len(src_list) > 16 else ''}")

    # Source is contiguous, destination is strided
    src_base = get_vpu_base_addr(ew)
    dst_base = get_vpu_base_addr(ew) + 0x10000

    # Calculate memory size needed for strided destination
    mem_size = (vl - 1) * stride + element_bytes + 64
    alloc_size = max(1024, mem_size)
    # Round up to page boundary
    page_bytes = params.page_bytes
    alloc_size = ((alloc_size + page_bytes - 1) // page_bytes) * page_bytes
    n_pages = alloc_size // page_bytes

    # Allocate source with uniform ew (contiguous load requires uniform ordering)
    # Allocate dest with varying ew per page (tests strided store across orderings)
    ews = [8, 16, 32, 64]
    src_alloc_base = get_vpu_base_addr(ew)
    dst_alloc_base = get_vpu_base_addr(ew) + 0x10000
    src_ordering = Ordering(WordOrder.STANDARD, ew)
    for page_idx in range(n_pages):
        dst_page_ew = ews[page_idx % len(ews)]
        dst_ordering = Ordering(WordOrder.STANDARD, dst_page_ew)
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=(src_alloc_base + page_idx * page_bytes) * 8, params=params),
            page_bytes, is_vpu=True, ordering=src_ordering
        )
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=(dst_alloc_base + page_idx * page_bytes) * 8, params=params),
            page_bytes, is_vpu=True, ordering=dst_ordering
        )

    # Write source data contiguously
    logger.info(f"Writing source data contiguously")
    for i, val in enumerate(src_list):
        addr = src_base + i * element_bytes
        data = pack_elements([val], ew)
        await lamlet.set_memory(addr, data)
        if i < 8 or i == vl - 1:
            logger.info(f"  src[{i}] at 0x{addr:x} = {val}")
        elif i == 8:
            logger.info(f"  ...")

    logger.info(f"Memory initialized at src_base=0x{src_base:x}, dst_base=0x{dst_base:x}")

    # Set up vl and vtype
    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[ew]

    # Load contiguously into v0 (src has uniform ordering)
    logger.info(f"Loading {vl} elements contiguously into v0")
    await lamlet.vload(
        vd=0,
        addr=src_base,
        ordering=src_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=None,
    )

    # Store from v0 to destination with stride
    # For strided store, ordering sets reg_ordering (memory ordering looked up from TLB)
    reg_ordering = Ordering(WordOrder.STANDARD, ew)
    logger.info(f"Storing {vl} elements with stride={stride} to dst")
    await lamlet.vstore(
        vs=0,
        addr=dst_base,
        ordering=reg_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=None,
        stride_bytes=stride,
    )

    logger.info("Load and store completed")

    # Read back results at strided locations and verify
    logger.info("Reading results from strided memory locations")
    result_list = []
    for i in range(vl):
        addr = dst_base + i * stride
        future = await lamlet.get_memory(addr, element_bytes)
        await future
        data = future.result()
        val = unpack_elements(data, ew)[0]
        result_list.append(val)
        if i < 8 or i == vl - 1:
            logger.info(f"  dst[{i}] at 0x{addr:x} = {val}")
        elif i == 8:
            logger.info(f"  ...")

    # Compare
    if result_list == src_list:
        logger.warning("TEST PASSED: Results match expected values!")
        return 0
    else:
        logger.error("TEST FAILED: Results do not match expected values")
        for i in range(min(vl, 32)):
            actual_val = result_list[i]
            expected_val = src_list[i]
            match = "✓" if actual_val == expected_val else "✗"
            logger.error(f"  [{i}] expected={expected_val} actual={actual_val} {match}")
        if vl > 32:
            logger.error(f"  ... and {vl - 32} more elements")
        return 1


async def main(
    clock,
    ew: int,
    vl: int,
    stride: int,
    params: LamletParams,
    seed: int,
    test_store: bool = False,
):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)

    clock.register_main()

    clock_driver_task = clock.create_task(clock.clock_driver())
    if test_store:
        exit_code = await run_strided_store_test(clock, ew, vl, stride, params, seed)
    else:
        exit_code = await run_strided_load_test(clock, ew, vl, stride, params, seed)

    logger.warning(f"Test completed with exit_code: {exit_code}")
    clock.running = False

    return exit_code


def run_test(ew: int, vl: int, stride: int, params: LamletParams = None, seed: int = 0,
             test_store: bool = False):
    """Helper to run a single test configuration."""
    if params is None:
        params = LamletParams()
    clock = Clock(max_cycles=10000)
    exit_code = asyncio.run(main(clock, ew, vl, stride, params, seed, test_store))
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

    level = logging.DEBUG
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    clock = Clock(max_cycles=10000)
    exit_code = None
    try:
        logger.info(
            f'Starting with ew={args.ew}, vl={args.vl}, stride={args.stride}, '
            f'geometry={args.geometry}, seed={args.seed}, store={args.store}'
        )
        exit_code = asyncio.run(main(clock, args.ew, args.vl, args.stride, params,
                                     args.seed, args.store))
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
