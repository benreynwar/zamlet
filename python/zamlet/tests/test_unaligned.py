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

import pytest

from zamlet.runner import Clock
from zamlet.params import LamletParams
from zamlet.geometries import SMALL_GEOMETRIES, scale_n_tests
from zamlet.lamlet.lamlet import Lamlet
from zamlet.addresses import GlobalAddress, MemoryType, Ordering, WordOrder
from zamlet.monitor import CompletionType, SpanType

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


async def run_unaligned_test(
    clock: Clock,
    src_ew: int,
    dst_ew: int,
    vl: int,
    reg_ew: int,
    src_offset: int,
    dst_offset: int,
    lmul: int,
    params: LamletParams,
    seed: int,
):
    """
    Test unaligned vector load/store operations.

    Loads vl elements from src+src_offset, stores to dst+dst_offset.
    """
    lamlet = Lamlet(clock, params)
    clock.create_task(update(clock, lamlet))
    clock.create_task(lamlet.run())

    await clock.next_cycle

    # Generate test data - elements are reg_ew sized (the size we load/store)
    # The values fit in src_ew bits but are stored as reg_ew elements in memory
    rnd = Random(seed)
    src_list = [rnd.getrandbits(src_ew) for i in range(vl)]
    #src_list = [i for i in range(vl)]

    logger.info(f"Test parameters:")
    logger.info(f"  src_ew={src_ew}, dst_ew={dst_ew}, reg_ew={reg_ew}")
    logger.info(f"  vl={vl}, lmul={lmul}")
    logger.info(f"  src_offset={src_offset}, dst_offset={dst_offset}")
    logger.info(f"  seed={seed}")
    logger.info(f"src_list: {src_list[:16]}{'...' if len(src_list) > 16 else ''}")

    # Memory stores reg_ew-sized elements (memory ordering is separate from element size)
    src_data = pack_elements(src_list, reg_ew)

    # Expected output: same values, packed with reg_ew (element size in registers)
    expected_list = src_list
    expected_data = pack_elements(expected_list, reg_ew)

    # Memory layout:
    # src_base + src_offset -> source data
    # dst_base + dst_offset -> destination data
    src_base = get_vpu_base_addr(src_ew)
    dst_base = get_vpu_base_addr(dst_ew) + 0x10000  # Offset to avoid overlap

    src_addr = src_base + src_offset
    dst_addr = dst_base + dst_offset

    # Allocate memory regions with enough padding for offsets (must be page-aligned)
    # Data is packed with reg_ew, so use that for size calculation
    data_size = vl * reg_ew // 8
    alloc_size = max(1024, data_size + max(src_offset, dst_offset) + 64)
    alloc_size = ((alloc_size + params.page_bytes - 1) // params.page_bytes) * params.page_bytes

    lamlet.allocate_memory(
        GlobalAddress(bit_addr=src_base * 8, params=params),
        alloc_size, memory_type=MemoryType.VPU, ordering=Ordering(WordOrder.STANDARD, src_ew)
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=dst_base * 8, params=params),
        alloc_size, memory_type=MemoryType.VPU, ordering=Ordering(WordOrder.STANDARD, dst_ew)
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

        # Calculate byte offsets for this iteration (data is packed with reg_ew)
        src_byte_offset = iter_start * reg_ew // 8
        dst_byte_offset = iter_start * reg_ew // 8

        span_id = lamlet.monitor.create_span(
            span_type=SpanType.RISCV_INSTR, component="test",
            completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_iteration")

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
            parent_span_id=span_id,
            reg_ordering=reg_ordering,
        )

        # Store from v0 to destination
        await lamlet.vstore(
            vs=0,
            addr=dst_addr + dst_byte_offset,
            ordering=dst_ordering,
            n_elements=iter_count,
            start_index=0,
            mask_reg=None,
            parent_span_id=span_id,
        )

    logger.info("All iterations processed")

    # Read back results and verify
    logger.info("Reading results from memory")
    result_size = vl * reg_ew // 8
    future = await lamlet.get_memory(dst_addr, result_size)
    await future
    result = future.result()
    logger.info(f"Result: {result.hex()}")
    logger.info(f"Expected: {expected_data.hex()}")

    # Write span trees for debugging
    with open('span_trees.txt', 'w') as f:
        for span in lamlet.monitor.spans.values():
            if span.parent is None:
                f.write(lamlet.monitor.format_span_tree(span.span_id, max_depth=20))
                f.write('\n')
    logger.info("Span trees written to span_trees.txt")

    # Compare
    if result == expected_data:
        logger.warning("TEST PASSED: Results match expected values!")
        return 0
    else:
        logger.error("TEST FAILED: Results do not match expected values")
        result_list = unpack_elements(result, reg_ew)
        # Find mismatches
        mismatches = []
        for i in range(vl):
            actual_val = result_list[i] if i < len(result_list) else None
            expected_val = expected_list[i]
            if actual_val != expected_val:
                mismatches.append((i, expected_list[i], actual_val))
        logger.error(f"  {len(mismatches)} mismatches out of {vl} elements")
        # Show first 16 mismatches with context
        for idx, (i, expected_val, actual_val) in enumerate(mismatches[:16]):
            src_val = src_list[i]
            logger.error(
                f"  [{i}] src={src_val} -> expected={expected_val} actual={actual_val} ✗"
            )
        if len(mismatches) > 16:
            logger.error(f"  ... and {len(mismatches) - 16} more mismatches")
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
    params: LamletParams,
    seed: int,
):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)

    clock.register_main()

    clock_driver_task = clock.create_task(clock.clock_driver())
    exit_code = await run_unaligned_test(
        clock, src_ew, dst_ew, vl, reg_ew, src_offset, dst_offset, lmul, params, seed
    )

    logger.warning(f"Test completed with exit_code: {exit_code}")
    clock.running = False

    return exit_code


