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

.Lloop64:
    # Set vl for 64-bit data width (determines elements per iteration)
    vsetvli t0, a0, e64, m1, ta, ma

    # Switch to e32 for index manipulation (vl stays the same since vlmax_e32 >= t0)
    vsetvli zero, t0, e32, m1, ta, ma

    # Load 32-bit read and write indices
    vle32.v v0, (a3)         # v0 = read element indices
    vle32.v v1, (a4)         # v1 = write element indices

    # Convert element indices to byte offsets (*8 for 64-bit data)
    vsll.vi v0, v0, 3        # v0 = read byte offsets
    vsll.vi v1, v1, 3        # v1 = write byte offsets

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

.Ldone64:
    ret
