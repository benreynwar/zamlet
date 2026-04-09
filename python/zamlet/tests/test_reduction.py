"""
Test vector reduction operations.

Tests the tree reduction implementation by loading data into vector registers,
invoking the reduction, storing the result, and comparing against Python-computed
expected values.
"""

import asyncio
import logging
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.addresses import GlobalAddress, MemoryType, Ordering, WordOrder
from zamlet.geometries import SMALL_GEOMETRIES, scale_n_tests
from zamlet.kamlet.kinstructions import VRedOp
from zamlet.instructions.vector import Vreduction
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, unpack_elements, dump_span_trees,
)

logger = logging.getLogger(__name__)


def _reduce_ref(op, vs1_scalar, vs2_elements, ew):
    """Compute expected reduction result in Python."""
    mask = (1 << ew) - 1
    sign_bit = 1 << (ew - 1)

    def to_signed(v):
        v = v & mask
        return v - (1 << ew) if v & sign_bit else v

    if op == VRedOp.SUM:
        result = vs1_scalar
        for v in vs2_elements:
            result = (result + v) & mask
        return result
    elif op == VRedOp.AND:
        result = vs1_scalar
        for v in vs2_elements:
            result = result & v
        return result & mask
    elif op == VRedOp.OR:
        result = vs1_scalar
        for v in vs2_elements:
            result = result | v
        return result & mask
    elif op == VRedOp.XOR:
        result = vs1_scalar
        for v in vs2_elements:
            result = result ^ v
        return result & mask
    elif op == VRedOp.MAX:
        result = to_signed(vs1_scalar)
        for v in vs2_elements:
            result = max(result, to_signed(v))
        return result & mask
    elif op == VRedOp.MAXU:
        result = vs1_scalar & mask
        for v in vs2_elements:
            result = max(result, v & mask)
        return result
    elif op == VRedOp.MIN:
        result = to_signed(vs1_scalar)
        for v in vs2_elements:
            result = min(result, to_signed(v))
        return result & mask
    elif op == VRedOp.MINU:
        result = vs1_scalar & mask
        for v in vs2_elements:
            result = min(result, v & mask)
        return result
    else:
        raise ValueError(f"Unsupported op: {op}")


async def run_reduction_test(
    clock: Clock, op: VRedOp, vl: int, ew: int,
    seed: int, lmul: int, params: ZamletParams,
    dump_spans: bool = False,
):
    lamlet = await setup_lamlet(clock, params)

    try:
        return await _run_reduction_test_inner(
            lamlet, clock, op, vl, ew, seed, lmul, params)
    finally:
        if dump_spans:
            dump_span_trees(lamlet.monitor)


async def _run_reduction_test_inner(lamlet, clock, op, vl, ew, seed, lmul, params):
    rnd = Random(seed)

    vs2_list = [rnd.getrandbits(ew) for _ in range(vl)]
    vs1_scalar = rnd.getrandbits(ew)

    expected = _reduce_ref(op, vs1_scalar, vs2_list, ew)

    logger.info(f"op={op.value} vl={vl} ew={ew} lmul={lmul} vs1[0]={vs1_scalar}")
    logger.info(f"vs2={vs2_list[:8]}{'...' if len(vs2_list) > 8 else ''}")
    logger.info(f"expected={expected}")

    # Allocate memory
    page_bytes = params.page_bytes
    byte_width = ew // 8
    data_size = max(vl, 1) * byte_width * lmul
    alloc_size = max(page_bytes, ((data_size + page_bytes - 1) // page_bytes) * page_bytes)

    base_addr = 0x90000000
    vs2_addr = base_addr
    vs1_addr = base_addr + alloc_size
    vd_addr = base_addr + 2 * alloc_size
    ordering = Ordering(lamlet.word_order, ew)

    for addr in (vs2_addr, vs1_addr, vd_addr):
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=addr * 8, params=params),
            alloc_size, memory_type=MemoryType.VPU)

    # Write test data
    await lamlet.set_memory(vs2_addr, pack_elements(vs2_list, ew), ordering=ordering)
    await lamlet.set_memory(vs1_addr, pack_elements([vs1_scalar], ew), ordering=ordering)

    # Set vtype
    vsew = {8: 0, 16: 1, 32: 2}[ew]
    vlmul = {1: 0, 2: 1, 4: 2, 8: 3}[lmul]
    lamlet.vtype = (vsew << 3) | vlmul

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_reduction")

    # Register allocation: vs2 occupies v2..v(2+lmul-1), so vs1 and vd must not overlap.
    vs2_reg = 2
    vs1_reg = vs2_reg + lmul
    vd_reg = vs1_reg + 1

    # Load vs2
    lamlet.vl = vl
    await lamlet.vload(
        vd=vs2_reg, addr=vs2_addr, ordering=ordering,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=lmul)

    # Load vs1 (only element 0)
    lamlet.vl = 1
    await lamlet.vload(
        vd=vs1_reg, addr=vs1_addr, ordering=ordering,
        n_elements=1, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=1)

    # Run the reduction
    lamlet.vl = vl
    lamlet.pc = 0
    reduction_instr = Vreduction(vd=vd_reg, vs2=vs2_reg, vs1=vs1_reg, vm=1, op=op)
    await reduction_instr.update_state(lamlet)

    # Store vd element 0 to memory
    lamlet.vl = 1
    await lamlet.vstore(
        vs=vd_reg, addr=vd_addr, ordering=ordering,
        n_elements=1, start_index=0, mask_reg=None,
        parent_span_id=span_id)

    lamlet.monitor.finalize_children(span_id)

    # Read back and verify
    result_data = await lamlet.get_memory_blocking(vd_addr, byte_width)
    actual = unpack_elements(result_data, ew)[0]

    if actual == expected:
        logger.warning(f"PASS: {op.value} vl={vl} ew={ew} => {actual}")
        return 0
    else:
        logger.error(f"FAIL: {op.value} vl={vl} ew={ew} => {actual} != {expected}")
        logger.error(f"  vs2={vs2_list}")
        logger.error(f"  vs1[0]={vs1_scalar}")
        return 1


