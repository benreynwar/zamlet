    .text
    .balign 4
    .global bitreverse_vec

# void bitreverse_vec(size_t n, uint32_t* src, uint32_t* dst, int reverse_bits)
#
# Bit-reverses the lower reverse_bits bits of n values from src,
# preserving upper bits unchanged. Writes results to dst.
#
# Arguments:
#   a0 = n (number of elements)
#   a1 = src (pointer to input array)
#   a2 = dst (pointer to output array)
#   a3 = reverse_bits (number of bits to reverse, 0..32)
#
# Method: mask to lower bits, reverse using only needed swap stages,
# shift to align, recombine with preserved upper bits.

#define count       a0
#define src         a1
#define dst         a2
#define rev_bits    a3
#define shift_amt   a4
#define lower_mask  a5

#define mask_aa     t0
#define mask_cc     t1
#define mask_f0     t2
#define mask_ff00   t3
#define vl_actual   t4

bitreverse_vec:
    # Compute lower_mask: bits [0, reverse_bits) set
    li t5, 32
    beq rev_bits, t5, .Lfull_mask
    li lower_mask, 1
    sll lower_mask, lower_mask, rev_bits
    addi lower_mask, lower_mask, -1
    j .Lmask_done
.Lfull_mask:
    li lower_mask, -1
.Lmask_done:

    # Compute shift_amt = stage_bits - reverse_bits
    # stage_bits = smallest power of 2 >= reverse_bits
    li shift_amt, 1
    bge shift_amt, rev_bits, .Lshift_ready
    li shift_amt, 2
    bge shift_amt, rev_bits, .Lshift_ready
    li shift_amt, 4
    bge shift_amt, rev_bits, .Lshift_ready
    li shift_amt, 8
    bge shift_amt, rev_bits, .Lshift_ready
    li shift_amt, 16
    bge shift_amt, rev_bits, .Lshift_ready
    li shift_amt, 32
.Lshift_ready:
    sub shift_amt, shift_amt, rev_bits

    # Load swap masks (high mask of each pair; complement derived in loop)
    li mask_aa, 0xAAAAAAAA
    li mask_cc, 0xCCCCCCCC
    li mask_f0, 0xF0F0F0F0
    li mask_ff00, 0xFF00FF00

.Lloop:
    beqz count, .Ldone

    vsetvli vl_actual, count, e32, m1, ta, ma

    vle32.v v0, (src)
    vmv.v.v v3, v0              # save original for upper bits
    vand.vx v0, v0, lower_mask  # isolate lower reverse_bits

    # Stage 1: swap adjacent bits (needed if reverse_bits > 1)
    li t5, 1
    ble rev_bits, t5, .Lcombine
    vand.vx v1, v0, mask_aa
    vsrl.vi v1, v1, 1
    xori t6, mask_aa, -1        # t6 = 0x55555555
    vand.vx v2, v0, t6
    vsll.vi v2, v2, 1
    vor.vv v0, v1, v2

    # Stage 2: swap bit pairs (needed if reverse_bits > 2)
    li t5, 2
    ble rev_bits, t5, .Lcombine
    vand.vx v1, v0, mask_cc
    vsrl.vi v1, v1, 2
    xori t6, mask_cc, -1        # t6 = 0x33333333
    vand.vx v2, v0, t6
    vsll.vi v2, v2, 2
    vor.vv v0, v1, v2

    # Stage 3: swap nibbles (needed if reverse_bits > 4)
    li t5, 4
    ble rev_bits, t5, .Lcombine
    vand.vx v1, v0, mask_f0
    vsrl.vi v1, v1, 4
    xori t6, mask_f0, -1        # t6 = 0x0F0F0F0F
    vand.vx v2, v0, t6
    vsll.vi v2, v2, 4
    vor.vv v0, v1, v2

    # Stage 4: swap bytes (needed if reverse_bits > 8)
    li t5, 8
    ble rev_bits, t5, .Lcombine
    vand.vx v1, v0, mask_ff00
    vsrl.vi v1, v1, 8
    xori t6, mask_ff00, -1      # t6 = 0x00FF00FF
    vand.vx v2, v0, t6
    vsll.vi v2, v2, 8
    vor.vv v0, v1, v2

    # Stage 5: swap halfwords (needed if reverse_bits > 16)
    li t5, 16
    ble rev_bits, t5, .Lcombine
    vsrl.vi v1, v0, 16
    vsll.vi v2, v0, 16
    vor.vv v0, v1, v2

.Lcombine:
    # Align reversed bits to lower positions
    vsrl.vx v0, v0, shift_amt

    # Recombine: reversed lower bits + preserved upper bits
    xori t6, lower_mask, -1     # t6 = upper_mask
    vand.vx v3, v3, t6          # keep only upper bits of original
    vor.vv v0, v0, v3           # combine

    vse32.v v0, (dst)

    # Advance pointers
    slli t6, vl_actual, 2
    add src, src, t6
    add dst, dst, t6

    # Decrement count
    sub count, count, vl_actual
    j .Lloop

.Ldone:
    ret
