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
    j_rows: int,
    seed: int,
):
    """
    Test strided vector load/store operations.

    Creates source data with elements at strided locations:
      src[0], src[stride], src[2*stride], ...

    Loads into register (contiguous), then stores back with stride.
    """
    params = LamletParams(j_rows=j_rows)
    lamlet = Lamlet(clock, params)
    clock.create_task(update(clock, lamlet))
    clock.create_task(lamlet.run())

    await clock.next_cycle

    # Generate test data
    rnd = Random(seed)
    element_bytes = ew // 8
    src_list = [rnd.getrandbits(ew) for i in range(vl)]

    logger.info(f"Test parameters:")
    logger.info(f"  ew={ew}, vl={vl}, stride={stride}")
    logger.info(f"  element_bytes={element_bytes}")
    logger.info(f"  j_rows={j_rows}, seed={seed}")
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

    # Allocate memory regions
    ordering = Ordering(WordOrder.STANDARD, ew)
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=get_vpu_base_addr(ew) * 8, params=params),
        alloc_size, is_vpu=True, ordering=ordering
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=(get_vpu_base_addr(ew) + 0x10000) * 8, params=params),
        alloc_size, is_vpu=True, ordering=ordering
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
    logger.info(f"Loading {vl} elements with stride={stride} into v0")
    await lamlet.vload(
        vd=0,
        addr=src_base,
        ordering=ordering,
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
        ordering=ordering,
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
    j_rows: int,
    seed: int,
):
    """
    Test strided vector store operations.

    1. Write source data contiguously in memory
    2. Load contiguously into register
    3. Store from register with stride
    4. Read back at strided locations and verify
    """
    params = LamletParams(j_rows=j_rows)
    lamlet = Lamlet(clock, params)
    clock.create_task(update(clock, lamlet))
    clock.create_task(lamlet.run())

    await clock.next_cycle

    # Generate test data
    rnd = Random(seed)
    element_bytes = ew // 8
    src_list = [rnd.getrandbits(ew) for i in range(vl)]
    #src_list = [i for i in range(vl)]

    logger.info(f"Strided Store Test parameters:")
    logger.info(f"  ew={ew}, vl={vl}, stride={stride}")
    logger.info(f"  element_bytes={element_bytes}")
    logger.info(f"  j_rows={j_rows}, seed={seed}")
    logger.info(f"src_list: {src_list[:16]}{'...' if len(src_list) > 16 else ''}")

    # Source is contiguous, destination is strided
    src_base = get_vpu_base_addr(ew)
    dst_base = get_vpu_base_addr(ew) + 0x10000

    # Calculate memory size needed for strided destination
    mem_size = (vl - 1) * stride + element_bytes + 64
    alloc_size = max(1024, mem_size)

    # Allocate memory regions
    ordering = Ordering(WordOrder.STANDARD, ew)
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=get_vpu_base_addr(ew) * 8, params=params),
        alloc_size, is_vpu=True, ordering=ordering
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=(get_vpu_base_addr(ew) + 0x10000) * 8, params=params),
        alloc_size, is_vpu=True, ordering=ordering
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

    # Load contiguously into v0
    logger.info(f"Loading {vl} elements contiguously into v0")
    await lamlet.vload(
        vd=0,
        addr=src_base,
        ordering=ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=None,
    )

    # Store from v0 to destination with stride
    logger.info(f"Storing {vl} elements with stride={stride} to dst")
    await lamlet.vstore(
        vs=0,
        addr=dst_base,
        ordering=ordering,
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
    j_rows: int,
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
        exit_code = await run_strided_store_test(clock, ew, vl, stride, j_rows, seed)
    else:
        exit_code = await run_strided_load_test(clock, ew, vl, stride, j_rows, seed)

    logger.warning(f"Test completed with exit_code: {exit_code}")
    clock.running = False

    return exit_code


def run_test(ew: int, vl: int, stride: int, j_rows: int = 1, seed: int = 0,
             test_store: bool = False):
    """Helper to run a single test configuration."""
    clock = Clock(max_cycles=5000)
    exit_code = asyncio.run(main(clock, ew, vl, stride, j_rows, seed, test_store))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def generate_test_params():
    """Generate test parameter combinations."""
    params = []
    for ew in [8, 16, 32, 64]:
        for vl in [1, 3, 7, 8]:
            for stride in [16, 24, 32]:
                id_str = f"ew{ew}_vl{vl}_stride{stride}"
                params.append(pytest.param(ew, vl, stride, id=id_str))
    return params


@pytest.mark.parametrize("ew,vl,stride", generate_test_params())
def test_strided_load(ew, vl, stride):
    run_test(ew, vl, stride, test_store=False)


@pytest.mark.parametrize("ew,vl,stride", generate_test_params())
def test_strided_store(ew, vl, stride):
    run_test(ew, vl, stride, test_store=True)


if __name__ == '__main__':
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='Test strided vector load/store operations')
    parser.add_argument('--ew', type=int, default=64,
                        help='Element width in bits (8, 16, 32, 64) (default: 64)')
    parser.add_argument('--vl', type=int, default=8,
                        help='Vector length - number of elements (default: 8)')
    parser.add_argument('--stride', type=int, default=16,
                        help='Byte stride between elements (default: 16)')
    parser.add_argument('--j-rows', type=int, default=1,
                        help='Number of jamlet rows per kamlet (default: 1)')
    parser.add_argument('--seed', '-s', type=int, default=0,
                        help='Random seed for test data generation (default: 0)')
    parser.add_argument('--store', action='store_true',
                        help='Test strided store (default: test strided load)')
    args = parser.parse_args()

    # Validate element width
    valid_ews = [8, 16, 32, 64]
    if args.ew not in valid_ews:
        print(f"Error: ew must be one of {valid_ews}", file=sys.stderr)
        sys.exit(1)

    level = logging.DEBUG
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    clock = Clock(max_cycles=5000)
    exit_code = None
    try:
        logger.info(
            f'Starting with ew={args.ew}, vl={args.vl}, stride={args.stride}, '
            f'j_rows={args.j_rows}, seed={args.seed}, store={args.store}'
        )
        exit_code = asyncio.run(main(clock, args.ew, args.vl, args.stride, args.j_rows,
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
