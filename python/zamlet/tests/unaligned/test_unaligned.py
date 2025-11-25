"""
Direct kamlet-level test for unaligned vector load/store operations.

This test bypasses lamlet.py instruction processing and directly sends
kinstructions to the kamlet array to test unaligned memory access:

1. Load data from memory with src_offset
2. Store data to memory with dst_offset

Parameters:
- src_ew: Source element width (8, 16, 32, 64)
- dst_ew: Destination element width (8, 16, 32, 64)
- vl: Vector length (number of elements)
- reg_ew: Register element width for vload/vstore (8, 16, 32, 64)
- src_offset: Byte offset for source address
- dst_offset: Byte offset for destination address
- lmul: Number of registers grouped as one logical register
"""

import asyncio
import logging
import struct
from random import Random

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


async def test_unaligned(
    clock: Clock,
    src_ew: int,
    dst_ew: int,
    vl: int,
    reg_ew: int,
    src_offset: int,
    dst_offset: int,
    lmul: int,
    j_rows: int,
    seed: int,
):
    """
    Test unaligned vector load/store operations.

    Loads vl elements from src+src_offset, stores to dst+dst_offset.
    """
    params = LamletParams(j_rows=j_rows)
    lamlet = Lamlet(clock, params)
    clock.create_task(update(clock, lamlet))
    clock.create_task(lamlet.run())

    await clock.next_cycle

    # Generate test data where each byte is its index (0, 1, 2, 3, ...)
    rnd = Random(seed)
    src_list = [rnd.getrandbits(src_ew) for i in range(vl)]

    logger.info(f"Test parameters:")
    logger.info(f"  src_ew={src_ew}, dst_ew={dst_ew}, reg_ew={reg_ew}")
    logger.info(f"  vl={vl}, lmul={lmul}")
    logger.info(f"  src_offset={src_offset}, dst_offset={dst_offset}")
    logger.info(f"  seed={seed}")
    logger.info(f"src_list: {src_list[:16]}{'...' if len(src_list) > 16 else ''}")

    # Convert to binary format for memory operations
    src_data = pack_elements(src_list, src_ew)

    # Expected output: same values, but packed with dst_ew
    # When widening (dst_ew > src_ew), zero-extend
    # When narrowing (dst_ew < src_ew), truncate
    if dst_ew >= src_ew:
        expected_list = src_list  # zero-extension is implicit
    else:
        mask = (1 << dst_ew) - 1
        expected_list = [v & mask for v in src_list]
    expected_data = pack_elements(expected_list, dst_ew)

    # Memory layout:
    # src_base + src_offset -> source data
    # dst_base + dst_offset -> destination data
    src_base = get_vpu_base_addr(src_ew)
    dst_base = get_vpu_base_addr(dst_ew) + 0x10000  # Offset to avoid overlap

    src_addr = src_base + src_offset
    dst_addr = dst_base + dst_offset

    # Allocate memory regions with enough padding for offsets
    alloc_size = max(1024, vl * max(src_ew, dst_ew) // 8 + max(src_offset, dst_offset) + 64)

    lamlet.allocate_memory(
        GlobalAddress(bit_addr=src_base * 8, params=params),
        alloc_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, src_ew)
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=dst_base * 8, params=params),
        alloc_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, dst_ew)
    )

    # Write initial data to memory at the offset address
    await lamlet.set_memory(src_addr, src_data)

    logger.info(f"Memory initialized at src_addr=0x{src_addr:x}, dst_addr=0x{dst_addr:x}")

    # Calculate elements per iteration based on lmul and reg_ew
    vline_bytes = params.vline_bytes
    elements_per_iteration = (lmul * vline_bytes * 8) // reg_ew
    logger.info(f"lmul={lmul}, vline_bytes={vline_bytes}, elements_per_iteration={elements_per_iteration}")

    src_ordering = Ordering(WordOrder.STANDARD, src_ew)
    dst_ordering = Ordering(WordOrder.STANDARD, dst_ew)
    reg_ordering = Ordering(WordOrder.STANDARD, reg_ew)

    for iter_start in range(0, vl, elements_per_iteration):
        iter_count = min(elements_per_iteration, vl - iter_start)
        logger.info(f"Iteration: elements {iter_start} to {iter_start + iter_count - 1}")

        # Calculate byte offsets for this iteration
        src_byte_offset = iter_start * src_ew // 8
        dst_byte_offset = iter_start * dst_ew // 8

        # Load from source into v0
        lamlet.vl = iter_count
        lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[reg_ew]  # Set SEW
        await lamlet.vload(
            vd=0,
            addr=src_addr + src_byte_offset,
            ordering=src_ordering,
            n_elements=iter_count,
            start_index=0,
            mask_reg=None,
        )

        # Store from v0 to destination
        await lamlet.vstore(
            vs=0,
            addr=dst_addr + dst_byte_offset,
            ordering=dst_ordering,
            n_elements=iter_count,
            start_index=0,
            mask_reg=None,
        )

    logger.info("All iterations processed")

    # Read back results and verify
    logger.info("Reading results from memory")
    result_size = vl * dst_ew // 8
    future = await lamlet.get_memory(dst_addr, result_size)
    await future
    result = future.result()
    logger.info(f"Result: {result.hex()}")
    logger.info(f"Expected: {expected_data.hex()}")

    # Compare
    if result == expected_data:
        logger.warning("TEST PASSED: Results match expected values!")
        return 0
    else:
        logger.error("TEST FAILED: Results do not match expected values")
        result_list = unpack_elements(result, dst_ew)
        # Show detailed comparison
        for i in range(min(vl, 32)):  # Show first 32 elements max
            actual_val = result_list[i] if i < len(result_list) else None
            expected_val = expected_list[i]
            src_val = src_list[i]
            match = "✓" if actual_val == expected_val else "✗"
            logger.error(
                f"  [{i}] src={src_val} -> expected={expected_val} actual={actual_val} {match}"
            )
        if vl > 32:
            logger.error(f"  ... and {vl - 32} more elements")
        return 1


