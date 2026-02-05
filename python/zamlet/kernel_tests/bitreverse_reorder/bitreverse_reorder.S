    .text
    .balign 4
    .global bitreverse_reorder

# void bitreverse_reorder(size_t n, const int32_t* src, int32_t* dst,
#                         const uint32_t* read_idx, const uint32_t* write_idx)
#
# Performs bit-reversal reordering using precomputed indices.
# dst[write_idx[i]] = src[read_idx[i]] for all i in [0, n)
#
# Arguments:
#   a0 = n (number of elements)
#   a1 = src (source array)
#   a2 = dst (destination array)
#   a3 = read_idx (precomputed read indices, element indices not byte offsets)
#   a4 = write_idx (precomputed write indices, element indices not byte offsets)

bitreverse_reorder:
    beqz a0, .Ldone

.Lloop:
    vsetvli t0, a0, e32, m1, ta, ma

    # Load read and write indices
    vle32.v v0, (a3)         # v0 = read element indices
    vle32.v v1, (a4)         # v1 = write element indices

    # Convert to byte offsets (*4)
    vsll.vi v0, v0, 2        # v0 = read byte offsets
    vsll.vi v1, v1, 2        # v1 = write byte offsets

    # Gather from src
    vluxei32.v v2, (a1), v0  # v2 = src[read_idx[i]]

    # Scatter to dst
    vsuxei32.v v2, (a2), v1  # dst[write_idx[i]] = v2

    # Advance index pointers
    slli t1, t0, 2
    add a3, a3, t1
    add a4, a4, t1

    # Decrement count
    sub a0, a0, t0
    bnez a0, .Lloop

.Ldone:
    ret
