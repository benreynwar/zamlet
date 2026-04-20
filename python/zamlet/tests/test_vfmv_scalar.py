"""
Test vfmv.f.s and vfmv.s.f (floating-point scalar moves).

These transfer a single SEW-wide element between element 0 of a vector
register and an FP scalar register, ignoring LMUL.

- vfmv.f.s rd, vs2:  f[rd] = vs2[0]
- vfmv.s.f vd, rs1:  vd[0] = f[rs1]; other lanes undisturbed.

The python model does not NaN-box the FP scalar today (see docs/TODO.md),
so for comparison purposes we only inspect the low SEW bits of the freg.
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
from zamlet.instructions.vector import VfmvFs, VfmvSf
from zamlet.tests.test_utils import (
    setup_lamlet, pack_elements, unpack_elements, dump_span_trees,
)

logger = logging.getLogger(__name__)


DIRECTIONS = ('f_s', 's_f')   # vfmv.f.s  and  vfmv.s.f


async def _run_inner(lamlet, direction: str, data_ew: int,
                     params: ZamletParams, seed: int):
    rnd = Random(seed)
    data_bytes = data_ew // 8
    data_mask = (1 << data_ew) - 1
    ordering = Ordering(lamlet.word_order, data_ew)

    logger.info(
        f"Test: direction={direction} data_ew={data_ew} seed={seed}")

    data_base_addr = 0x90000000
    page_bytes = params.page_bytes
    for i in range(6):
        page_addr = data_base_addr + i * page_bytes
        lamlet.allocate_memory(
            GlobalAddress(bit_addr=page_addr * 8, params=params),
            page_bytes, memory_type=MemoryType.VPU)

    elements_in_vline = params.vline_bytes * 8 // data_ew
    vl = elements_in_vline

    src_data = [rnd.getrandbits(data_ew) for _ in range(vl)]
    init_vd = [rnd.getrandbits(data_ew) for _ in range(vl)]
    scalar_val = rnd.getrandbits(data_ew)

    src_mem_addr = data_base_addr
    init_mem_addr = data_base_addr + 2 * page_bytes
    dst_mem_addr = data_base_addr + 4 * page_bytes

    lamlet.vl = vl
    lamlet.vtype = {8: 0x0, 16: 0x8, 32: 0x10, 64: 0x18}[data_ew]
    lamlet.vstart = 0
    lamlet.pc = 0

    vs2_reg = 1        # source vreg for vfmv.f.s
    vd_reg = 4         # dest vreg for vfmv.s.f
    freg_num = 5

    span_id = lamlet.monitor.create_span(
        span_type=SpanType.RISCV_INSTR, component="test",
        completion_type=CompletionType.FIRE_AND_FORGET,
        mnemonic="test_vfmv_scalar")

    if direction == 'f_s':
        # Load vs2 with src_data; run vfmv.f.s rd=freg, vs2; check freg[0..SEW/8].
        await lamlet.set_memory(
            src_mem_addr, pack_elements(src_data, data_ew), ordering=ordering)
        await lamlet.vload(
            vd=vs2_reg, addr=src_mem_addr, ordering=ordering,
            n_elements=vl, mask_reg=None, start_index=0,
            parent_span_id=span_id, emul=1)

        instr = VfmvFs(rd=freg_num, vs2=vs2_reg)
        await instr.update_state(lamlet)

        # Drain the read-register-element future so freg is settled.
        while lamlet.scalar._frf[freg_num].updating():
            await lamlet.clock.next_cycle

        freg_bytes = lamlet.scalar.read_freg(freg_num)
        actual = int.from_bytes(freg_bytes[:data_bytes],
                                byteorder='little', signed=False) & data_mask
        expected = src_data[0] & data_mask

        if actual != expected:
            logger.error(
                f"FAIL: freg low SEW bits expected={expected:#x} "
                f"actual={actual:#x}")
            return 1

        logger.info(f"PASS: vfmv.f.s freg low SEW = {actual:#x}")

    else:  # 's_f'
        # Initialize vd with init_vd; load scalar into freg; run vfmv.s.f;
        # store vd and verify element 0 overwritten, others preserved.
        await lamlet.set_memory(
            init_mem_addr, pack_elements(init_vd, data_ew), ordering=ordering)
        await lamlet.vload(
            vd=vd_reg, addr=init_mem_addr, ordering=ordering,
            n_elements=vl, mask_reg=None, start_index=0,
            parent_span_id=span_id, emul=1)

        freg_bytes = scalar_val.to_bytes(8, byteorder='little', signed=False)
        lamlet.scalar.write_freg(freg_num, freg_bytes, span_id)

        instr = VfmvSf(vd=vd_reg, rs1=freg_num)
        await instr.update_state(lamlet)

        await lamlet.vstore(
            vs=vd_reg, addr=dst_mem_addr, ordering=ordering,
            n_elements=vl, start_index=0, mask_reg=None,
            parent_span_id=span_id)

        effective_scalar = scalar_val & data_mask
        expected = [effective_scalar] + list(init_vd[1:])

        errors = []
        for i in range(vl):
            addr = dst_mem_addr + i * data_bytes
            fut = await lamlet.get_memory(addr, data_bytes)
            await fut
            actual = unpack_elements(fut.result(), data_ew)[0]
            if actual != expected[i]:
                errors.append(
                    f"  [{i}] expected={expected[i]:#x} actual={actual:#x}")

        if errors:
            logger.error(f"FAIL: {len(errors)} element(s) differ")
            for err in errors[:16]:
                logger.error(err)
            return 1

        logger.info(f"PASS: vfmv.s.f element 0 = {effective_scalar:#x}, "
                    f"{vl - 1} tail elements preserved")

    lamlet.monitor.finalize_children(span_id)
    return 0


async def run_vfmv_scalar_test(
    clock: Clock,
    direction: str,
    data_ew: int,
    params: ZamletParams,
    seed: int,
    dump_spans: bool = False,
):
    lamlet = await setup_lamlet(clock, params)
    try:
        return await _run_inner(lamlet, direction, data_ew, params, seed)
    finally:
        if dump_spans:
            dump_span_trees(lamlet.monitor)


async def main(clock, direction, data_ew, params, seed, dump_spans=False):
    clock.register_main()
    clock.create_task(clock.clock_driver())
    exit_code = await run_vfmv_scalar_test(
        clock, direction=direction, data_ew=data_ew, params=params,
        seed=seed, dump_spans=dump_spans)
    clock.running = False
    return exit_code


def run_test(direction: str, data_ew: int, params: ZamletParams, seed: int,
             dump_spans: bool = False):
    clock = Clock(max_cycles=20000)
    exit_code = asyncio.run(main(
        clock, direction=direction, data_ew=data_ew, params=params,
        seed=seed, dump_spans=dump_spans))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def generate_test_params(n_tests: int = 16, seed: int = 42):
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name = rnd.choice(list(SMALL_GEOMETRIES.keys()))
        geom_params = SMALL_GEOMETRIES[geom_name]
        data_ew = rnd.choice([32, 64])
        direction = rnd.choice(DIRECTIONS)
        id_str = f"{i}_{geom_name}_{direction}_ew{data_ew}"
        test_params.append(pytest.param(
            geom_params, direction, data_ew, i, id=id_str))
    return test_params


@pytest.mark.parametrize(
    "params,direction,data_ew,seed",
    generate_test_params(n_tests=scale_n_tests(16)))
def test_vfmv_scalar(params, direction, data_ew, seed):
    run_test(direction=direction, data_ew=data_ew, params=params, seed=seed)


if __name__ == '__main__':
    import sys
    import argparse

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(
        description='Test vfmv.f.s / vfmv.s.f')
    parser.add_argument('--direction', choices=list(DIRECTIONS), default='s_f')
    parser.add_argument('--data-ew', type=int, default=32)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--geometry', '-g', default='k2x2_j1x2')
    parser.add_argument('--list-geometries', action='store_true')
    parser.add_argument('--dump-spans', action='store_true')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    params = get_geometry(args.geometry)
    run_test(direction=args.direction, data_ew=args.data_ew,
             params=params, seed=args.seed, dump_spans=args.dump_spans)
