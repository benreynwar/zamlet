"""
Test scalar reads from VPU memory.

Isolates whether set_memory/get_memory and vstore/get_memory agree on
VPU address mapping, motivated by the vecadd_evict failure where scalar
lwu from VPU memory returns wrong data.
"""

import asyncio
import logging

import pytest

from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.addresses import GlobalAddress, MemoryType, Ordering, WordOrder
from zamlet.geometries import SMALL_GEOMETRIES
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, unpack_elements, get_vpu_base_addr,
)

logger = logging.getLogger(__name__)


async def test_set_get_roundtrip(clock: Clock, params: ZamletParams, ew: int, n_elements: int):
    """Sub-test 1: set_memory then get_memory for each element."""
    lamlet = await setup_lamlet(clock, params)

    base = get_vpu_base_addr(ew)
    element_bytes = ew // 8
    page_bytes = params.page_bytes
    total_bytes = n_elements * element_bytes
    n_pages = (total_bytes + page_bytes - 1) // page_bytes

    ordering = Ordering(WordOrder.STANDARD, ew)
    for i in range(n_pages):
        page_addr = base + i * page_bytes
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=page_addr * 8, params=params),
            page_bytes, memory_type=MemoryType.VPU, ordering=ordering)

    values = [1100 + i for i in range(n_elements)]
    data = pack_elements(values, ew)
    await lamlet.set_memory(base, data)

    # Issue all reads before awaiting any, so they're in-flight in parallel.
    futures = []
    for i in range(n_elements):
        addr = base + i * element_bytes
        futures.append((i, addr, await lamlet.get_memory(addr, element_bytes)))

    errors = []
    for i, addr, future in futures:
        await future
        actual = unpack_elements(future.result(), ew)[0]
        if actual != values[i]:
            errors.append(f"  [{i}] addr=0x{addr:x} expected={values[i]} actual={actual}")

    if errors:
        for err in errors[:16]:
            logger.error(err)
        return 1

    logger.info(f"PASS: set_memory round-trip, {n_elements} elements correct")
    return 0


async def test_vstore_get_memory(clock: Clock, params: ZamletParams, ew: int, n_elements: int):
    """Sub-test 2: vload from src, vstore to dst, then get_memory from dst."""
    lamlet = await setup_lamlet(clock, params)

    src_base = get_vpu_base_addr(ew)
    dst_base = src_base + 0x100000
    element_bytes = ew // 8
    page_bytes = params.page_bytes
    total_bytes = n_elements * element_bytes
    n_pages = (total_bytes + page_bytes - 1) // page_bytes

    ordering = Ordering(WordOrder.STANDARD, ew)
    for region_base in [src_base, dst_base]:
        for i in range(n_pages):
            page_addr = region_base + i * page_bytes
            lamlet.allocate_memory(
                GlobalAddress(bit_addr=page_addr * 8, params=params),
                page_bytes, memory_type=MemoryType.VPU, ordering=ordering)

    values = [1100 + i for i in range(n_elements)]
    data = pack_elements(values, ew)
    await lamlet.set_memory(src_base, data)

    lamlet.vl = n_elements
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[ew]

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_vstore_get_memory")

    vd = 0
    await lamlet.vload(
        vd=vd, addr=src_base, ordering=ordering,
        n_elements=n_elements, mask_reg=None, start_index=0,
        parent_span_id=span_id, lmul=1)

    vs = vd
    await lamlet.vstore(
        vs=vs, addr=dst_base, ordering=ordering,
        n_elements=n_elements, start_index=0, mask_reg=None,
        parent_span_id=span_id)

    # Issue all reads before awaiting any, so they're in-flight in parallel.
    futures = []
    for i in range(n_elements):
        addr = dst_base + i * element_bytes
        futures.append((i, addr, await lamlet.get_memory(addr, element_bytes)))

    errors = []
    for i, addr, future in futures:
        await future
        actual = unpack_elements(future.result(), ew)[0]
        if actual != values[i]:
            errors.append(f"  [{i}] addr=0x{addr:x} expected={values[i]} actual={actual}")

    lamlet.monitor.finalize_children(span_id)

    if errors:
        for err in errors[:16]:
            logger.error(err)
        return 1

    logger.info(f"PASS: vstore+get_memory, {n_elements} elements correct")
    return 0


