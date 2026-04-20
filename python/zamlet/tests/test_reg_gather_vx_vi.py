"""
Test vrgather.vx and vrgather.vi (scalar/immediate index) instructions.

For vrgather.vx: idx = x[rs1] (zero-extended).
For vrgather.vi: idx = uimm5.
In both cases: vd[i] = (idx >= VLMAX) ? 0 : vs2[idx], for i in [vstart, vl).

The lamlet dispatch is asynchronous: the RISC-V instruction enqueues a
ReadRegWord kinstr for vs2[idx] and a LamletWaitingVrgatherBroadcast item,
then returns. A later VBroadcastOp is emitted when the word arrives. The
idx >= vlmax path broadcasts 0 directly without a remote fetch.
"""

import asyncio
import logging
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.addresses import GlobalAddress, MemoryType, Ordering
from zamlet.geometries import SMALL_GEOMETRIES, scale_n_tests
from zamlet.monitor import CompletionType, SpanType
from zamlet.instructions.vector import VrgatherVxVi
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, unpack_elements, dump_span_trees,
)

logger = logging.getLogger(__name__)


async def run_vrgather_vx_vi_test(
    clock: Clock,
    data_ew: int,
    vl: int,
    idx: int,
    is_imm: bool,
    params: ZamletParams,
    seed: int,
    dump_spans: bool = False,
):
    """Drive vrgather.vx or vrgather.vi and verify vd against the reference."""
    lamlet = await setup_lamlet(clock, params)
    try:
        return await _run_inner(lamlet, data_ew, vl, idx, is_imm, params, seed)
    finally:
        if dump_spans:
            dump_span_trees(lamlet.monitor)


async def _run_inner(lamlet, data_ew, vl, idx, is_imm, params, seed):
    rnd = Random(seed)
    data_bytes = data_ew // 8
    data_ordering = Ordering(lamlet.word_order, data_ew)

    elements_in_vline = params.vline_bytes * 8 // data_ew
    vlmax = elements_in_vline  # LMUL=1 for these tests

    if is_imm:
        assert 0 <= idx < 32, f'vrgather.vi idx must fit in uimm5; got {idx}'

    logger.info(
        f"Test params: data_ew={data_ew} vl={vl} vlmax={vlmax} "
        f"idx={idx} is_imm={is_imm} seed={seed}")

    page_bytes = params.page_bytes
    src_base = 0x90000000
    dst_base = src_base + max(page_bytes, 4096)
    for base in (src_base, dst_base):
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=base * 8, params=params),
            page_bytes, memory_type=MemoryType.VPU)

    src_data = [rnd.getrandbits(data_ew) for _ in range(vlmax)]
    await lamlet.set_memory(src_base, pack_elements(src_data, data_ew),
                            ordering=data_ordering)

    if idx >= vlmax:
        expected = [0] * vl
    else:
        expected = [src_data[idx]] * vl

    logger.info(f"Source[idx]={hex(src_data[idx]) if idx < vlmax else 'OOR'}")
    logger.info(f"Expected[:8]={[hex(x) for x in expected[:8]]}")

    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x8, 32: 0x10, 64: 0x18}[data_ew]
    lamlet.vstart = 0
    lamlet.pc = 0

    vs2_reg = 4
    vd_reg = 8
    rs1_reg = 5

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET,
        mnemonic="test_vrgather_vx_vi")

    await lamlet.vload(
        vd=vs2_reg, addr=src_base, ordering=data_ordering,
        n_elements=vlmax, mask_reg=None, start_index=0,
        parent_span_id=span_id, emul=1)

    if not is_imm:
        rs1_bytes = idx.to_bytes(8, byteorder='little', signed=False)
        lamlet.scalar.write_reg(rs1_reg, rs1_bytes, span_id)

    index_src = idx if is_imm else rs1_reg
    instr = VrgatherVxVi(vd=vd_reg, vs2=vs2_reg, index_src=index_src,
                         is_imm=is_imm, vm=1)
    await instr.update_state(lamlet)

    await lamlet.vstore(
        vs=vd_reg, addr=dst_base, ordering=data_ordering,
        n_elements=vl, start_index=0, mask_reg=None,
        parent_span_id=span_id, emul=1)

    errors = []
    for i in range(vl):
        addr = dst_base + i * data_bytes
        future = await lamlet.get_memory(addr, data_bytes)
        await future
        actual = unpack_elements(future.result(), data_ew)[0]
        if actual != expected[i]:
            errors.append(
                f"  [{i}] expected={expected[i]:#x} actual={actual:#x}")

    lamlet.monitor.finalize_children(span_id)

    if errors:
        logger.error(f"FAIL: {len(errors)} mismatches")
        for e in errors[:16]:
            logger.error(e)
        if len(errors) > 16:
            logger.error(f"  ... and {len(errors) - 16} more")
        return 1

    logger.info(f"PASS: {vl} elements correct")
    return 0


