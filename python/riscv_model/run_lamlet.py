import asyncio
import logging
import struct

import disasm_trace
import program_info
import lamlet
from runner import Clock
from params import LamletParams
from addresses import GlobalAddress, Ordering, WordOrder

logger = logging.getLogger(__name__)


async def update(clock, lamlet):
    while True:
        await clock.next_update
        lamlet.update()


async def run(clock: Clock, filename):
    p_info = program_info.get_program_info(filename)

    params = LamletParams()

    s = lamlet.Lamlet(clock, params)
    clock.create_task(update(clock, s))
    clock.create_task(s.run())
    await clock.next_cycle

    s.set_pc(p_info['pc'])

    # Allocate memory for all segments, with extra for scalar regions (stack/heap)
    for segment in p_info['segments']:
        address = segment['address']
        size = len(segment['contents'])
        page_start = (address // params.page_bytes) * params.page_bytes
        page_end = (address + size + params.page_bytes - 1) // params.page_bytes * params.page_bytes

        # Determine if this is VPU memory
        # 0x20000000-0x207FFFFF: .data.vpu8 (8-bit static data)
        # 0x20800000-0x20FFFFFF: .data.vpu16 (16-bit static data)
        # 0x21000000-0x217FFFFF: .data.vpu32 (32-bit static data)
        # 0x21800000-0x21FFFFFF: .data.vpu64 (64-bit static data)
        # 0x90000000-0x9FFFFFFF: VPU dynamic allocation pools
        is_vpu = ((address >= 0x20000000 and address < 0x22000000) or
                  (address >= 0x90000000 and address < 0xa0000000))

        # For scalar memory at 0x10000000, allocate extra for stack/heap (2MB total)
        if address >= 0x10000000 and address < 0x20000000:
            alloc_size = 2 * 1024 * 1024  # 2MB to cover data + stack + heap
        else:
            alloc_size = page_end - page_start

        # Determine element width based on memory region
        if is_vpu:
            if address >= 0x20000000 and address < 0x20800000:
                ew = 8   # .data.vpu8
            elif address >= 0x20800000 and address < 0x21000000:
                ew = 16  # .data.vpu16
            elif address >= 0x21000000 and address < 0x21800000:
                ew = 32  # .data.vpu32
            elif address >= 0x21800000 and address < 0x22000000:
                ew = 64  # .data.vpu64
            else:
                ew = 8   # Dynamic pools (will be overridden below)
            ordering = Ordering(WordOrder.STANDARD, ew)
        else:
            ordering = None
        logger.warning(
            f'[ALLOC] addr=0x{address:x} size={size} page_start=0x{page_start:x} '
            f'alloc_size={alloc_size} is_vpu={is_vpu} ordering={ordering}'
        )
        s.allocate_memory(GlobalAddress(bit_addr=page_start*8, params=params),
                          alloc_size, is_vpu=is_vpu, ordering=ordering)

    # Allocate VPU memory pools with fixed element widths
    # Each pool is 256KB as defined in vpu_alloc.c
    pool_size = 256 * 1024
    s.allocate_memory(GlobalAddress(bit_addr=0x90000000*8, params=params), pool_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 1))   # 1-bit pool (masks)
    s.allocate_memory(GlobalAddress(bit_addr=0x90040000*8, params=params), pool_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 8))   # 8-bit pool
    s.allocate_memory(GlobalAddress(bit_addr=0x90080000*8, params=params), pool_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 16))  # 16-bit pool
    s.allocate_memory(GlobalAddress(bit_addr=0x900C0000*8, params=params), pool_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 32))  # 32-bit pool
    s.allocate_memory(GlobalAddress(bit_addr=0x90100000*8, params=params), pool_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 64))  # 64-bit pool

    for segment in p_info['segments']:
        address = segment['address']
        data = segment['contents']
        logger.warning(f'[MEM_INIT] Segment addr=0x{address:x} size={len(data)} bytes')
        await s.set_memory(address, data)
        logger.warning(f'[MEM_INIT] Segment addr=0x{address:x} complete')

    trace = disasm_trace.parse_objdump(filename)
    logger.info(f"Loaded {len(trace)} instructions from objdump")

    # Verify data will be in .data.vpu section at 0x20000000
    # The offset is the same as before (~0x400 into the data)
    verify_addr = 0x20000400
    # Results are written to the first allocation from the 32-bit pool at 0x900C0000
    results_addr = 0x900C0000

    clock.create_task(s.run_instructions(disasm_trace=trace))
    while clock.running:
        if s.exit_code is not None:
            logger.warning(f"Program exited with code {s.exit_code}")
            logger.info(f"Final VL register: {s.vl}")
            logger.info(f"Final VTYPE register: {hex(s.vtype)}")

            logger.info("Verifying results from vector register file:")
            #verify_results_from_vrf(s, verify_addr)

            logger.info("\nVerifying results from memory:")
            #verify_results(s, results_addr, verify_addr)

            # Signal clock to stop gracefully
            clock.running = False
            logger.warning(f"run() about to return exit_code={s.exit_code}")
            return s.exit_code
        await clock.next_cycle
    logger.warning(f"run() exiting with clock.running=False, exit_code={s.exit_code}")
    return None



