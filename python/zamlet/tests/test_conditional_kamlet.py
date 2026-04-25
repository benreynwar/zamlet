"""
Direct kamlet-level test for conditional operations.

This test bypasses lamlet.py instruction processing and directly sends
kinstructions to the kamlet array to test the conditional operation:

z[i] = (x[i] < 5) ? a[i] : b[i]

Where:
- x is int8_t array (mask condition)
- a and b are int16_t arrays (data to select from)
- z is int16_t array (output)
"""

import logging
import struct
from dataclasses import dataclass
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.geometries import SMALL_GEOMETRIES, scale_n_tests
from zamlet.oamlet.oamlet import Oamlet
from zamlet.addresses import GlobalAddress, MemoryType, Ordering, WordOrder, KMAddr, RegAddr
from zamlet.instructions.vector import VCmpVi, VCmpVv, VCmpVx
from zamlet.kamlet import kinstructions
from zamlet.transactions.load import Load
from zamlet.transactions.store import Store
from zamlet.monitor import CompletionType, SpanType
from zamlet.tests import test_utils
from zamlet.tests.test_utils import pack_elements, setup_mask_register

logger = logging.getLogger(__name__)


async def run_conditional_simple(clock: Clock, lamlet: Oamlet, vector_length: int, seed: int,
                                 lmul: int, params: ZamletParams):
    """
    Simple conditional test with small arrays.

    Implements: z[i] = (x[i] < 5) ? a[i] : b[i]

    Where:
    - x is int8 array (mask condition)
    - a and b are int16 arrays (data to select from)
    - z is int16 array (output)
    """
    # Generate random test data
    rnd = Random(seed)
    vl = vector_length
    x_list = [rnd.randint(0, 10) for _ in range(vl)]  # int8 values (0-10 to get mix of < 5 and >= 5)
    a_list = [rnd.getrandbits(16) for _ in range(vl)]  # int16 values
    b_list = [rnd.getrandbits(16) for _ in range(vl)]  # int16 values

    # Compute expected result in Python: z[i] = (x[i] < 5) ? a[i] : b[i]
    expected_list = [a_list[i] if x_list[i] < 5 else b_list[i] for i in range(len(x_list))]

    logger.info(f"x_list: {x_list}")
    logger.info(f"a_list: {a_list}")
    logger.info(f"b_list: {b_list}")
    logger.info(f"expected_list: {expected_list}")

    # Convert to binary format for memory operations
    x_data = bytes(x_list)  # int8 -> 1 byte each
    a_data = struct.pack(f'<{len(a_list)}H', *a_list)  # int16 -> 2 bytes each
    b_data = struct.pack(f'<{len(b_list)}H', *b_list)  # int16 -> 2 bytes each
    expected = struct.pack(f'<{len(expected_list)}H', *expected_list)  # int16 -> 2 bytes each

    # Allocate memory regions, spaced by alloc_size to avoid overlap
    page_bytes = params.page_bytes
    max_data_bytes = vl * 2 * lmul
    alloc_size = ((max_data_bytes + page_bytes - 1) // page_bytes) * page_bytes

    x_addr = 0x20000000
    a_addr = 0x20800000
    b_addr = a_addr + alloc_size
    z_addr = 0x90000000

    lamlet.allocate_memory(
        GlobalAddress(bit_addr=x_addr * 8, params=params),
        alloc_size, memory_type=MemoryType.VPU,
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=a_addr * 8, params=params),
        alloc_size, memory_type=MemoryType.VPU,
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=b_addr * 8, params=params),
        alloc_size, memory_type=MemoryType.VPU,
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=z_addr * 8, params=params),
        alloc_size, memory_type=MemoryType.VPU,
    )

    # Write initial data to memory
    x_mem_ordering = Ordering(lamlet.word_order, 8)
    ab_mem_ordering = Ordering(lamlet.word_order, 16)
    await lamlet.set_memory(x_addr, x_data, ordering=x_mem_ordering)
    await lamlet.set_memory(a_addr, a_data, ordering=ab_mem_ordering)
    await lamlet.set_memory(b_addr, b_data, ordering=ab_mem_ordering)

    logger.info("Memory initialized")

    # Now we need to manually construct and send the kinstructions
    # that implement the conditional operation:
    #
    # 1. Load x into v0 (with e8)
    # 2. Compare x < 5 to create mask in v0
    # 3. Load a into v2 (with e16, masked by v0)
    # 4. Invert mask v0
    # 5. Load b into v2 (with e16, masked by inverted v0)
    # 6. Store v2 to z

    # Step 1: Load x into v0 with e8
    logger.info("Step 1: Loading x array (e8) into v0")
    x_global_addr = GlobalAddress(bit_addr=x_addr * 8, params=params)
    x_vpu_addr = lamlet.to_vpu_addr(x_global_addr)

    # Create Load instruction for v0 with e8
    x_ordering = Ordering(lamlet.word_order, 8)

    # We need to manually create kinstructions for each kamlet
    # In the real system, lamlet.vload() would do this, but we're bypassing that

    # For now, let's use the high-level vload to see how it works
    # then we can manually construct the kinstructions

    logger.info("Using lamlet.vload() to load data into registers")

    # Calculate elements per iteration based on lmul
    # With lmul registers grouped as one logical register, for e16 (2 bytes/element):
    # elements_per_iteration = lmul * vline_bytes / 2
    vline_bytes = params.vline_bytes
    elements_per_iteration = (lmul * vline_bytes) // 2  # for e16
    logger.info(f"lmul={lmul}, vline_bytes={vline_bytes}, elements_per_iteration={elements_per_iteration}")

    a_ordering = Ordering(lamlet.word_order, 16)
    b_ordering = Ordering(lamlet.word_order, 16)
    z_ordering = Ordering(lamlet.word_order, 16)

    for iter_start in range(0, vl, elements_per_iteration):
        iter_count = min(elements_per_iteration, vl - iter_start)
        logger.info(f"Iteration: elements {iter_start} to {iter_start + iter_count - 1}")

        span_id = lamlet.monitor.create_span(
            span_type=SpanType.RISCV_INSTR, component="test",
            completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_iteration")

        # Step 1: Load x into v0 (e8)
        lamlet.vl = iter_count
        lamlet.set_vtype(8, lmul)
        await lamlet.vload(
            vd=0,
            addr=x_addr + iter_start,
            ordering=x_ordering,
            n_elements=iter_count,
            start_index=0,
            mask_reg=None,
            parent_span_id=span_id,
        )

        # Step 2: Create mask (x < 5)
        instr_ident = await lamlet.get_instr_ident()
        vmsle_instr = kinstructions.VCmpViOp(
            op=kinstructions.VCmpOp.LE,
            dst=0,
            src=0,
            simm5=4,
            n_elements=iter_count,
            element_width=8,
            ordering=x_ordering,
            instr_ident=instr_ident,
        )
        await lamlet.add_to_instruction_buffer(vmsle_instr, span_id)
        # Direct-kinstr path bypasses the dispatch class; stamp the ew=1
        # mask ordering that VCmpVi.update_state would normally set.
        lamlet.vrf_ordering[0] = Ordering(lamlet.word_order, 1)

        # Step 3: Load a into v1 (e16, unmasked)
        lamlet.set_vtype(16, lmul)
        await lamlet.vload(
            vd=1,
            addr=a_addr + iter_start * 2,
            ordering=a_ordering,
            n_elements=iter_count,
            start_index=0,
            mask_reg=None,
            parent_span_id=span_id,
        )

        # Step 4: Invert mask
        instr_ident = await lamlet.get_instr_ident()
        vmnand_instr = kinstructions.VmLogicMmOp(
            op=kinstructions.VmLogicOp.NAND,
            dst=0,
            src1=0,
            src2=0,
            start_index=lamlet.vstart,
            n_elements=iter_count,
            word_order=lamlet.word_order,
            instr_ident=instr_ident,
        )
        await lamlet.add_to_instruction_buffer(vmnand_instr, span_id)

        # Step 5: Load b into v1 with inverted mask (only where x >= 5)
        await lamlet.vload(
            vd=1,
            addr=b_addr + iter_start * 2,
            ordering=b_ordering,
            n_elements=iter_count,
            start_index=0,
            mask_reg=0,
            parent_span_id=span_id,
        )

        # Step 6: Store v1 to z
        await lamlet.vstore(
            vs=1,
            addr=z_addr + iter_start * 2,
            ordering=z_ordering,
            n_elements=iter_count,
            start_index=0,
            mask_reg=None,
            parent_span_id=span_id,
        )

    logger.info("All iterations processed")

    # Read back results and verify
    logger.info("Reading results from memory")
    future = await lamlet.get_memory(z_addr, vl * 2)
    await future
    result = future.result()
    logger.info(f"Result: {result.hex()}")
    logger.info(f"Expected: {expected.hex()}")

    # Compare
    if result == expected:
        logger.warning("TEST PASSED: Results match expected values!")
        return 0
    else:
        logger.error("TEST FAILED: Results do not match expected values")
        # Show detailed comparison
        for i in range(vl):
            actual_val = struct.unpack('<H', result[i*2:(i+1)*2])[0]
            expected_val = expected_list[i]
            x_val = x_list[i]
            a_val = a_list[i]
            b_val = b_list[i]
            match = "✓" if actual_val == expected_val else "✗"
            cond = "T" if x_val < 5 else "F"
            logger.error(
                f"  [{i}] x={x_val} (<5?{cond}) a={a_val:5d} b={b_val:5d} -> "
                f"expected={expected_val:5d} actual={actual_val:5d} {match}"
            )
        return 1


def run_test(vector_length: int, seed: int = 0, lmul: int = 4,
             params: ZamletParams = None, dump_spans: bool = False, max_cycles: int = 5000):
    """Helper to run a single test configuration."""
    if params is None:
        params = ZamletParams()

    async def test_fn(clock: Clock, lamlet: Oamlet):
        return await run_conditional_simple(clock, lamlet, vector_length, seed, lmul, params)

    test_utils.run_test(test_fn, params, max_cycles=max_cycles, dump_spans=dump_spans)


def random_test_config(rnd: Random):
    """Generate a random test configuration."""
    geom_name = rnd.choice(list(SMALL_GEOMETRIES.keys()))
    geom_params = SMALL_GEOMETRIES[geom_name]
    vl = rnd.randint(1, 64)
    seed = rnd.randint(0, 10000)
    lmul = rnd.choice([1, 2, 4, 8])
    return geom_name, geom_params, vl, seed, lmul


def generate_test_params(n_tests: int = 128, seed: int = 42):
    """Generate random test parameter combinations."""
    rnd = Random(seed)
    test_params = []
    for i in range(n_tests):
        geom_name, geom_params, vl, test_seed, lmul = random_test_config(rnd)
        id_str = f"{i}_{geom_name}_vl{vl}_seed{test_seed}_lmul{lmul}"
        test_params.append(pytest.param(geom_params, vl, test_seed, lmul, id=id_str))
    return test_params


@pytest.mark.parametrize("params,vl,seed,lmul", generate_test_params(n_tests=scale_n_tests(32)))
def test_conditional(params, vl, seed, lmul):
    run_test(vl, seed, lmul, params=params)


# ---------------------------------------------------------------------------
# Masked vector-compare coverage (VCmpVi / VCmpVv / VCmpVx).
#
# Verifies both unmasked (vm=1) and masked (vm=0) operation:
#   - Unmasked: every element of vd is set to the comparison result.
#   - Masked:   element i of vd is set to the result when v0[i]=1, otherwise
#     the prior vd[i] is preserved (mask-undisturbed semantics under
#     vma=False).
# Reads vd back as a mask register via ew=64 vstore and decodes the bits.

VCMP_TRIALS_PER_FORM = 4
VCMP_FORMS = ('vi', 'vv', 'vx')
VCMP_OPS = (
    kinstructions.VCmpOp.EQ,
    kinstructions.VCmpOp.NE,
    kinstructions.VCmpOp.LT,
    kinstructions.VCmpOp.LE,
    kinstructions.VCmpOp.GT,
    kinstructions.VCmpOp.GE,
)


@dataclass
class _VCmpTrial:
    idx: int
    form: str
    op: kinstructions.VCmpOp
    vl: int
    vm: int
    vs2_vals: list
    vs1_vals: list
    scalar_val: int
    simm5: int
    v0_bits: list
    init_vd_bits: list
    expected: list


def _vcmp_eval(op, a: int, b: int) -> bool:
    if op == kinstructions.VCmpOp.EQ:
        return a == b
    if op == kinstructions.VCmpOp.NE:
        return a != b
    if op == kinstructions.VCmpOp.LT:
        return a < b
    if op == kinstructions.VCmpOp.LE:
        return a <= b
    if op == kinstructions.VCmpOp.GT:
        return a > b
    if op == kinstructions.VCmpOp.GE:
        return a >= b
    raise NotImplementedError(op)


def _vcmp_trial_addrs(trial: _VCmpTrial, page_bytes: int) -> dict:
    base = 0x90000000 + trial.idx * 16 * page_bytes
    return {
        'vs1': base,
        'vs2': base + 2 * page_bytes,
        'v0': base + 4 * page_bytes,
        'vd_init': base + 6 * page_bytes,
        'vd_out': base + 8 * page_bytes,
    }


def _bytes_to_mask_bits(params: ZamletParams, data: bytes) -> list:
    bits = []
    max_bits = params.word_bytes * 8 * params.j_in_l
    for i in range(max_bits):
        jamlet_idx = i % params.j_in_l
        local_bit = i // params.j_in_l
        byte_idx = jamlet_idx * params.word_bytes + local_bit // 8
        bits.append(bool((data[byte_idx] >> (local_bit % 8)) & 1))
    return bits


def _vcmp_expected(trial: _VCmpTrial) -> list:
    expected = list(trial.init_vd_bits)
    for i in range(trial.vl):
        if trial.vm == 0 and not trial.v0_bits[i]:
            continue
        if trial.form == 'vi':
            b = trial.simm5
        elif trial.form == 'vv':
            b = trial.vs1_vals[i]
        else:
            b = trial.scalar_val
        expected[i] = _vcmp_eval(trial.op, trial.vs2_vals[i], b)
    return expected


def _build_vcmp_trials(rnd: Random, params: ZamletParams) -> list:
    max_vl_data = params.vline_bytes  # ew=8, lmul=1
    max_bits = params.word_bytes * 8 * params.j_in_l
    trials = []
    idx = 0
    for form in VCMP_FORMS:
        for _ in range(VCMP_TRIALS_PER_FORM):
            op = rnd.choice(VCMP_OPS)
            vl = rnd.randint(1, max_vl_data)
            vm = rnd.choice([0, 1])
            vs2_vals = [rnd.randint(-128, 127) for _ in range(max_vl_data)]
            vs1_vals = [rnd.randint(-128, 127) for _ in range(max_vl_data)]
            scalar_val = rnd.randint(-128, 127)
            simm5 = rnd.randint(-16, 15)
            v0_bits = [rnd.random() < 0.5 for _ in range(max_bits)]
            init_vd_bits = [rnd.random() < 0.5 for _ in range(max_bits)]
            trial = _VCmpTrial(
                idx=idx, form=form, op=op, vl=vl, vm=vm,
                vs2_vals=vs2_vals, vs1_vals=vs1_vals, scalar_val=scalar_val,
                simm5=simm5, v0_bits=v0_bits, init_vd_bits=init_vd_bits,
                expected=[])
            trial.expected = _vcmp_expected(trial)
            trials.append(trial)
            idx += 1
    return trials


async def _vcmp_alloc_and_write(lamlet, addr: int, vals: list):
    page_bytes = lamlet.params.page_bytes
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=addr * 8, params=lamlet.params),
        page_bytes, memory_type=MemoryType.VPU)
    ordering = Ordering(lamlet.word_order, 8)
    data = pack_elements(vals, 8)
    await lamlet.set_memory(addr, data, ordering=ordering)
    return ordering


