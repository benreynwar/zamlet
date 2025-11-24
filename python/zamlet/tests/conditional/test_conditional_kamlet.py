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

from runner import Clock
from params import LamletParams
from lamlet import Lamlet
from addresses import GlobalAddress, Ordering, WordOrder, KMAddr, RegAddr
import kinstructions
from kinstructions import Load, Store

logger = logging.getLogger(__name__)


async def update(clock, lamlet):
    """Update loop for the lamlet"""
    while True:
        await clock.next_update
        lamlet.update()


async def test_conditional_simple(clock: Clock):
    """
    Simple conditional test with small arrays.

    Test data:
    x = [0, 3, 1, 3, 1, 1, 8, 2]  (int8)
    a = [454, 564, 989, 350, 64, 584, 140, 6]  (int16)
    b = [833, 1, 749, 572, 949, 216, 621, 572]  (int16)

    Expected result (x[i] < 5 ? a[i] : b[i]):
    z = [454, 564, 989, 350, 64, 584, 621, 572]  (int16)
    """
    params = LamletParams()
    lamlet = Lamlet(clock, params)
    clock.create_task(update(clock, lamlet))

    await clock.next_cycle

    # Test data
    x_data = bytes([0, 3, 1, 3, 1, 1, 8, 2])  # 8 bytes (int8)
    a_data = struct.pack('<8H', 454, 564, 989, 350, 64, 584, 140, 6)  # 16 bytes (int16)
    b_data = struct.pack('<8H', 833, 1, 749, 572, 949, 216, 621, 572)  # 16 bytes (int16)
    expected = struct.pack('<8H', 454, 564, 989, 350, 64, 584, 621, 572)  # 16 bytes (int16)

    logger.info(f"x_data: {x_data.hex()}")
    logger.info(f"a_data: {a_data.hex()}")
    logger.info(f"b_data: {b_data.hex()}")
    logger.info(f"expected: {expected.hex()}")

    # Allocate memory regions
    # x at 0x20000000 (VPU 8-bit region)
    # a at 0x20800000 (VPU 16-bit region)
    # b at 0x20800010 (VPU 16-bit region, offset by 16 bytes)
    # z at 0x900C0000 (VPU 32-bit pool, will use for results)

    x_addr = 0x20000000
    a_addr = 0x20800000
    b_addr = 0x20800010
    z_addr = 0x900C0000

    lamlet.allocate_memory(
        GlobalAddress(bit_addr=x_addr * 8, params=params),
        1024, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 8)
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=a_addr * 8, params=params),
        1024, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 16)
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=b_addr * 8, params=params),
        1024, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 16)
    )
    lamlet.allocate_memory(
        GlobalAddress(bit_addr=z_addr * 8, params=params),
        1024, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 16)
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

    # Vector length for this operation
    vl = 8

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

    # Set up vector configuration
    lamlet.vl = vl
    lamlet.vtype = 0x0  # e8, m1

    # Load x into v0 (register 0)
    logger.info("Loading x into v0...")
    await lamlet.vload(
        vd=0,
        address=x_addr,
        ordering=x_ordering,
        n_bytes=vl,
        masked=False,
        mask_reg=None
    )

    logger.info("x loaded into v0")

    # Step 2: Create mask (x < 5)
    # Use vmsle.vi v0, v0, 4  (which implements x < 5 since vmslt.vi x,5 == vmsle.vi x,4)
    logger.info("Step 2: Creating mask (x < 5) using VmsleViOp")

    # Create the VmsleViOp instruction (x <= 4, which is equivalent to x < 5)
    # This will overwrite v0 with the mask result
    vmsle_instr = kinstructions.VmsleViOp(
        dst=0,  # v0 (will hold mask)
        src=0,  # v0 (current data)
        simm5=4,  # compare with 4 (x <= 4 is same as x < 5)
        n_elements=vl,
        element_width=8,
        ordering=x_ordering,
    )

    # Send instruction to all kamlets
    logger.info("Sending VmsleViOp to instruction buffer")
    await lamlet.add_to_instruction_buffer(vmsle_instr)

    # Expected mask for x = [0, 3, 1, 3, 1, 1, 8, 2]
    # x <= 4: [1, 1, 1, 1, 1, 1, 0, 1]

    # Step 3: Load a into v2 with mask (masked load)
    logger.info("Step 3: Loading a array (e16) into v2 with mask")
    a_ordering = Ordering(WordOrder.STANDARD, 16)
    lamlet.vtype = 0x1  # e16, m1

    await lamlet.vload(
        vd=2,
        address=a_addr,
        ordering=a_ordering,
        n_bytes=vl * 2,  # 8 elements * 2 bytes each
        masked=True,
        mask_reg=0  # Use v0 as mask
    )

    logger.info("a loaded into v2 (masked)")

    # Step 4: Invert mask in v0 using vmnot (implemented as vmnand v0, v0, v0)
    logger.info("Step 4: Inverting mask using VmnandMmOp")

    vmnand_instr = kinstructions.VmnandMmOp(
        dst=0,
        src1=0,
        src2=0,
    )

    await lamlet.add_to_instruction_buffer(vmnand_instr)

    # Step 5: Load b into v2 with inverted mask (masked load)
    logger.info("Step 5: Loading b array (e16) into v2 with inverted mask")
    b_ordering = Ordering(WordOrder.STANDARD, 16)

    await lamlet.vload(
        vd=2,
        address=b_addr,
        ordering=b_ordering,
        n_bytes=vl * 2,  # 8 elements * 2 bytes each
        masked=True,
        mask_reg=0  # Use inverted v0 as mask
    )

    logger.info("b loaded into v2 (masked)")

    # Step 6: Store v2 to z
    logger.info("Step 6: Storing v2 to z")
    z_ordering = Ordering(WordOrder.STANDARD, 16)

    await lamlet.vstore(
        vs=2,
        address=z_addr,
        ordering=z_ordering,
        n_bytes=vl * 2,
        masked=False,
        mask_reg=None
    )

    logger.info("v2 stored to z")

    # Read back results and verify
    logger.info("Reading results from memory")
    result = await lamlet.get_memory(z_addr, vl * 2)
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
            expected_val = struct.unpack('<H', expected[i*2:(i+1)*2])[0]
            match = "✓" if actual_val == expected_val else "✗"
            logger.error(f"  [{i}] actual={actual_val:5d} expected={expected_val:5d} {match}")
        return 1


async def main(clock):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)

    clock.register_main()

    exit_code = await test_conditional_simple(clock)

    logger.warning(f"Test completed with exit_code: {exit_code}")
    clock.running = False

    return exit_code


if __name__ == '__main__':
    import sys

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
        exit_code = asyncio.run(main(clock))
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