async def main(clock, filename):
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)

    clock.register_main()
    run_task = clock.create_task(run(clock, filename))
    clock_driver_task = clock.create_task(clock.clock_driver())

    # Wait for run_task to complete - it will set clock.running = False
    await run_task
    exit_code = run_task.result()
    logger.warning(f"run_task completed with exit_code: {exit_code}")

    # Now wait for clock_driver to finish naturally
    await clock_driver_task
    logger.warning(f"clock_driver_task completed")

    return exit_code


if __name__ == '__main__':
    level = logging.DEBUG
    import sys
    import os
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Check if a file was provided as argument
    if len(sys.argv) > 1:
        filenames = [sys.argv[1]]
    else:
        filenames = [
           #'tests/readwritebyte/should_fail.riscv',
           #'tests/readwritebyte/simple_vpu_test.riscv',
           #'tests/readwritebyte/write_then_read_many_bytes.riscv',
           #'tests/sgemv/vec-sgemv-large.riscv', (too small)
           #'tests/sgemv/vec-sgemv-64x64.riscv',
           # #'tests/sgemv/vec-sgemv.riscv',  (too small) (it tries to step through rows in a matrix but one row is less than vline so it gets misaligned)
           #'tests/vecadd/vec-add-evict.riscv',
           #'tests/vecadd/vec-add.riscv',
           #'tests/daxpy/vec-daxpy.riscv',
           #'tests/daxpy/vec-daxpy-small.riscv',
           'tests/conditional/vec-conditional.riscv',
           #'tests/conditional/vec-conditional-tiny.riscv',
        ]

    for filename in filenames:
        root_logger.warning(f'========== Starting test: {filename} ==========')
        clock = Clock(max_cycles=20000)
        exit_code = None
        try:
            exit_code = asyncio.run(main(clock, filename))
        except KeyboardInterrupt:
            root_logger.warning(f'========== Test interrupted by user ==========')
            sys.exit(1)
        except asyncio.CancelledError:
            # This happens when clock.stop() cancels tasks - it's normal
            pass
        except Exception as e:
            root_logger.error(f'========== Test FAILED: {filename} - {e} ==========')
            import traceback
            traceback.print_exc()
            continue

        # Log result based on exit code
        if exit_code is not None:
            if exit_code == 0:
                root_logger.warning(f'========== Test PASSED: {filename} (exit code: {exit_code}) ==========')
            else:
                root_logger.warning(f'========== Test FAILED: {filename} (exit code: {exit_code}) ==========')
        else:
            root_logger.warning(f'========== Test completed: {filename} (no exit code) ==========')
