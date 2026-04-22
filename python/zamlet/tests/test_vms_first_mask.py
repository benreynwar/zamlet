"""
Test vmsbf.m, vmsif.m, and vmsof.m.

The masked cases check both parts of the spec: v0 participates in finding the
first active source bit, and inactive destination mask elements are preserved
under the model's current undisturbed policy.
"""

import asyncio
import logging
from dataclasses import dataclass
from random import Random

import pytest

from zamlet.addresses import GlobalAddress, MemoryType, Ordering
from zamlet.geometries import SMALL_GEOMETRIES, scale_n_tests
from zamlet.instructions.vector import VmsFirstMask
from zamlet.kamlet import kinstructions
from zamlet.monitor import CompletionType, SpanType
from zamlet.params import ZamletParams
from zamlet.runner import Clock
from zamlet.tests.test_utils import (
    dump_span_trees, setup_lamlet, setup_mask_register,
)

logger = logging.getLogger(__name__)


TRIALS_PER_MODE = 4
MODES = (
    ('vmsbf.m', kinstructions.SetMaskBitsMode.LT),
    ('vmsif.m', kinstructions.SetMaskBitsMode.LE),
    ('vmsof.m', kinstructions.SetMaskBitsMode.EQ),
)


@dataclass
class Trial:
    idx: int
    mnemonic: str
    mode: kinstructions.SetMaskBitsMode
    vl: int
    vm: int
    vs2_bits: list
    v0_bits: list
    init_vd_bits: list
    expected: list


def _mask_addr(trial: Trial, page_bytes: int) -> int:
    return 0x90000000 + trial.idx * 8 * page_bytes


def _v0_addr(trial: Trial, page_bytes: int) -> int:
    return _mask_addr(trial, page_bytes) + 2 * page_bytes


def _vd_addr(trial: Trial, page_bytes: int) -> int:
    return _mask_addr(trial, page_bytes) + 4 * page_bytes


def _out_addr(trial: Trial, page_bytes: int) -> int:
    return _mask_addr(trial, page_bytes) + 6 * page_bytes


def _bytes_to_mask_bits(params: ZamletParams, data: bytes) -> list:
    bits = []
    max_bits = params.word_bytes * 8 * params.j_in_l
    for i in range(max_bits):
        jamlet_idx = i % params.j_in_l
        local_bit = i // params.j_in_l
        byte_idx = jamlet_idx * params.word_bytes + local_bit // 8
        bits.append(bool((data[byte_idx] >> (local_bit % 8)) & 1))
    return bits


def _expected(mode, vl, vm, vs2_bits, v0_bits, init_vd_bits) -> list:
    first = None
    for i in range(vl):
        if vs2_bits[i] and (vm == 1 or v0_bits[i]):
            first = i
            break

    expected = list(init_vd_bits)
    for i in range(vl):
        if vm == 0 and not v0_bits[i]:
            continue
        if first is None:
            bit = mode != kinstructions.SetMaskBitsMode.EQ
        elif mode == kinstructions.SetMaskBitsMode.LT:
            bit = i < first
        elif mode == kinstructions.SetMaskBitsMode.LE:
            bit = i <= first
        elif mode == kinstructions.SetMaskBitsMode.EQ:
            bit = i == first
        else:
            raise NotImplementedError(mode)
        expected[i] = bit
    return expected


def _build_trials(rnd: Random, params: ZamletParams) -> list:
    max_bits = params.word_bytes * 8 * params.j_in_l
    trials = []
    idx = 0
    patterns = ['random', 'allzero', 'first0', 'late']
    for mnemonic, mode in MODES:
        for _ in range(TRIALS_PER_MODE):
            vl = rnd.randint(1, max_bits)
            vm = rnd.choice([0, 1])
            pattern = patterns[idx % len(patterns)]
            if pattern == 'allzero':
                vs2_bits = [False] * max_bits
            elif pattern == 'first0':
                vs2_bits = [False] * max_bits
                vs2_bits[0] = True
            elif pattern == 'late':
                vs2_bits = [False] * max_bits
                vs2_bits[max(0, vl - 1)] = True
            else:
                vs2_bits = [rnd.random() < 0.25 for _ in range(max_bits)]
            v0_bits = [rnd.random() < 0.6 for _ in range(max_bits)]
            init_vd_bits = [rnd.random() < 0.5 for _ in range(max_bits)]
            expected = _expected(mode, vl, vm, vs2_bits, v0_bits, init_vd_bits)
            trials.append(Trial(
                idx=idx, mnemonic=mnemonic, mode=mode, vl=vl, vm=vm,
                vs2_bits=vs2_bits, v0_bits=v0_bits,
                init_vd_bits=init_vd_bits, expected=expected))
            idx += 1
    return trials