async def _vcmp_read_mask(lamlet, reg: int, addr: int, span_id: int) -> list:
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


async def run_vcmp_masked(clock: Clock, lamlet: Oamlet, seed: int,
                          params: ZamletParams):
    rnd = Random(seed)
    trials = _build_vcmp_trials(rnd, params)

    vs1_reg = 2
    vs2_reg = 4
    vd_reg = 6
    rs1 = 5

    lamlet.vstart = 0
    lamlet.pc = 0
    lamlet.vtype = 0  # vsew=0 (ew=8), vlmul=0

    for trial in trials:
        addrs = _vcmp_trial_addrs(trial, params.page_bytes)
        span_id = lamlet.monitor.create_span(
            span_type=SpanType.RISCV_INSTR, component="test",
            completion_type=CompletionType.FIRE_AND_FORGET,
            mnemonic=f"vcmp_trial_{trial.idx}_{trial.form}_{trial.op.value}")

        lamlet.vl = trial.vl

        vs2_ord = await _vcmp_alloc_and_write(lamlet, addrs['vs2'], trial.vs2_vals)
        await lamlet.vload(
            vd=vs2_reg, addr=addrs['vs2'], ordering=vs2_ord,
            n_elements=trial.vl, start_index=0, mask_reg=None,
            parent_span_id=span_id, emul=1)

        if trial.form == 'vv':
            vs1_ord = await _vcmp_alloc_and_write(lamlet, addrs['vs1'], trial.vs1_vals)
            await lamlet.vload(
                vd=vs1_reg, addr=addrs['vs1'], ordering=vs1_ord,
                n_elements=trial.vl, start_index=0, mask_reg=None,
                parent_span_id=span_id, emul=1)
        elif trial.form == 'vx':
            scalar_bytes = trial.scalar_val.to_bytes(8, byteorder='little', signed=True)
            lamlet.scalar.write_reg(rs1, scalar_bytes, span_id)

        await setup_mask_register(
            lamlet, mask_reg=vd_reg, mask_bits=trial.init_vd_bits,
            page_bytes=params.page_bytes, mask_mem_addr=addrs['vd_init'])
        if trial.vm == 0:
            await setup_mask_register(
                lamlet, mask_reg=0, mask_bits=trial.v0_bits,
                page_bytes=params.page_bytes, mask_mem_addr=addrs['v0'])

        if trial.form == 'vi':
            instr = VCmpVi(
                vd=vd_reg, vs2=vs2_reg, simm5=trial.simm5 & 0x1f,
                vm=trial.vm, op=trial.op)
        elif trial.form == 'vv':
            instr = VCmpVv(
                vd=vd_reg, vs2=vs2_reg, vs1=vs1_reg,
                vm=trial.vm, op=trial.op)
        else:
            instr = VCmpVx(
                vd=vd_reg, vs2=vs2_reg, rs1=rs1,
                vm=trial.vm, op=trial.op)
        await instr.update_state(lamlet)
        await lamlet.await_vreg_write_pending(vd_reg, 1)

        actual = await _vcmp_read_mask(lamlet, vd_reg, addrs['vd_out'], span_id)
        lamlet.monitor.finalize_children(span_id)

        errors = [
            i for i in range(trial.vl)
            if actual[i] != trial.expected[i]
        ]
        if errors:
            logger.error(
                f"FAIL trial={trial.idx} form={trial.form} op={trial.op.value} "
                f"vm={trial.vm} vl={trial.vl}: {len(errors)} mismatches")
            for i in errors[:16]:
                if trial.form == 'vi':
                    rhs = trial.simm5
                elif trial.form == 'vv':
                    rhs = trial.vs1_vals[i]
                else:
                    rhs = trial.scalar_val
                logger.error(
                    f"  [{i}] expected={trial.expected[i]} actual={actual[i]} "
                    f"vs2={trial.vs2_vals[i]} rhs={rhs} "
                    f"v0={trial.v0_bits[i]} init={trial.init_vd_bits[i]}")
            return 1

    logger.info(f"PASS: {len(trials)} trials")
    return 0


