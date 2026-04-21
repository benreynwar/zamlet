"""
Test vcpop.m (population count of active mask bits).

Exercises the MaskPopcountLocal kinstr + tree-reduction SUM path by counting
set bits in a mask register, comparing against a Python popcount reference.

A single test case kicks off many trials concurrently: per-trial mask regs
and rd registers are distinct, so the hardware can execute them in parallel.
vm=0 trials share v0 and naturally serialize on that register.
"""

import asyncio
import logging
from dataclasses import dataclass
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.geometries import SMALL_GEOMETRIES, scale_n_tests
from zamlet.instructions.vector import VcpopM
from zamlet.tests.test_utils import (
    setup_lamlet, setup_mask_register, dump_span_trees,
)

logger = logging.getLogger(__name__)


TRIALS_PER_TEST = 8


@dataclass
class Trial:
    idx: int
    vl: int
    vm: int
    mask_bits: list
    v0_bits: list
    mask_reg: int
    rd: int
    expected: int


def _trial_mask_addr(trial: Trial, page_bytes: int) -> int:
    return 0x90000000 + trial.idx * 4 * page_bytes


def _trial_v0_addr(trial: Trial, page_bytes: int) -> int:
    return _trial_mask_addr(trial, page_bytes) + 2 * page_bytes


async def _load_trial_mask(lamlet, trial: Trial, page_bytes: int):
    lamlet.vl = trial.vl
    await setup_mask_register(
        lamlet, mask_reg=trial.mask_reg, mask_bits=trial.mask_bits[:trial.vl],
        page_bytes=page_bytes, mask_mem_addr=_trial_mask_addr(trial, page_bytes))


async def _issue_trial_vcpop(lamlet, trial: Trial, page_bytes: int):
    """Issue VcpopM, loading v0 first if vm=0. Must run in trial order per
    test since vm=0 trials depend on v0."""
    lamlet.vl = trial.vl
    if trial.vm == 0:
        await setup_mask_register(
            lamlet, mask_reg=0, mask_bits=trial.v0_bits[:trial.vl],
            page_bytes=page_bytes, mask_mem_addr=_trial_v0_addr(trial, page_bytes))
    instr = VcpopM(rd=trial.rd, vs2=trial.mask_reg, vm=trial.vm)
    await instr.update_state(lamlet)


def _build_trials(rnd: Random, params: ZamletParams) -> list:
    word_bits = params.word_bytes * 8
    max_bits = params.j_in_l * word_bits

    # Distinct mask vregs per trial so the hardware can run trials in parallel.
    # Leave v0 for vm=0 and give each trial its own mask slot + distinct rd.
    # Arch vregs [1..31] are available; stay well under to avoid stepping on
    # scratch temps used inside VcpopM.
    mask_reg_pool = [2, 4, 6, 8, 10, 12, 14, 16]
    rd_pool = [5, 6, 7, 8, 9, 10, 11, 12]
    assert TRIALS_PER_TEST <= len(mask_reg_pool)

    trials = []
    for i in range(TRIALS_PER_TEST):
        vl = rnd.randint(1, max_bits)
        vm = rnd.choice([0, 1])
        mask_bits = [rnd.randint(0, 1) == 1 for _ in range(max_bits)]
        v0_bits = [rnd.randint(0, 1) == 1 for _ in range(max_bits)]
        if vm == 0:
            expected = sum(1 for k in range(vl) if mask_bits[k] and v0_bits[k])
        else:
            expected = sum(1 for b in mask_bits[:vl] if b)
        trials.append(Trial(
            idx=i, vl=vl, vm=vm,
            mask_bits=mask_bits, v0_bits=v0_bits,
            mask_reg=mask_reg_pool[i], rd=rd_pool[i],
            expected=expected))
    return trials


async def _run_inner(lamlet, seed: int, params: ZamletParams):
    rnd = Random(seed)
    trials = _build_trials(rnd, params)

    lamlet.vtype = 0x18  # vsew=3 (ew=64), vlmul=0 — mask instrs ignore lmul
    lamlet.vstart = 0
    lamlet.pc = 0

    for trial in trials:
        logger.info(
            f"trial={trial.idx} vl={trial.vl} vm={trial.vm} "
            f"expected={trial.expected} rd={trial.rd}")

    # Phase 1: queue all per-trial mask register loads. Each trial uses a
    # distinct mask_reg so the hardware can satisfy these loads concurrently.
    for trial in trials:
        await _load_trial_mask(lamlet, trial, params.page_bytes)

    # Phase 2: queue all vcpops. vm=0 trials load v0 just before their vcpop
    # (v0 is shared), so those pairs serialize on v0. vm=1 trials have no v0
    # dependency and overlap with everything else.
    for trial in trials:
        await _issue_trial_vcpop(lamlet, trial, params.page_bytes)

    # Wait for every rd to settle.
    for trial in trials:
        while lamlet.scalar._rf[trial.rd].updating():
            await lamlet.clock.next_cycle

    fails = 0
    for trial in trials:
        rd_bytes = lamlet.scalar.read_reg(trial.rd)
        actual = int.from_bytes(rd_bytes, byteorder='little', signed=False)
        if actual != trial.expected:
            fails += 1
            logger.error(
                f"FAIL trial={trial.idx} vl={trial.vl} vm={trial.vm}: "
                f"expected={trial.expected} actual={actual}")
            logger.error(f"  mask_bits={trial.mask_bits[:trial.vl]}")
            if trial.vm == 0:
                logger.error(f"  v0_bits  ={trial.v0_bits[:trial.vl]}")

    if fails:
        logger.error(f"FAIL: {fails}/{len(trials)} trials failed")
        return 1

    logger.info(f"PASS: {len(trials)}/{len(trials)} trials")
    return 0


async def run_vcpop_test(clock: Clock, seed: int, params: ZamletParams,
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
    exit_code = await run_vcpop_test(clock, seed, params, dump_spans)
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
def test_vcpop(params, seed):
    run_test(seed=seed, params=params)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test vcpop.m')
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