async def main(clock, data_ew, vl, idx, is_imm, params, seed, dump_spans=False):
    clock.register_main()
    clock.create_task(clock.clock_driver())
    exit_code = await run_vrgather_vx_vi_test(
        clock, data_ew=data_ew, vl=vl, idx=idx, is_imm=is_imm,
        params=params, seed=seed, dump_spans=dump_spans)
    clock.running = False
    return exit_code


def run_test(data_ew: int, vl: int, idx: int, is_imm: bool,
             params: ZamletParams, seed: int, dump_spans: bool = False):
    clock = Clock(max_cycles=50000)
    exit_code = asyncio.run(main(
        clock, data_ew=data_ew, vl=vl, idx=idx, is_imm=is_imm,
        params=params, seed=seed, dump_spans=dump_spans))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def generate_test_params(n_tests: int = 32, seed: int = 42):
    """Random (geometry, data_ew, vl, idx, is_imm) combos, plus OOR cases."""
    rnd = Random(seed)
    test_params = []
    # Mix of .vx and .vi with in-range idx across geometries / data_ew.
    for i in range(n_tests):
        geom_name = rnd.choice(list(SMALL_GEOMETRIES.keys()))
        geom_params = SMALL_GEOMETRIES[geom_name]
        data_ew = rnd.choice([8, 16, 32, 64])
        vlmax = geom_params.vline_bytes * 8 // data_ew
        vl = rnd.randint(1, vlmax)
        is_imm = rnd.random() < 0.5
        idx_hi = (vlmax - 1) if not is_imm else min(vlmax - 1, 31)
        idx = rnd.randint(0, idx_hi)
        kind = 'vi' if is_imm else 'vx'
        id_str = f"{i}_{geom_name}_dew{data_ew}_vl{vl}_idx{idx}_{kind}"
        test_params.append(pytest.param(
            geom_params, data_ew, vl, idx, is_imm, i, id=id_str))
    # Explicit out-of-range cases (.vx only so we can pick idx >= 32 when needed).
    for i, geom_name in enumerate(SMALL_GEOMETRIES):
        geom_params = SMALL_GEOMETRIES[geom_name]
        data_ew = 32
        vlmax = geom_params.vline_bytes * 8 // data_ew
        vl = max(1, vlmax // 2)
        idx = vlmax + 3  # out of range
        id_str = f"oor{i}_{geom_name}_dew{data_ew}_vl{vl}_idx{idx}_vx"
        test_params.append(pytest.param(
            geom_params, data_ew, vl, idx, False, 1000 + i, id=id_str))
    return test_params


@pytest.mark.parametrize("params,data_ew,vl,idx,is_imm,seed",
                         generate_test_params(n_tests=scale_n_tests(32)))
def test_reg_gather_vx_vi(params, data_ew, vl, idx, is_imm, seed):
    """Test vrgather.vx and vrgather.vi with random configurations."""
    run_test(data_ew=data_ew, vl=vl, idx=idx, is_imm=is_imm,
             params=params, seed=seed)


if __name__ == '__main__':
    import sys
    import argparse

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(
        description='Test vrgather.vx / vrgather.vi instructions')
    parser.add_argument('--data-ew', type=int, default=32,
                        help='Data element width in bits')
    parser.add_argument('--vl', type=int, default=8, help='Vector length')
    parser.add_argument('--idx', type=int, default=0,
                        help='Gather index (scalar for .vx, uimm5 for .vi)')
    parser.add_argument('--is-imm', action='store_true',
                        help='Use .vi form (uimm5) instead of .vx')
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
    run_test(data_ew=args.data_ew, vl=args.vl, idx=args.idx,
             is_imm=args.is_imm, params=params, seed=args.seed,
             dump_spans=args.dump_spans)
