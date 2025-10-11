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


def run(use_physical=False):
    filename = 'vec-sgemv.riscv'
    p_info = program_info.get_program_info(filename)
    
    params = state.Params(
            maxvl_words=16,
            word_width_bytes=8,
            vpu_memory_bytes=1<<20,
            scalar_memory_bytes=1<<20,
            sram_bytes=1<<16,
            n_lanes=4,
            n_vpu_memories=2,
            page_size=1<<10,
            )

    s = state.State(params, use_physical=use_physical)

    s.set_pc(p_info['pc'])

    # Allocate memory for all segments, with extra for scalar regions (stack/heap)
    for segment in p_info['segments']:
        address = segment['address']
        size = len(segment['contents'])
        page_start = address // params.page_size * params.page_size
        page_end = (address + size + params.page_size - 1) // params.page_size * params.page_size

        # Determine if this is VPU memory (0x20000000 for static VPU data, 0x90000000 for pools)
        is_vpu = ((address >= 0x20000000 and address < 0x30000000) or
                  (address >= 0x90000000 and address < 0xa0000000))

        # For scalar memory at 0x10000000, allocate extra for stack/heap (32MB total)
        if address >= 0x10000000 and address < 0x20000000:
            alloc_size = 32 * 1024 * 1024  # 32MB to cover data + stack + heap
        else:
            alloc_size = page_end - page_start

        # For VPU static data at 0x20000000, use element_width=32 (float data)
        ew = 32 if (address >= 0x20000000 and address < 0x30000000) else None
        s.allocate_memory(page_start, alloc_size, is_vpu=is_vpu, element_width=ew)

    # Allocate VPU memory pools with fixed element widths
    # Each pool is 2MB as defined in vpu_alloc.c
    pool_size = 2 * 1024 * 1024
    s.allocate_memory(0x90000000, pool_size, is_vpu=True, element_width=1)   # 1-bit pool (masks)
    s.allocate_memory(0x90200000, pool_size, is_vpu=True, element_width=8)   # 8-bit pool
    s.allocate_memory(0x90400000, pool_size, is_vpu=True, element_width=16)  # 16-bit pool
    s.allocate_memory(0x90600000, pool_size, is_vpu=True, element_width=32)  # 32-bit pool
    s.allocate_memory(0x90800000, pool_size, is_vpu=True, element_width=64)  # 64-bit pool

    for segment in p_info['segments']:
        address = segment['address']
        data = segment['contents']
        s.set_memory(address, data, force_vpu=True)

    trace = disasm_trace.parse_objdump(filename)
    logger.info(f"Loaded {len(trace)} instructions from objdump")

    # Verify data will be in .data.vpu section at 0x20000000
    # The offset is the same as before (~0x400 into the data)
    verify_addr = 0x20000400
    # Results are written to the first allocation from the 32-bit pool at 0x90600000
    results_addr = 0x90600000

    for i in range(10000):
        s.step(disasm_trace=trace)

        if s.exit_code is not None:
            logger.info(f"Program exited with code {s.exit_code}")
            logger.info(f"Final VL register: {s.vl}")
            logger.info(f"Final VTYPE register: {hex(s.vtype)}")

            logger.info("Verifying results from vector register file:")
            verify_results_from_vrf(s, verify_addr)

            logger.info("\nVerifying results from memory:")
            verify_results(s, results_addr, verify_addr)
            break


def read_float_array(state, address, count):
    import struct
    data = state.get_memory(address, count * 4)

    logger.debug(f"Reading {count} floats from {hex(address)}")
    logger.debug(f"First 40 bytes: {bytes(data[:40]).hex()}")

    return [struct.unpack('<f', bytes(data[i*4:(i+1)*4]))[0] for i in range(count)]


def read_float_array_from_vrf(state, vreg_start, count):
    import struct
    floats = []
    vreg = vreg_start
    byte_offset = 0

    for i in range(count):
        vrf_data = state.vpu_logical.vrf[vreg]
        float_bytes = bytes(vrf_data[byte_offset:byte_offset+4])
        floats.append(struct.unpack('<f', float_bytes)[0])

        byte_offset += 4
        if byte_offset >= len(vrf_data):
            vreg += 1
            byte_offset = 0

    return floats


def verify_results_from_vrf(state, verify_addr):
    expected = read_float_array(state, verify_addr, 128)
    logger.info(f"Expected first 10: {expected[:10]}")

    computed = read_float_array_from_vrf(state, 16, 128)
    logger.info(f"VRF v16+ first 10: {computed[:10]}")

    mismatches = [(i, computed[i], expected[i])
                  for i in range(128) if computed[i] != expected[i]]

    if mismatches:
        logger.error("FAILURE: VRF results do not match!")
        for i, comp, exp in mismatches[:10]:
            logger.error(f"  Index {i}: got {comp}, expected {exp}")
    else:
        logger.info("SUCCESS: All 128 VRF results match expected values!")


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

    run(use_physical=False)