def _run_vcmp_masked_test(seed: int, params: ZamletParams, max_cycles: int = 200000):
    async def test_fn(clock: Clock, lamlet: Oamlet):
        return await run_vcmp_masked(clock, lamlet, seed, params)
    test_utils.run_test(test_fn, params, max_cycles=max_cycles)


def _generate_vcmp_test_params(n_tests: int = 8, seed: int = 42):
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
    "params,seed", _generate_vcmp_test_params(n_tests=scale_n_tests(8)))
def test_vcmp_masked(params, seed):
    _run_vcmp_masked_test(seed=seed, params=params)


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Test conditional kamlet operations')
    parser.add_argument('--vector-length', '-vl', type=int, default=8,
                        help='Vector length for the test (default: 8)')
    parser.add_argument('--seed', '-s', type=int, default=0,
                        help='Random seed for test data generation (default: 0)')
    parser.add_argument('--lmul', type=int, default=4,
                        help='LMUL - number of registers grouped as one (default: 4)')
    parser.add_argument('--geometry', '-g', default='k2x1_j1x1',
                        help='Geometry name (default: k2x1_j1x1)')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries and exit')
    parser.add_argument('--dump-spans', action='store_true',
                        help='Dump span trees to span_trees.txt')
    parser.add_argument('--max-cycles', type=int, default=5000,
                        help='Maximum simulation cycles (default: 5000)')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    params = get_geometry(args.geometry)
    run_test(vector_length=args.vector_length, seed=args.seed, lmul=args.lmul,
             params=params, dump_spans=args.dump_spans, max_cycles=args.max_cycles)
