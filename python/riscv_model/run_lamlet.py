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


async def run(clock: Clock):
    filename = 'tests/readwritebyte/readwritebyte.riscv'
    p_info = program_info.get_program_info(filename)

    params = LamletParams(
        k_cols=2,
        k_rows=2,
        j_cols=2,
        j_rows=2,
        )

    s = lamlet.Lamlet(clock, params, 4, 4)
    clock.spawn(s.run())

    s.set_pc(p_info['pc'])

    # Allocate memory for all segments, with extra for scalar regions (stack/heap)
    for segment in p_info['segments']:
        address = segment['address']
        size = len(segment['contents'])
        page_start = (address // params.page_bytes) * params.page_bytes
        page_end = (address + size + params.page_bytes - 1) // params.page_bytes * params.page_bytes

        # Determine if this is VPU memory (0x20000000 for static VPU data, 0x90000000 for pools)
        is_vpu = ((address >= 0x20000000 and address < 0x30000000) or
                  (address >= 0x90000000 and address < 0xa0000000))

        # For scalar memory at 0x10000000, allocate extra for stack/heap (2MB total)
        if address >= 0x10000000 and address < 0x20000000:
            alloc_size = 2 * 1024 * 1024  # 2MB to cover data + stack + heap
        else:
            alloc_size = page_end - page_start

        # For VPU static data at 0x20000000, use element_width=32 (float data)
        if is_vpu:
            ew = 32 if (address >= 0x20000000 and address < 0x30000000) else 8
            ordering = Ordering(WordOrder.STANDARD, ew)
        else:
            ordering = None
        s.allocate_memory(GlobalAddress(bit_addr=page_start*8), alloc_size, is_vpu=is_vpu, ordering=ordering)

    # Allocate VPU memory pools with fixed element widths
    # Each pool is 256KB as defined in vpu_alloc.c
    pool_size = 256 * 1024
    s.allocate_memory(GlobalAddress(bit_addr=0x90000000*8), pool_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 1))   # 1-bit pool (masks)
    s.allocate_memory(GlobalAddress(bit_addr=0x90040000*8), pool_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 8))   # 8-bit pool
    s.allocate_memory(GlobalAddress(bit_addr=0x90080000*8), pool_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 16))  # 16-bit pool
    s.allocate_memory(GlobalAddress(bit_addr=0x900C0000*8), pool_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 32))  # 32-bit pool
    s.allocate_memory(GlobalAddress(bit_addr=0x90100000*8), pool_size, is_vpu=True, ordering=Ordering(WordOrder.STANDARD, 64))  # 64-bit pool

    for segment in p_info['segments']:
        address = segment['address']
        data = segment['contents']
        await s.set_memory(address, data)
        logger.info(f'Segment {hex(address)} Size {len(data)} {data}')

    trace = disasm_trace.parse_objdump(filename)
    logger.info(f"Loaded {len(trace)} instructions from objdump")

    # Verify data will be in .data.vpu section at 0x20000000
    # The offset is the same as before (~0x400 into the data)
    verify_addr = 0x20000400
    # Results are written to the first allocation from the 32-bit pool at 0x900C0000
    results_addr = 0x900C0000

    clock.spawn(s.run_instructions(disasm_trace=trace))
    for i in range(10000):

        if s.exit_code is not None:
            logger.info(f"Program exited with code {s.exit_code}")
            logger.info(f"Final VL register: {s.vl}")
            logger.info(f"Final VTYPE register: {hex(s.vtype)}")

            logger.info("Verifying results from vector register file:")
            #verify_results_from_vrf(s, verify_addr)

            logger.info("\nVerifying results from memory:")
            #verify_results(s, results_addr, verify_addr)
            break
        await clock.next_cycle()


async def main():
    clock = Clock(max_cycles=30)
    #clock.spawn(run(clock))
    #await clock.clock_driver()
    clock.spawn(clock.clock_driver())
    await run(clock)


if __name__ == '__main__':
    import sys
    import os
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    root_logger.info('Starting main')

    if os.environ.get('PDB_ON_EXCEPTION'):
        import pdb
        try:
            asyncio.run(main())
        except (AssertionError, Exception) as e:
            import traceback
            traceback.print_exc()
            pdb.post_mortem()
    else:
        asyncio.run(main())
