# Simple RISC-V test program for Shuttle
# Writes a pattern to memory, reads it back, then writes a "done" marker
# Done marker is written to MMIO space (0x60000000) which is uncached
#
# MMIO layout at 0x60000000:
#   +0x00: expected value (what we wrote)
#   +0x08: actual value (what we read back)
#   +0x10: status (1 = success, -1 = failure)

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
    lwu t2, 0(t0)            # load word unsigned

    # Write both values to MMIO for debugging
    li t3, 0x60000000       # MMIO base
    sd t1, 0(t3)            # expected value
    sd t2, 8(t3)            # actual value

    # Check if read matches write
    bne t1, t2, fail        # if not equal, jump to fail

    # Success: write 0x1 to status
    li t4, 1
    sd t4, 16(t3)
    j done

fail:
    # Failure: write 0xFFFFFFFF to status
    li t4, -1
    sd t4, 16(t3)

done:
    # Spin forever
    j done
