# Loop test for Shuttle
# Writes values 0-7 to an array, reads them back, sums them
# Expected sum: 0+1+2+3+4+5+6+7 = 28
#
# MMIO layout at 0x60000000:
#   +0x00: expected value (28)
#   +0x08: actual value (computed sum)
#   +0x10: status (1 = success, -1 = failure)

.section .text
.global _start

_start:
    li t0, 0x80001000       # array base address
    li t1, 0                # loop counter / value to write
    li t2, 8                # loop limit

write_loop:
    sd t1, 0(t0)            # store counter value to array
    addi t0, t0, 8          # advance pointer
    addi t1, t1, 1          # increment counter
    blt t1, t2, write_loop  # loop while counter < 8

    fence                   # ensure stores are visible

    # Read back and sum
    li t0, 0x80001000       # reset array pointer
    li t1, 0                # loop counter
    li t3, 0                # sum accumulator

read_loop:
    ld t4, 0(t0)            # load value from array
    add t3, t3, t4          # add to sum
    addi t0, t0, 8          # advance pointer
    addi t1, t1, 1          # increment counter
    blt t1, t2, read_loop   # loop while counter < 8

    # Write results to MMIO
    li t0, 0x60000000       # MMIO base
    li t1, 28               # expected sum
    sd t1, 0(t0)            # write expected
    sd t3, 8(t0)            # write actual sum

    # Check if sum matches expected
    li t1, 28
    bne t3, t1, fail

    # Success
    li t4, 1
    sd t4, 16(t0)
    j done

fail:
    li t4, -1
    sd t4, 16(t0)

done:
    j done