async def _read_mask_register(lamlet, reg: int, addr: int, span_id: int) -> list:
    params = lamlet.params
    ordering = Ordering(lamlet.word_order, 64)
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=addr * 8, params=params),
        params.page_bytes, memory_type=MemoryType.VPU)
    lamlet.vrf_ordering[reg] = ordering
    await lamlet.vstore(
        vs=reg, addr=addr, ordering=ordering, n_elements=params.j_in_l,
        start_index=0, mask_reg=None, parent_span_id=span_id, emul=1)
    data = await lamlet.get_memory_blocking(addr, params.vline_bytes)
    return _bytes_to_mask_bits(params, data)


async def _run_inner(lamlet, seed: int, params: ZamletParams):
    rnd = Random(seed)
    trials = _build_trials(rnd, params)
    vs2_reg = 2
    vd_reg = 4

    lamlet.vtype = 0x18
    lamlet.vstart = 0
    lamlet.pc = 0

    for trial in trials:
        span_id = lamlet.monitor.create_span(
            span_type=SpanType.RISCV_INSTR, component="test",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=f"trial_{trial.idx}")

        lamlet.vl = trial.vl
        await setup_mask_register(
            lamlet, mask_reg=vs2_reg, mask_bits=trial.vs2_bits,
            page_bytes=params.page_bytes,
            mask_mem_addr=_mask_addr(trial, params.page_bytes))
        await setup_mask_register(
            lamlet, mask_reg=vd_reg, mask_bits=trial.init_vd_bits,
            page_bytes=params.page_bytes,
            mask_mem_addr=_vd_addr(trial, params.page_bytes))
        if trial.vm == 0:
            await setup_mask_register(
                lamlet, mask_reg=0, mask_bits=trial.v0_bits,
                page_bytes=params.page_bytes,
                mask_mem_addr=_v0_addr(trial, params.page_bytes))

        instr = VmsFirstMask(
            vd=vd_reg, vs2=vs2_reg, vm=trial.vm,
            mode=trial.mode, mnemonic=trial.mnemonic)
        await instr.update_state(lamlet)
        await lamlet.await_vreg_write_pending(vd_reg, 1)

        actual = await _read_mask_register(
            lamlet, vd_reg, _out_addr(trial, params.page_bytes), span_id)
        lamlet.monitor.finalize_children(span_id)

        errors = [
            i for i in range(trial.vl)
            if actual[i] != trial.expected[i]
        ]
        if errors:
            logger.error(
                f"FAIL trial={trial.idx} {trial.mnemonic} vm={trial.vm} "
                f"vl={trial.vl}: {len(errors)} mismatches")
            for i in errors[:16]:
                logger.error(
                    f"  [{i}] expected={trial.expected[i]} actual={actual[i]} "
                    f"vs2={trial.vs2_bits[i]} v0={trial.v0_bits[i]} "
                    f"init={trial.init_vd_bits[i]}")
            return 1

    logger.info(f"PASS: {len(trials)} trials")
    return 0


async def run_vms_first_mask_test(clock: Clock, seed: int,
                                  params: ZamletParams,
                                  dump_spans: bool = False):
    lamlet = await setup_lamlet(clock, params)
    try:
        return await _run_inner(lamlet, seed, params)
    finally:
        if dump_spans:
            dump_span_trees(lamlet.monitor)


async def main(clock, seed, params, dump_spans=False):
    clock.register_main()
    clock.create_task(clock.clock_driver())
    exit_code = await run_vms_first_mask_test(clock, seed, params, dump_spans)
    clock.running = False
    return exit_code


def run_test(seed: int, params: ZamletParams, dump_spans: bool = False,
             max_cycles: int = 100000):
    clock = Clock(max_cycles=max_cycles)
    exit_code = asyncio.run(main(clock, seed, params, dump_spans))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


def generate_test_params(n_tests: int = 8, seed: int = 42):
    rnd = Random(seed)
    test_params = []
    geom_names = list(SMALL_GEOMETRIES.keys())
    for i in range(n_tests):
        geom_name = rnd.choice(geom_names)
        geom_params = SMALL_GEOMETRIES[geom_name]
        test_seed = rnd.randint(0, 10000)
        id_str = f"{i}_{geom_name}_s{test_seed}"
        test_params.append(pytest.param(geom_params, test_seed, id=id_str))
    return test_params


@pytest.mark.parametrize(
    "params,seed", generate_test_params(n_tests=scale_n_tests(8)))
def test_vms_first_mask(params, seed):
    run_test(seed=seed, params=params)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test vmsbf/vmsif/vmsof')
    parser.add_argument('--seed', '-s', type=int, default=0)
    parser.add_argument('--geometry', '-g', default='k2x1_j1x1')
    parser.add_argument('--list-geometries', action='store_true')
    parser.add_argument('--dump-spans', action='store_true')
    parser.add_argument('--max-cycles', type=int, default=100000)
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    params = get_geometry(args.geometry)
    run_test(seed=args.seed, params=params, dump_spans=args.dump_spans,
             max_cycles=args.max_cycles)
