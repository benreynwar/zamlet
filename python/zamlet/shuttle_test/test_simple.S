# Simple RISC-V test program for Shuttle
# Writes a pattern to memory, reads it back, then writes a "done" marker
# Done marker is written to MMIO space (0x60000000) which is uncached

.section .text
.global _start

_start:
    # Write 0xDEADBEEF to address 0x80001000
    li t0, 0x80001000       # target address
    li t1, 0xDEADBEEF       # value to write
    sw t1, 0(t0)            # store word

    # Fence to ensure store is visible
    fence

    # Read it back to verify
    lw t2, 0(t0)            # load word

    # Check if read matches write
    bne t1, t2, fail        # if not equal, jump to fail

    # Success: write 0x1 to done marker at 0x60000000 (MMIO, uncached)
    li t0, 0x60000000
    li t1, 1
    sw t1, 0(t0)
    j done

fail:
    # Failure: write 0xFFFFFFFF to done marker
    li t0, 0x60000000
    li t1, -1
    sw t1, 0(t0)

done:
    # Spin forever
    j done
