# This test should follow saturn-vectors/benchmarks/vec-sgemv

# We start off with the data stored in the program memory (this is a DRAM attached to the scalar processor)

# We have a table in hardware (eventually should integrated with TLB), that says if a page has a special
# formatting.  By default all pages are in the scalar processor DRAM.  But by adding them to this page
# We can map them to the VPU memory.  We also specify the element_width and number of lanes when mapping them
# (this determines their layout).

# So we need to add some stuff to the benchmark.  It should
# 1) Say that a page (or pages) should be put on the VPU memory using element_width=32 since we're using floats.
# 2) Copy the data from the scalar memory to the VPU memory.

import program_info
import state
import disasm_trace
import logging


logger = logging.getLogger(__name__)


def run():
    filename = 'vec-sgemv.riscv'
    p_info = program_info.get_program_info(filename)
    
    params = state.Params(
            maxvl_words=16,
            word_width_bytes=8,
            vpu_memory_bytes=1<<20,
            scalar_memory_bytes=1<<20,
            sram_bytes=1<<16,
            n_lanes=4,
            page_size=1<<10,
            )

    s = state.State(params)

    s.set_pc(p_info['pc'])

    scalar_start = 0x80000000
    vpu_start = 0x90000000
    scalar_min = None
    scalar_max = None
    vpu_min = None
    vpu_max = None
    for segment in p_info['segments']:
        address = segment['address']
        data = segment['contents']
        if (address >= scalar_start) and (address < vpu_start):
            assert address + len(data) < vpu_start
            if scalar_min is None:
                scalar_min = address
            else:
                scalar_min = min(scalar_min, address)
            if scalar_max is None:
                scalar_max = address + len(data)
            else:
                scalar_max = max(scalar_max, address + len(data))
        else:
            assert address >= vpu_start
            if vpu_min is None:
                vpu_min = address
            else:
                vpu_min = min(vpu_min, address)
            if vpu_max is None:
                vpu_max = address + len(data)
            else:
                vpu_max = max(vpu_max, address + len(data))

        
    scalar_page_start = scalar_min//params.page_size
    scalar_page_end = (scalar_max + params.page_size-1)//params.page_size
    vpu_page_start = vpu_min//params.page_size
    vpu_page_end = (vpu_max + params.page_size-1)//params.page_size

    s.allocate_memory(scalar_page_start * params.page_size, (scalar_page_end - scalar_page_start) * params.page_size, is_vpu=False, element_width=None)

    # Allocate VPU memory including data segments + stack space
    # The stack is placed right after the VPU data (see crt.S), so allocate extra space
    vpu_stack_size = 256 * 1024  # 256KB for stack (128KB per hart + margin)
    vpu_total_size = (vpu_page_end - vpu_page_start) * params.page_size + vpu_stack_size
    s.allocate_memory(vpu_page_start * params.page_size, vpu_total_size, is_vpu=True, element_width=32)

    # Allocate stack memory at top of address space
    stack_size = 64 * 1024  # 64KB stack
    stack_start = (2**64 - stack_size) // params.page_size * params.page_size
    s.allocate_memory(stack_start, stack_size, is_vpu=False, element_width=None)

    for segment in p_info['segments']:
        address = segment['address']
        data = segment['contents']
        s.set_memory(address, data)

    trace = disasm_trace.parse_objdump(filename)
    logger.info(f"Loaded {len(trace)} instructions from objdump")

    results_addr = None
    verify_addr = 0x90000400
    vec_sgemv_call_pc = 0x800028ae

    for i in range(10000):
        if s.pc == vec_sgemv_call_pc and results_addr is None:
            results_addr = s.scalar.read_reg(14)
            logger.info(f"Results pointer: {hex(results_addr)}")

        s.step(disasm_trace=trace)

        if s.exit_code is not None:
            logger.info(f"Program exited with code {s.exit_code}")
            verify_results(s, results_addr, verify_addr)
            break


def read_float_array(state, address, count):
    import struct
    data = state.get_memory(address, count * 4)
    return [struct.unpack('<f', bytes(data[i*4:(i+1)*4]))[0] for i in range(count)]


def verify_results(state, results_addr, verify_addr):
    import struct

    expected = read_float_array(state, verify_addr, 128)
    logger.info(f"Expected first 10: {expected[:10]}")

    if not results_addr:
        logger.warning("Results address not captured")
        return

    computed = read_float_array(state, results_addr, 128)
    logger.info(f"Computed first 10: {computed[:10]}")

    mismatches = [(i, computed[i], expected[i])
                  for i in range(128) if computed[i] != expected[i]]

    if mismatches:
        logger.error("FAILURE: Results do not match!")
        for i, comp, exp in mismatches[:10]:
            logger.error(f"  Index {i}: got {comp}, expected {exp}")
    else:
        logger.info("SUCCESS: All 128 results match expected values!")


if __name__ == '__main__':
    import sys
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    root_logger.debug('Starting main')

    run()