def run_test(reg_ew, src_ew, dst_ew, src_offset, dst_offset, vl, lmul=8,
             params: LamletParams = None, seed=0):
    """Helper to run a single test configuration."""
    if params is None:
        params = LamletParams()
    clock = Clock(max_cycles=10000)
    exit_code = asyncio.run(main(
        clock, src_ew, dst_ew, vl, reg_ew, src_offset, dst_offset, lmul, params, seed
    ))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def random_test_config(rnd: Random):
    """Generate a random test configuration."""
    geom_name = rnd.choice(list(SMALL_GEOMETRIES.keys()))
    geom_params = SMALL_GEOMETRIES[geom_name]
    reg_ew = rnd.choice([8, 16, 32, 64])
    src_ew = rnd.choice([8, 16, 32, 64])
    dst_ew = rnd.choice([8, 16, 32, 64])
    src_offset = rnd.randint(0, 512) * 8
    dst_offset = rnd.randint(0, 512) * 8
    vl = rnd.randint(1, 128)
    return geom_name, geom_params, reg_ew, src_ew, dst_ew, src_offset, dst_offset, vl


def generate_test_params(n_tests: int = 8, seed: int = 42):
    """Generate random test parameter combinations."""
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name, geom_params, reg_ew, src_ew, dst_ew, src_offset, dst_offset, vl = \
            random_test_config(rnd)
        id_str = (f"{i}_{geom_name}_reg{reg_ew}_src{src_ew}_dst{dst_ew}"
                  f"_srcoff{src_offset}_dstoff{dst_offset}_vl{vl}")
        test_params.append(pytest.param(
            geom_params, reg_ew, src_ew, dst_ew,
            src_offset, dst_offset, vl, id=id_str))
    return test_params


@pytest.mark.parametrize("params,reg_ew,src_ew,dst_ew,src_offset,dst_offset,vl",
                         generate_test_params(n_tests=scale_n_tests(128)))
def test_unaligned(params, reg_ew, src_ew, dst_ew, src_offset, dst_offset, vl):
    run_test(reg_ew, src_ew, dst_ew, src_offset, dst_offset, vl, params=params)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

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
    parser.add_argument('--geometry', '-g', default='k2x1_j1x1',
                        help='Geometry name (default: k2x1_j1x1)')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries and exit')
    parser.add_argument('--seed', '-s', type=int, default=0,
                        help='Random seed for test data generation (default: 0)')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

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
            f'Starting with src_ew={args.src_ew}, dst_ew={args.dst_ew}, vl={args.vl}, '
            f'reg_ew={args.reg_ew}, src_offset={args.src_offset}, dst_offset={args.dst_offset}, '
            f'lmul={args.lmul}, geometry={args.geometry}, seed={args.seed}'
        )
        exit_code = asyncio.run(main(
            clock, args.src_ew, args.dst_ew, args.vl, args.reg_ew,
            args.src_offset, args.dst_offset, args.lmul, params, args.seed
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