async def main(
    clock,
    src_ew: int,
    dst_ew: int,
    vl: int,
    reg_ew: int,
    src_offset: int,
    dst_offset: int,
    lmul: int,
    j_rows: int,
    seed: int,
):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)

    clock.register_main()

    clock_driver_task = clock.create_task(clock.clock_driver())
    exit_code = await test_unaligned(
        clock, src_ew, dst_ew, vl, reg_ew, src_offset, dst_offset, lmul, j_rows, seed
    )

    logger.warning(f"Test completed with exit_code: {exit_code}")
    clock.running = False

    return exit_code


if __name__ == '__main__':
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='Test unaligned vector load/store operations')
    parser.add_argument('--src-ew', type=int, default=64,
                        help='Source element width in bits (8, 16, 32, 64) (default: 64)')
    parser.add_argument('--dst-ew', type=int, default=64,
                        help='Destination element width in bits (8, 16, 32, 64) (default: 64)')
    parser.add_argument('--vl', type=int, default=16,
                        help='Vector length - number of elements (default: 16)')
    parser.add_argument('--reg-ew', type=int, default=64,
                        help='Register element width for vload/vstore (default: 64)')
    parser.add_argument('--src-offset', type=int, default=0,
                        help='Source byte offset (default: 0)')
    parser.add_argument('--dst-offset', type=int, default=0,
                        help='Destination byte offset (default: 0)')
    parser.add_argument('--lmul', type=int, default=8,
                        help='LMUL - number of registers grouped as one (default: 8)')
    parser.add_argument('--j-rows', type=int, default=1,
                        help='Number of jamlet rows per kamlet (default: 1)')
    parser.add_argument('--seed', '-s', type=int, default=0,
                        help='Random seed for test data generation (default: 0)')
    args = parser.parse_args()

    # Validate element widths
    valid_ews = [8, 16, 32, 64]
    if args.src_ew not in valid_ews:
        print(f"Error: src-ew must be one of {valid_ews}", file=sys.stderr)
        sys.exit(1)
    if args.dst_ew not in valid_ews:
        print(f"Error: dst-ew must be one of {valid_ews}", file=sys.stderr)
        sys.exit(1)
    if args.reg_ew not in valid_ews:
        print(f"Error: reg-ew must be one of {valid_ews}", file=sys.stderr)
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
            f'Starting with src_ew={args.src_ew}, dst_ew={args.dst_ew}, vl={args.vl}, '
            f'reg_ew={args.reg_ew}, src_offset={args.src_offset}, dst_offset={args.dst_offset}, '
            f'lmul={args.lmul}, j_rows={args.j_rows}, seed={args.seed}'
        )
        exit_code = asyncio.run(main(
            clock, args.src_ew, args.dst_ew, args.vl, args.reg_ew,
            args.src_offset, args.dst_offset, args.lmul, args.j_rows, args.seed
        ))
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
