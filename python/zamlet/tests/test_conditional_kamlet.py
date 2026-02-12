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

import asyncio
import logging
import struct
from random import Random

import pytest

from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.geometries import SMALL_GEOMETRIES, scale_n_tests
from zamlet.oamlet.oamlet import Oamlet
from zamlet.addresses import GlobalAddress, MemoryType, Ordering, WordOrder, KMAddr, RegAddr
from zamlet.kamlet import kinstructions
from zamlet.kamlet.kinstructions import Load, Store
from zamlet.monitor import CompletionType, SpanType

logger = logging.getLogger(__name__)


async def update(clock, lamlet):
    """Update loop for the lamlet"""
    while True:
        await clock.next_update
        lamlet.update()


async def run_conditional_simple(clock: Clock, vector_length: int, seed: int, lmul: int,
                                 params: ZamletParams):
    """
    Simple conditional test with small arrays.

    Implements: z[i] = (x[i] < 5) ? a[i] : b[i]

    Where:
    - x is int8 array (mask condition)
    - a and b are int16 arrays (data to select from)
    - z is int16 array (output)
    """
    lamlet = Oamlet(clock, params)
    clock.create_task(update(clock, lamlet))
    clock.create_task(lamlet.run())

    await clock.next_cycle

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

    # Allocate memory regions
    # x at 0x20000000 (VPU 8-bit region)
    # a at 0x20800000 (VPU 16-bit region)
    # b at 0x20800010 (VPU 16-bit region, offset by 16 bytes)
    # z at 0x900C0000 (VPU 32-bit pool, will use for results)

    x_addr = 0x20000000
    a_addr = 0x20800000
    b_addr = 0x20801000
    z_addr = 0x900C0000

    # Verify arrays don't overlap
    assert b_addr - a_addr >= vl * 2, f"a and b arrays overlap: need {vl * 2} bytes, have {b_addr - a_addr}"

    lamlet.allocate_memory(
        GlobalAddress(bit_addr=x_addr * 8, params=params),
        1024, memory_type=MemoryType.VPU, ordering=Ordering(WordOrder.STANDARD, 8)
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=a_addr * 8, params=params),
        1024, memory_type=MemoryType.VPU, ordering=Ordering(WordOrder.STANDARD, 16)
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=b_addr * 8, params=params),
        1024, memory_type=MemoryType.VPU, ordering=Ordering(WordOrder.STANDARD, 16)
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=z_addr * 8, params=params),
        1024, memory_type=MemoryType.VPU, ordering=Ordering(WordOrder.STANDARD, 16)
    )

    # Write initial data to memory
    await lamlet.set_memory(x_addr, x_data)
    await lamlet.set_memory(a_addr, a_data)
    await lamlet.set_memory(b_addr, b_data)

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
    x_ordering = Ordering(WordOrder.STANDARD, 8)

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

    a_ordering = Ordering(WordOrder.STANDARD, 16)
    b_ordering = Ordering(WordOrder.STANDARD, 16)
    z_ordering = Ordering(WordOrder.STANDARD, 16)

    for iter_start in range(0, vl, elements_per_iteration):
        iter_count = min(elements_per_iteration, vl - iter_start)
        logger.info(f"Iteration: elements {iter_start} to {iter_start + iter_count - 1}")

        span_id = lamlet.monitor.create_span(
            span_type=SpanType.RISCV_INSTR, component="test",
            completion_type=CompletionType.FIRE_AND_FORGET, mnemonic="test_iteration")

        # Step 1: Load x into v0 (e8)
        lamlet.vl = iter_count
        lamlet.vtype = 0x0  # e8, m1
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
        vmsle_instr = kinstructions.VmsleViOp(
            dst=0,
            src=0,
            simm5=4,
            n_elements=iter_count,
            element_width=8,
            ordering=x_ordering,
            instr_ident=instr_ident,
        )
        await lamlet.add_to_instruction_buffer(vmsle_instr, span_id)

        # Step 3: Load a into v1 (e16, unmasked)
        lamlet.vtype = 0x1  # e16, m1
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
        vmnand_instr = kinstructions.VmnandMmOp(
            dst=0,
            src1=0,
            src2=0,
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


async def main(clock, vector_length: int, seed: int, lmul: int, params: ZamletParams):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)

    clock.register_main()

    clock_driver_task = clock.create_task(clock.clock_driver())
    exit_code = await run_conditional_simple(clock, vector_length, seed, lmul, params)

    logger.warning(f"Test completed with exit_code: {exit_code}")
    clock.running = False

    return exit_code


def run_test(vector_length: int, seed: int = 0, lmul: int = 4,
             params: ZamletParams = None):
    """Helper to run a single test configuration."""
    if params is None:
        params = ZamletParams()
    clock = Clock(max_cycles=5000)
    exit_code = asyncio.run(main(clock, vector_length, seed, lmul, params))
    assert exit_code == 0, f"Test failed with exit_code={exit_code}"


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
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    params = get_geometry(args.geometry)

    level = logging.DEBUG
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    clock = Clock(max_cycles=5000)
    exit_code = None
    try:
        logger.info(f'Starting with vector_length={args.vector_length}, seed={args.seed}, '
                    f'lmul={args.lmul}, geometry={args.geometry}')
        exit_code = asyncio.run(main(clock, args.vector_length, args.seed, args.lmul, params))
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