async def test_vstore_roundtrip(clock: Clock, params: ZamletParams, ew: int, n_elements: int):
    """Sub-test 3: vload src, vstore dst1, vload dst1, vstore dst2, get_memory dst2."""
    lamlet = await setup_lamlet(clock, params)

    src_base = get_vpu_base_addr(ew)
    dst1_base = src_base + 0x100000
    dst2_base = src_base + 0x200000
    element_bytes = ew // 8
    page_bytes = params.page_bytes
    total_bytes = n_elements * element_bytes
    n_pages = (total_bytes + page_bytes - 1) // page_bytes

    ordering = Ordering(WordOrder.STANDARD, ew)
    for region_base in [src_base, dst1_base, dst2_base]:
        for i in range(n_pages):
            page_addr = region_base + i * page_bytes
            lamlet.allocate_memory(
                GlobalAddress(bit_addr=page_addr * 8, params=params),
                page_bytes, memory_type=MemoryType.VPU, ordering=ordering)

    values = [1100 + i for i in range(n_elements)]
    data = pack_elements(values, ew)
    await lamlet.set_memory(src_base, data)

    lamlet.vl = n_elements
    lamlet.vtype = {8: 0x0, 16: 0x1, 32: 0x2, 64: 0x3}[ew]

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_vstore_roundtrip")

    reg_a = 0
    elements_per_vline = params.vline_bytes * 8 // ew
    n_data_regs = (n_elements + elements_per_vline - 1) // elements_per_vline
    reg_b = n_data_regs

    # vload src -> reg_a
    await lamlet.vload(
        vd=reg_a, addr=src_base, ordering=ordering,
        n_elements=n_elements, mask_reg=None, start_index=0,
        parent_span_id=span_id, lmul=1)

    # vstore reg_a -> dst1
    await lamlet.vstore(
        vs=reg_a, addr=dst1_base, ordering=ordering,
        n_elements=n_elements, start_index=0, mask_reg=None,
        parent_span_id=span_id)

    # vload dst1 -> reg_b
    await lamlet.vload(
        vd=reg_b, addr=dst1_base, ordering=ordering,
        n_elements=n_elements, mask_reg=None, start_index=0,
        parent_span_id=span_id, lmul=1)

    # vstore reg_b -> dst2
    await lamlet.vstore(
        vs=reg_b, addr=dst2_base, ordering=ordering,
        n_elements=n_elements, start_index=0, mask_reg=None,
        parent_span_id=span_id)

    # Issue all reads before awaiting any, so they're in-flight in parallel.
    futures = []
    for i in range(n_elements):
        addr = dst2_base + i * element_bytes
        futures.append((i, addr, await lamlet.get_memory(addr, element_bytes)))

    errors = []
    for i, addr, future in futures:
        await future
        actual = unpack_elements(future.result(), ew)[0]
        if actual != values[i]:
            errors.append(f"  [{i}] addr=0x{addr:x} expected={values[i]} actual={actual}")

    lamlet.monitor.finalize_children(span_id)

    if errors:
        for err in errors[:16]:
            logger.error(err)
        return 1

    logger.info(f"PASS: vstore roundtrip, {n_elements} elements correct")
    return 0


async def run_all(clock: Clock, params: ZamletParams, ew: int, n_elements: int, subtest: str):
    clock.register_main()
    clock.create_task(clock.clock_driver())

    runners = {
        'set_get': test_set_get_roundtrip,
        'vstore_get': test_vstore_get_memory,
        'vstore_roundtrip': test_vstore_roundtrip,
    }

    runner = runners[subtest]
    exit_code = await runner(clock, params, ew, n_elements)
    clock.running = False
    return exit_code


def run_test(params: ZamletParams, ew: int, n_elements: int, subtest: str,
             max_cycles: int = 50000):
    clock = Clock(max_cycles=max_cycles)
    exit_code = asyncio.run(run_all(clock, params, ew, n_elements, subtest))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


@pytest.mark.parametrize("geom_name,params", list(SMALL_GEOMETRIES.items()),
                         ids=list(SMALL_GEOMETRIES.keys()))
@pytest.mark.parametrize("subtest", ['set_get', 'vstore_get', 'vstore_roundtrip'])
def test_scalar_read_vpu(geom_name, params, subtest):
    run_test(params=params, ew=32, n_elements=8, subtest=subtest)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test scalar reads from VPU memory')
    parser.add_argument('--ew', type=int, default=32, help='Element width in bits')
    parser.add_argument('--n-elements', type=int, default=8, help='Number of elements')
    parser.add_argument('--geometry', '-g', default='k2x1_j1x1',
                        help='Geometry name (default: k2x1_j1x1)')
    parser.add_argument('--subtest', default='all',
                        choices=['all', 'set_get', 'vstore_get', 'vstore_roundtrip'],
                        help='Which sub-test to run (default: all)')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries and exit')
    parser.add_argument('--max-cycles', type=int, default=50000,
                        help='Maximum simulation cycles (default: 50000)')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    params = get_geometry(args.geometry)
    subtests = ['set_get', 'vstore_get', 'vstore_roundtrip'] if args.subtest == 'all' \
        else [args.subtest]

    for subtest in subtests:
        print(f"\n--- Running sub-test: {subtest} ---")
        run_test(params=params, ew=args.ew, n_elements=args.n_elements,
                 subtest=subtest, max_cycles=args.max_cycles)
        print(f"--- {subtest}: PASSED ---")
