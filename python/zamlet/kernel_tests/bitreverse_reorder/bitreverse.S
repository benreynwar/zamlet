    .text
    .balign 4
    .global bitreverse_vec

# void bitreverse_vec(size_t n, uint32_t* src, uint32_t* dst, int clog2_n)
#
# Bit-reverses n values from src and writes to dst.
# Each value is treated as a clog2_n-bit number.
#
# Arguments:
#   a0 = n (number of elements)
#   a1 = src (pointer to input array)
#   a2 = dst (pointer to output array)
#   a3 = clog2_n (number of bits to reverse, max 8)
#
# Method: reverse 8 bits, then shift right by (8 - clog2_n)

#define count       a0
#define src         a1
#define dst         a2
#define clog2_n     a3
#define shift_amt   a4

#define mask_aa     t0
#define mask_55     t1
#define mask_cc     t2
#define mask_33     t3
#define mask_f0     t4
#define vl_actual   t5

bitreverse_vec:
    # Compute shift amount = 8 - clog2_n
    li shift_amt, 8
    sub shift_amt, shift_amt, clog2_n

    # Load bit-reverse masks
    li mask_aa, 0xAA
    li mask_55, 0x55
    li mask_cc, 0xCC
    li mask_33, 0x33
    li mask_f0, 0xF0

loop:
    beqz count, done

    # Set vector length
    vsetvli vl_actual, count, e32, m1, ta, ma

    # Load values
    vle32.v v0, (src)

    # Stage 1: swap adjacent bits
    # x = ((x & 0xAA) >> 1) | ((x & 0x55) << 1)
    vand.vx v1, v0, mask_aa
    vsrl.vi v1, v1, 1
    vand.vx v2, v0, mask_55
    vsll.vi v2, v2, 1
    vor.vv v0, v1, v2

    # Stage 2: swap bit pairs
    # x = ((x & 0xCC) >> 2) | ((x & 0x33) << 2)
    vand.vx v1, v0, mask_cc
    vsrl.vi v1, v1, 2
    vand.vx v2, v0, mask_33
    vsll.vi v2, v2, 2
    vor.vv v0, v1, v2

    # Stage 3: swap nibbles
    # x = ((x & 0xF0) >> 4) | ((x & 0x0F) << 4)
    vand.vx v1, v0, mask_f0
    vsrl.vi v1, v1, 4
    vand.vi v2, v0, 0x0F
    vsll.vi v2, v2, 4
    vor.vv v0, v1, v2

    # Shift right by (8 - clog2_n) to get correct bit width
    vsrl.vx v0, v0, shift_amt

    # Store results
    vse32.v v0, (dst)

    # Advance pointers
    slli t6, vl_actual, 2
    add src, src, t6
    add dst, dst, t6

    # Decrement count
    sub count, count, vl_actual
    j loop

done:
    ret