async def main_async(clock, op, vl, ew, seed, lmul, params, dump_spans=False):
    clock.register_main()
    clock.create_task(clock.clock_driver())
    exit_code = await run_reduction_test(
        clock, op, vl, ew, seed, lmul, params, dump_spans)
    logger.warning(f"Test completed with exit_code: {exit_code}")
    clock.running = False
    return exit_code


def run_test(op, vl, ew, seed=0, lmul=1, params=None):
    if params is None:
        params = ZamletParams()
    clock = Clock(max_cycles=10000)
    exit_code = asyncio.run(
        main_async(clock, op, vl, ew, seed, lmul, params))
    assert exit_code == 0, f"Test failed: {op.value} vl={vl} ew={ew}"


INTEGER_OPS = [
    VRedOp.SUM, VRedOp.AND, VRedOp.OR, VRedOp.XOR,
    VRedOp.MAX, VRedOp.MAXU, VRedOp.MIN, VRedOp.MINU,
]


def generate_test_params(n_tests=64, seed=42):
    rnd = Random(seed)
    test_params = []
    geom_names = list(SMALL_GEOMETRIES.keys())

    for i in range(n_tests):
        op = rnd.choice(INTEGER_OPS)
        geom_name = rnd.choice(geom_names)
        geom_params = SMALL_GEOMETRIES[geom_name]
        ew = rnd.choice([8, 16, 32])
        lmul = rnd.choice([1, 2, 4])
        elements_in_vline = geom_params.vline_bytes * 8 // ew
        vlmax = elements_in_vline * lmul
        vl = rnd.randint(1, vlmax)
        test_seed = rnd.randint(0, 10000)

        id_str = f"{i}_{op.value}_{geom_name}_ew{ew}_vl{vl}_s{test_seed}_m{lmul}"
        test_params.append(
            pytest.param(op, geom_params, ew, vl, test_seed, lmul, id=id_str))

    return test_params


@pytest.mark.parametrize(
    "op,params,ew,vl,seed,lmul",
    generate_test_params(n_tests=scale_n_tests(32)))
def test_reduction(op, params, ew, vl, seed, lmul):
    run_test(op, vl, ew, seed, lmul, params=params)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test vector reductions')
    parser.add_argument('--op', default='sum',
                        choices=[op.value for op in INTEGER_OPS],
                        help='Reduction op (default: sum)')
    parser.add_argument('--vl', type=int, default=8)
    parser.add_argument('--ew', type=int, default=32, choices=[8, 16, 32])
    parser.add_argument('--seed', '-s', type=int, default=0)
    parser.add_argument('--lmul', type=int, default=1, choices=[1, 2, 4, 8])
    parser.add_argument('--geometry', '-g', default='k2x1_j1x1')
    parser.add_argument('--list-geometries', action='store_true')
    parser.add_argument('--dump-spans', action='store_true')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    params = get_geometry(args.geometry)
    op = VRedOp(args.op)

    level = logging.DEBUG
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    run_test(op, args.vl, args.ew, args.seed, args.lmul, params=params)
