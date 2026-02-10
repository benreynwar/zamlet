    .text
    .balign 4
    .global bitreverse_reorder64

# void bitreverse_reorder64(size_t n, const int64_t* src, int64_t* dst,
#                           const uint32_t* read_idx, const uint32_t* write_idx)
#
# Performs bit-reversal reordering of 64-bit elements using precomputed 32-bit indices.
# dst[write_idx[i]] = src[read_idx[i]] for all i in [0, n)
#
# Arguments:
#   a0 = n (number of elements)
#   a1 = src (source array, 64-bit elements)
#   a2 = dst (destination array, 64-bit elements)
#   a3 = read_idx (precomputed read indices, uint32_t element indices)
#   a4 = write_idx (precomputed write indices, uint32_t element indices)

bitreverse_reorder64:
    beqz a0, .Ldone64
    .insn i 0x0b, 0, x0, x0, 11    # set_index_bound 11 (indices bounded to 2^11 bytes)
    .insn i 0x0b, 1, x0, x0, 0     # begin_writeset

.Lloop64:
    # Set vl for 64-bit data width (determines elements per iteration)
    vsetvli t0, a0, e64, m1, ta, ma

    # Switch to e32 for index manipulation (vl stays the same since vlmax_e32 >= t0)
    vsetvli zero, t0, e32, m1, ta, ma

    # Load 32-bit read and write byte offsets (pre-scaled in C)
    vle32.v v0, (a3)         # v0 = read byte offsets
    vle32.v v1, (a4)         # v1 = write byte offsets

    # Switch to e64 for data gather/scatter
    vsetvli zero, t0, e64, m1, ta, ma

    # Gather 64-bit elements from src using 32-bit offsets
    vluxei32.v v2, (a1), v0  # v2 = src[read_idx[i]]

    # Scatter 64-bit elements to dst using 32-bit offsets
    vsuxei32.v v2, (a2), v1  # dst[write_idx[i]] = v2

    # Advance index pointers (4 bytes per uint32_t index)
    slli t1, t0, 2
    add a3, a3, t1
    add a4, a4, t1

    # Decrement count
    sub a0, a0, t0
    bnez a0, .Lloop64
    .insn i 0x0b, 2, x0, x0, 0     # end_writeset
    .insn i 0x0b, 0, x0, x0, 0     # set_index_bound 0 (disable)

.Ldone64:
    ret
