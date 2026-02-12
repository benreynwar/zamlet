import asyncio
import logging
import struct

from zamlet import disasm_trace
from zamlet import program_info
from zamlet.oamlet import oamlet
from zamlet.runner import Clock
from zamlet.params import ZamletParams
from zamlet.addresses import GlobalAddress, MemoryType, Ordering, WordOrder

logger = logging.getLogger(__name__)


async def update(clock, lamlet):
    while True:
        await clock.next_update
        lamlet.update()


def write_span_trees(lam):
    """Write span trees to file for debugging."""
    with open('span_trees.txt', 'w') as f:
        for span in lam.monitor.spans.values():
            if span.parent is None:
                f.write(lam.monitor.format_span_tree(span.span_id, max_depth=20))
                f.write('\n\n')
    logger.info("Span trees written to span_trees.txt")


async def run(clock: Clock, filename, params: ZamletParams = None,
              word_order: WordOrder = WordOrder.STANDARD,
              symbol_values: dict = None):
    p_info = program_info.get_program_info(filename)

    if params is None:
        params = ZamletParams()

    s = oamlet.Oamlet(clock, params, word_order=word_order)
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
            ordering = Ordering(word_order, ew)
        else:
            ordering = None
        memory_type = MemoryType.VPU if is_vpu else MemoryType.SCALAR_IDEMPOTENT
        logger.info(
            f'[ALLOC] addr=0x{address:x} size={size} page_start=0x{page_start:x} '
            f'alloc_size={alloc_size} memory_type={memory_type} ordering={ordering}'
        )
        s.allocate_memory(GlobalAddress(bit_addr=page_start*8, params=params),
                          alloc_size, memory_type=memory_type, ordering=ordering)

    # Allocate VPU memory pools with fixed element widths
    # Each pool is 256KB as defined in vpu_alloc.c
    pool_size = 256 * 1024
    s.allocate_memory(GlobalAddress(bit_addr=0x90000000*8, params=params), pool_size, memory_type=MemoryType.VPU, ordering=Ordering(word_order, 1))   # 1-bit pool (masks)
    s.allocate_memory(GlobalAddress(bit_addr=0x90040000*8, params=params), pool_size, memory_type=MemoryType.VPU, ordering=Ordering(word_order, 8))   # 8-bit pool
    s.allocate_memory(GlobalAddress(bit_addr=0x90080000*8, params=params), pool_size, memory_type=MemoryType.VPU, ordering=Ordering(word_order, 16))  # 16-bit pool
    s.allocate_memory(GlobalAddress(bit_addr=0x900C0000*8, params=params), pool_size, memory_type=MemoryType.VPU, ordering=Ordering(word_order, 32))  # 32-bit pool
    s.allocate_memory(GlobalAddress(bit_addr=0x90100000*8, params=params), pool_size, memory_type=MemoryType.VPU, ordering=Ordering(word_order, 64))  # 64-bit pool

    for segment in p_info['segments']:
        address = segment['address']
        data = segment['contents']
        logger.info(f'[MEM_INIT] Segment addr=0x{address:x} size={len(data)} bytes')
        await s.set_memory(address, data)
        logger.info(f'[MEM_INIT] Segment addr=0x{address:x} complete')

    if symbol_values:
        for name, value in symbol_values.items():
            addr = p_info['symbols'][name]
            data = struct.pack('<i', value)
            logger.info(
                f'[SYMBOL] {name} @ 0x{addr:x} = {value}'
            )
            await s.set_memory(addr, data)

    trace = disasm_trace.parse_objdump(filename)
    logger.info(f"Loaded {len(trace)} instructions from objdump")

    # Verify data will be in .data.vpu section at 0x20000000
    # The offset is the same as before (~0x400 into the data)
    verify_addr = 0x20000400
    # Results are written to the first allocation from the 32-bit pool at 0x900C0000
    results_addr = 0x900C0000

    clock.create_task(s.run_instructions(disasm_trace=trace))
    exit_code = 1  # Default to failure
    try:
        while clock.running:
            if s.exit_code is not None:
                logger.info(f"Program exited with code {s.exit_code}")
                logger.info(f"Final VL register: {s.vl}")
                logger.info(f"Final VTYPE register: {hex(s.vtype)}")

                logger.info("Verifying results from vector register file:")
                #verify_results_from_vrf(s, verify_addr)

                logger.info("\nVerifying results from memory:")
                #verify_results(s, results_addr, verify_addr)

                exit_code = s.exit_code

                # Let in-flight operations drain before stopping.
                drain_cycles = 0
                drain_limit = 100000
                while not s.monitor.is_complete():
                    drain_cycles += 1
                    assert drain_cycles <= drain_limit, (
                        f"Monitor still has open spans after"
                        f" {drain_limit} drain cycles"
                    )
                    for _ in range(100):
                        await clock.next_cycle
                    drain_cycles += 99

                clock.running = False
                logger.info(
                    f"run() about to return exit_code={exit_code}"
                )
                break
            await clock.next_cycle
        else:
            logger.info(f"run() exiting with clock.running=False, exit_code={s.exit_code}")
    finally:
        write_span_trees(s)
    return exit_code, s.monitor



