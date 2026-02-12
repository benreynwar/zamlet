"""
Test vrgather.vv (register gather) instruction.

Tests RegGather kinstr which gathers elements from a source register
using indices from another register:
    vd[i] = (vs1[i] >= VLMAX) ? 0 : vs2[vs1[i]]
"""

import asyncio
import logging
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.addresses import GlobalAddress, MemoryType, Ordering, WordOrder
from zamlet.geometries import SMALL_GEOMETRIES, scale_n_tests
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, unpack_elements, get_vpu_base_addr, dump_span_trees,
)

logger = logging.getLogger(__name__)


async def run_reg_gather_test(
    clock: Clock,
    data_ew: int,
    index_ew: int,
    vl: int,
    params: ZamletParams,
    seed: int,
    dump_spans: bool = False,
):
    """Test register gather operation."""
    lamlet = await setup_lamlet(clock, params)

    try:
        return await _run_reg_gather_test_inner(lamlet, clock, data_ew, index_ew, vl, params, seed)
    finally:
        if dump_spans:
            dump_span_trees(lamlet.monitor)


async def _run_reg_gather_test_inner(
    lamlet,
    clock: Clock,
    data_ew: int,
    index_ew: int,
    vl: int,
    params: ZamletParams,
    seed: int,
):
    rnd = Random(seed)
    data_bytes = data_ew // 8
    index_bytes = index_ew // 8

    logger.info(f"Test parameters: data_ew={data_ew}, index_ew={index_ew}, vl={vl}, seed={seed}")

    data_base_addr = get_vpu_base_addr(data_ew)
    index_base_addr = get_vpu_base_addr(index_ew)
    page_bytes = params.page_bytes
    data_ordering = Ordering(WordOrder.STANDARD, data_ew)
    index_ordering = Ordering(WordOrder.STANDARD, index_ew)

    # If same ew, use different offsets within the same address space
    if data_ew == index_ew:
        index_base_addr = data_base_addr + 4 * page_bytes

    # Allocate memory for source and destination data
    for i in range(4):
        page_addr = data_base_addr + i * page_bytes
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=page_addr * 8, params=params),
            page_bytes, memory_type=MemoryType.VPU, ordering=data_ordering)

    # Allocate memory for index data
    for i in range(2):
        page_addr = index_base_addr + i * page_bytes
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=page_addr * 8, params=params),
            page_bytes, memory_type=MemoryType.VPU, ordering=index_ordering)

    # Compute VLMAX for data element width
    elements_in_vline = params.vline_bytes * 8 // data_ew
    vlmax = elements_in_vline  # LMUL=1

    # Generate source data - fill the whole register (VLMAX elements)
    src_data = [rnd.getrandbits(data_ew) for _ in range(vlmax)]

    # Generate indices - must be < VLMAX to produce valid results
    indices = [rnd.randint(0, vlmax - 1) for _ in range(vl)]

    logger.info(f"vlmax={vlmax}, vl={vl}")
    logger.info(f"Source data: {[hex(x) for x in src_data[:8]]}...")
    logger.info(f"Indices: {indices[:16]}...")

    # Compute expected results
    expected = [src_data[idx] for idx in indices]
    logger.info(f"Expected: {[hex(x) for x in expected[:8]]}...")

    # Write source data to memory
    src_mem_addr = data_base_addr
    await lamlet.set_memory(src_mem_addr, pack_elements(src_data, data_ew))

    # Write indices to memory
    index_mem_addr = index_base_addr
    await lamlet.set_memory(index_mem_addr, pack_elements(indices, index_ew))

    # Set up lamlet vector state
    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x8, 32: 0x10, 64: 0x18}[data_ew]
    lamlet.vstart = 0

    # Allocate registers: vs2=0 (source), vs1=1 (indices), vd=2 (dest)
    vs2_reg = 0
    vs1_reg = 1
    vd_reg = 2

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_reg_gather")

    # Load source data into vs2
    logger.info(f"Loading source data into v{vs2_reg}")
    await lamlet.vload(
        vd=vs2_reg,
        addr=src_mem_addr,
        ordering=data_ordering,
        n_elements=vlmax,
        mask_reg=None,
        start_index=0,
        parent_span_id=span_id,
    )

    # Load indices into vs1
    logger.info(f"Loading indices into v{vs1_reg}")
    await lamlet.vload(
        vd=vs1_reg,
        addr=index_mem_addr,
        ordering=index_ordering,
        n_elements=vl,
        mask_reg=None,
        start_index=0,
        parent_span_id=span_id,
    )

    # Set up vrf_ordering for registers
    lamlet.vrf_ordering[vs2_reg] = data_ordering
    lamlet.vrf_ordering[vs1_reg] = index_ordering
    lamlet.vrf_ordering[vd_reg] = data_ordering

    # Execute vrgather.vv
    logger.info(f"Executing vrgather.vv v{vd_reg}, v{vs2_reg}, v{vs1_reg}")
    await lamlet.vrgather(
        vd=vd_reg, vs2=vs2_reg, vs1=vs1_reg,
        start_index=0, n_elements=vl,
        index_ew=index_ew, data_ew=data_ew,
        word_order=WordOrder.STANDARD, vlmax=vlmax,
        mask_reg=None, parent_span_id=span_id,
    )

    # Store result to memory
    dst_mem_addr = data_base_addr + 2 * page_bytes
    logger.info(f"Storing result to memory at 0x{dst_mem_addr:x}")
    await lamlet.vstore(
        vs=vd_reg,
        addr=dst_mem_addr,
        ordering=data_ordering,
        n_elements=vl,
        start_index=0,
        mask_reg=None,
        parent_span_id=span_id,
    )

    # Read back and verify results
    errors = []
    for i in range(vl):
        addr = dst_mem_addr + i * data_bytes
        future = await lamlet.get_memory(addr, data_bytes)
        await future
        actual = unpack_elements(future.result(), data_ew)[0]
        if actual != expected[i]:
            errors.append(f"  [{i}] index={indices[i]} expected={expected[i]:#x} actual={actual:#x}")

    if errors:
        logger.error(f"FAIL: {len(errors)} elements do not match")
        for err in errors[:16]:
            logger.error(err)
        if len(errors) > 16:
            logger.error(f"  ... and {len(errors) - 16} more errors")
        return 1

    logger.info(f"PASS: {vl} elements correct")
    lamlet.monitor.finalize_children(span_id)
    return 0


