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
#   a3 = clog2_n (number of bits to reverse, max 32)
#
# Method: reverse all 32 bits, then shift right by (32 - clog2_n)

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
#define mask_0f     a3
#define mask_ff00   a5
#define mask_00ff   a6

bitreverse_vec:
    # Compute shift amount = 32 - clog2_n
    li shift_amt, 32
    sub shift_amt, shift_amt, clog2_n

    # Load bit-reverse masks (32-bit patterns)
    li mask_aa, 0xAAAAAAAA
    li mask_55, 0x55555555
    li mask_cc, 0xCCCCCCCC
    li mask_33, 0x33333333
    li mask_f0, 0xF0F0F0F0
    li mask_0f, 0x0F0F0F0F
    li mask_ff00, 0xFF00FF00
    li mask_00ff, 0x00FF00FF

loop:
    beqz count, done

    # Set vector length
    vsetvli vl_actual, count, e32, m1, ta, ma

    # Load values
    vle32.v v0, (src)

    # Stage 1: swap adjacent bits
    # x = ((x & 0xAAAAAAAA) >> 1) | ((x & 0x55555555) << 1)
    vand.vx v1, v0, mask_aa
    vsrl.vi v1, v1, 1
    vand.vx v2, v0, mask_55
    vsll.vi v2, v2, 1
    vor.vv v0, v1, v2

    # Stage 2: swap bit pairs
    # x = ((x & 0xCCCCCCCC) >> 2) | ((x & 0x33333333) << 2)
    vand.vx v1, v0, mask_cc
    vsrl.vi v1, v1, 2
    vand.vx v2, v0, mask_33
    vsll.vi v2, v2, 2
    vor.vv v0, v1, v2

    # Stage 3: swap nibbles
    # x = ((x & 0xF0F0F0F0) >> 4) | ((x & 0x0F0F0F0F) << 4)
    vand.vx v1, v0, mask_f0
    vsrl.vi v1, v1, 4
    vand.vx v2, v0, mask_0f
    vsll.vi v2, v2, 4
    vor.vv v0, v1, v2

    # Stage 4: swap bytes within halfwords
    # x = ((x & 0xFF00FF00) >> 8) | ((x & 0x00FF00FF) << 8)
    vand.vx v1, v0, mask_ff00
    vsrl.vi v1, v1, 8
    vand.vx v2, v0, mask_00ff
    vsll.vi v2, v2, 8
    vor.vv v0, v1, v2

    # Stage 5: swap halfwords
    # x = (x >> 16) | (x << 16)
    vsrl.vi v1, v0, 16
    vsll.vi v2, v0, 16
    vor.vv v0, v1, v2

    # Shift right by (32 - clog2_n) to get correct bit width
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