async def main(clock, filename, params: ZamletParams = None,
               word_order: WordOrder = WordOrder.STANDARD,
               symbol_values: dict = None) -> int:
    import signal

    def signal_handler(signum, frame):
        clock.stop()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)

    clock.register_main()
    run_task = clock.create_task(
        run(clock, filename, params, word_order, symbol_values))
    clock_driver_task = clock.create_task(clock.clock_driver())

    # Wait for run_task to complete - it will set clock.running = False
    await run_task
    exit_code, monitor = run_task.result()
    logger.info(f"run_task completed with exit_code: {exit_code}")

    # Now wait for clock_driver to finish naturally
    await clock_driver_task
    logger.info(f"clock_driver_task completed")

    return exit_code, monitor


if __name__ == '__main__':
    import argparse
    import sys

    from zamlet.geometries import GEOMETRIES, get_geometry, list_geometries

    parser = argparse.ArgumentParser(description='Run RISC-V binary through oamlet simulator')
    parser.add_argument('filename', nargs='?', help='RISC-V binary to run')
    parser.add_argument('--geometry', '-g', default='k2x1_j1x1',
                        help=f'Geometry name (default: k2x1_j1x1)')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries and exit')
    parser.add_argument('--all-geometries', action='store_true',
                        help='Run with all geometries')
    parser.add_argument('--max-cycles', type=int, default=50000,
                        help='Maximum simulation cycles (default: 50000)')
    parser.add_argument('--log-level', default='WARNING',
                        help='Logging level (DEBUG, INFO, WARNING, ERROR)')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        print(list_geometries())
        sys.exit(0)

    level = getattr(logging, args.log_level.upper())
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    if args.filename:
        filenames = [args.filename]
    else:
        filenames = [
           'kernel_tests/readwritebyte/should_fail.riscv',
           'kernel_tests/readwritebyte/simple_vpu_test.riscv',
           'kernel_tests/readwritebyte/write_then_read_many_bytes.riscv',
           'kernel_tests/sgemv/vec-sgemv-large.riscv',
           'kernel_tests/sgemv/vec-sgemv-64x64.riscv',
           'kernel_tests/sgemv/vec-sgemv.riscv',
           'kernel_tests/vecadd/vec-add-evict.riscv',
           'kernel_tests/vecadd/vec-add.riscv',
           'kernel_tests/daxpy/vec-daxpy.riscv',
           'kernel_tests/daxpy/vec-daxpy-small.riscv',
           'kernel_tests/conditional/vec-conditional.riscv',
           'kernel_tests/conditional/vec-conditional-tiny.riscv',
           'kernel_tests/unaligned/unaligned.riscv',
        ]

    if args.all_geometries:
        geometries = list(GEOMETRIES.items())
    else:
        geometries = [(args.geometry, get_geometry(args.geometry))]

    for filename in filenames:
        for geom_name, params in geometries:
            root_logger.info(f'========== Starting test: {filename} {geom_name} ==========')
            clock = Clock(max_cycles=args.max_cycles)
            exit_code = None
            try:
                exit_code, _monitor = asyncio.run(main(clock, filename, params))
            except KeyboardInterrupt:
                root_logger.warning(f'========== Test interrupted by user ==========')
                sys.exit(1)
            except asyncio.CancelledError:
                exit_code = 1
            except Exception as e:
                root_logger.error(f'========== Test FAILED: {filename} {geom_name} - {e} ==========')
                import traceback
                traceback.print_exc()
                continue

            if exit_code is not None:
                if exit_code == 0:
                    root_logger.warning(f'========== Test PASSED: {filename} {geom_name} ==========')
                else:
                    root_logger.warning(f'========== Test FAILED: {filename} {geom_name} (exit code: {exit_code}) ==========')
                    sys.exit(exit_code)
            else:
                root_logger.info(f'========== Test completed: {filename} {geom_name} (no exit code) ==========')
                sys.exit(1)