async def main(clock, data_ew, index_ew, vl, params, seed, dump_spans=False):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)
    clock.register_main()
    clock.create_task(clock.clock_driver())

    exit_code = await run_reg_gather_test(
        clock, data_ew=data_ew, index_ew=index_ew, vl=vl,
        params=params, seed=seed, dump_spans=dump_spans)
    clock.running = False
    return exit_code


def run_test(data_ew: int, index_ew: int, vl: int, params: ZamletParams, seed: int,
             dump_spans: bool = False):
    """Helper to run a single test configuration."""
    clock = Clock(max_cycles=50000)
    exit_code = asyncio.run(main(clock, data_ew=data_ew, index_ew=index_ew, vl=vl,
                                  params=params, seed=seed, dump_spans=dump_spans))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def generate_test_params(n_tests: int = 32, seed: int = 42):
    """Generate random test parameter combinations."""
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name = rnd.choice(list(SMALL_GEOMETRIES.keys()))
        geom_params = SMALL_GEOMETRIES[geom_name]
        data_ew = rnd.choice([8, 16, 32, 64])
        index_ew = rnd.choice([8, 16, 32, 64])
        # vl must be <= elements in one vline (LMUL=1) for both data and index
        max_vl_data = geom_params.vline_bytes * 8 // data_ew
        max_vl_index = geom_params.vline_bytes * 8 // index_ew
        max_vl = min(max_vl_data, max_vl_index)
        vl = rnd.randint(1, max_vl)
        id_str = f"{i}_{geom_name}_dew{data_ew}_iew{index_ew}_vl{vl}"
        test_params.append(pytest.param(geom_params, data_ew, index_ew, vl, i, id=id_str))
    return test_params


@pytest.mark.parametrize("params,data_ew,index_ew,vl,seed",
                         generate_test_params(n_tests=scale_n_tests(32)))
def test_reg_gather(params, data_ew, index_ew, vl, seed):
    """Test register gather with random configurations."""
    run_test(data_ew=data_ew, index_ew=index_ew, vl=vl, params=params, seed=seed)


if __name__ == '__main__':
    import sys
    import argparse

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test vrgather.vv instruction')
    parser.add_argument('--data-ew', type=int, default=64, help='Data element width in bits')
    parser.add_argument('--index-ew', type=int, default=64, help='Index element width in bits')
    parser.add_argument('--vl', type=int, default=8, help='Vector length')
    parser.add_argument('--seed', type=int, default=0, help='Random seed')
    parser.add_argument('--geometry', '-g', default='k2x2_j1x2',
                        help='Geometry name (default: k2x2_j1x2)')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries and exit')
    parser.add_argument('--dump-spans', action='store_true',
                        help='Dump span trees to span_trees.txt')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    params = get_geometry(args.geometry)
    run_test(data_ew=args.data_ew, index_ew=args.index_ew, vl=args.vl,
             params=params, seed=args.seed, dump_spans=args.dump_spans)
