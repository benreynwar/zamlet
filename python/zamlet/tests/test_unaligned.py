"""
Test for unaligned vector load/store operations.

Loads and stores data through a mix of scalar and VPU pages with random
element widths. The kamlet handles ew mismatches between the register
ordering and the memory page ordering via J2J remapping.

Parameters:
- reg_ew: Register/instruction element width (8, 16, 32, 64)
- vl: Vector length (number of elements)
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
from zamlet.params import ZamletParams
from zamlet.geometries import SMALL_GEOMETRIES, scale_n_tests
from zamlet.oamlet.oamlet import Oamlet
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


def allocate_pages(lamlet, base_addr, n_pages, rnd, params):
    """Allocate n_pages at base_addr, each randomly scalar or VPU with random ew.

    Returns a list of (is_scalar, ew) tuples for each page.
    """
    page_descs = []
    for i in range(n_pages):
        is_scalar = rnd.choice([True, False])
        ew = rnd.choice([8, 16, 32, 64])
        page_descs.append((is_scalar, ew))
        page_addr = base_addr + i * params.page_bytes
        g_addr = GlobalAddress(bit_addr=page_addr * 8, params=params)
        if is_scalar:
            lamlet.allocate_memory(
                g_addr, params.page_bytes,
                memory_type=MemoryType.SCALAR_IDEMPOTENT, ordering=None)
        else:
            lamlet.allocate_memory(
                g_addr, params.page_bytes,
                memory_type=MemoryType.VPU,
                ordering=Ordering(WordOrder.STANDARD, ew))
    return page_descs


async def run_unaligned_test(
    clock: Clock,
    vl: int,
    reg_ew: int,
    src_offset: int,
    dst_offset: int,
    lmul: int,
    params: ZamletParams,
    seed: int,
):
    """
    Test unaligned vector load/store operations.

    Loads vl elements from src+src_offset, stores to dst+dst_offset.
    """
    lamlet = Oamlet(clock, params)
    clock.create_task(update(clock, lamlet))
    clock.create_task(lamlet.run())

    await clock.next_cycle

    rnd = Random(seed)
    src_list = [rnd.getrandbits(reg_ew) for i in range(vl)]

    logger.info(f"Test parameters:")
    logger.info(f"  reg_ew={reg_ew}")
    logger.info(f"  vl={vl}, lmul={lmul}")
    logger.info(f"  src_offset={src_offset}, dst_offset={dst_offset}")
    logger.info(f"  seed={seed}")
    logger.info(f"src_list: {src_list[:16]}{'...' if len(src_list) > 16 else ''}")

    src_data = pack_elements(src_list, reg_ew)
    expected_list = src_list
    expected_data = pack_elements(expected_list, reg_ew)

    src_base = 0x40000000
    dst_base = 0x50000000

    src_addr = src_base + src_offset
    dst_addr = dst_base + dst_offset

    # Allocate pages individually with random types (scalar or VPU with random ew)
    page_bytes = params.page_bytes
    data_size = vl * reg_ew // 8
    src_n_pages = (src_offset + data_size + page_bytes - 1) // page_bytes
    dst_n_pages = (dst_offset + data_size + page_bytes - 1) // page_bytes

    src_page_descs = allocate_pages(lamlet, src_base, src_n_pages, rnd, params)
    dst_page_descs = allocate_pages(lamlet, dst_base, dst_n_pages, rnd, params)

    src_desc = ' '.join(f"{'S' if s else 'V'}{ew}" for s, ew in src_page_descs)
    dst_desc = ' '.join(f"{'S' if s else 'V'}{ew}" for s, ew in dst_page_descs)
    logger.info(f"Source pages: {src_desc}")
    logger.info(f"Dest pages: {dst_desc}")


    # Write initial data to memory at the offset address
    await lamlet.set_memory(src_addr, src_data)

    logger.info(f"Memory initialized at src_addr=0x{src_addr:x}, dst_addr=0x{dst_addr:x}")

    # Calculate elements per iteration based on lmul and reg_ew
    vline_bytes = params.vline_bytes
    elements_per_iteration = (lmul * vline_bytes * 8) // reg_ew
    logger.info(f"lmul={lmul}, vline_bytes={vline_bytes}, elements_per_iteration={elements_per_iteration}")

    ordering = Ordering(WordOrder.STANDARD, reg_ew)

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
            ordering=ordering,
            n_elements=iter_count,
            start_index=0,
            mask_reg=None,
            parent_span_id=span_id,
        )

        # Store from v0 to destination
        await lamlet.vstore(
            vs=0,
            addr=dst_addr + dst_byte_offset,
            ordering=ordering,
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
    vl: int,
    reg_ew: int,
    src_offset: int,
    dst_offset: int,
    lmul: int,
    params: ZamletParams,
    seed: int,
):
    clock.register_main()

    clock_driver_task = clock.create_task(clock.clock_driver())
    exit_code = await run_unaligned_test(
        clock, vl, reg_ew, src_offset, dst_offset, lmul, params, seed
    )

    logger.warning(f"Test completed with exit_code: {exit_code}")
    clock.running = False

    return exit_code


def run_test(reg_ew, src_offset, dst_offset, vl, lmul=8,
             params: ZamletParams = None, seed=0):
    """Helper to run a single test configuration."""
    if params is None:
        params = ZamletParams()
    clock = Clock(max_cycles=10000)
    exit_code = asyncio.run(main(
        clock, vl, reg_ew, src_offset, dst_offset, lmul, params, seed
    ))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def random_offset(rnd: Random, params: ZamletParams, eb: int, data_size: int):
    """Generate a random element-aligned offset.

    50% of the time, choose an offset that forces the data to cross a page boundary.
    """
    page_bytes = params.page_bytes
    if rnd.random() < 0.5 and data_size < page_bytes:
        # Place the start near the end of a page so data crosses into the next page
        page_index = rnd.randint(0, 2)
        page_start = page_index * page_bytes
        # Between 1 element and data_size before the page end
        max_into_page = min(data_size, page_bytes) - eb
        dist_from_end = rnd.randint(1, max(1, max_into_page // eb)) * eb
        return page_start + page_bytes - dist_from_end
    else:
        max_offset_elements = (3 * page_bytes) // eb
        return rnd.randint(0, max_offset_elements) * eb


def random_test_config(rnd: Random, params: ZamletParams):
    """Generate a random test configuration."""
    reg_ew = rnd.choice([8, 16, 32, 64])
    eb = reg_ew // 8
    vl = rnd.randint(1, 128)
    data_size = vl * eb
    src_offset = random_offset(rnd, params, eb, data_size)
    dst_offset = random_offset(rnd, params, eb, data_size)
    return reg_ew, src_offset, dst_offset, vl


def generate_test_params(n_tests: int = 8, seed: int = 42):
    """Generate random test parameter combinations."""
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name = rnd.choice(list(SMALL_GEOMETRIES.keys()))
        geom_params = SMALL_GEOMETRIES[geom_name]
        reg_ew, src_offset, dst_offset, vl = random_test_config(rnd, geom_params)
        id_str = (f"{i}_{geom_name}_reg{reg_ew}"
                  f"_srcoff{src_offset}_dstoff{dst_offset}_vl{vl}")
        test_params.append(pytest.param(
            geom_params, reg_ew, src_offset, dst_offset, vl, id=id_str))
    return test_params


@pytest.mark.parametrize("params,reg_ew,src_offset,dst_offset,vl",
                         generate_test_params(n_tests=scale_n_tests(128)))
def test_unaligned(params, reg_ew, src_offset, dst_offset, vl):
    run_test(reg_ew, src_offset, dst_offset, vl, params=params)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test unaligned vector load/store operations')
    parser.add_argument('--vl', type=int, default=16,
                        help='Vector length - number of elements (default: 16)')
    parser.add_argument('--reg-ew', type=int, default=64, choices=[8, 16, 32, 64],
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

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    params = get_geometry(args.geometry)
    run_test(args.reg_ew, args.src_offset, args.dst_offset,
             args.vl, lmul=args.lmul, params=params, seed=args.seed)
