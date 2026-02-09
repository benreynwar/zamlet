    .text
    .balign 4
    .global bitreverse_reorder

# void bitreverse_reorder(size_t n, const int32_t* src, int32_t* dst,
#                         const uint32_t* read_idx, const uint32_t* write_idx,
#                         size_t reps)
#
# Performs bit-reversal reordering using precomputed indices.
# dst[write_idx[i]] = src[read_idx[i]] for all i in [0, n)
# Repeated reps times.  Requires n == 8 * vlmax.
#
# Arguments:
#   a0 = n (number of elements, must equal 8 * vlmax)
#   a1 = src (source array)
#   a2 = dst (destination array)
#   a3 = read_idx (precomputed read byte offsets)
#   a4 = write_idx (precomputed write byte offsets)
#   a5 = reps (number of repetitions)
#
# Unrolled 8x with separate index and data registers to avoid contention.
# Data: v2-v9, Read indices: v10-v17, Write indices: v18-v25.

bitreverse_reorder:
    beqz a0, .Ldone
    .insn i 0x0b, 0, x0, x0, 10    # set_index_bound 10 (indices bounded to 2^10 bytes)
    .insn i 0x0b, 1, x0, x0, 0     # begin_writeset

    # Compute vlmax for e32,m1
    li t2, -1
    vsetvli t2, t2, e32, m1, ta, ma # t2 = vlmax

    # Set vl = vlmax, compute index pointer stride
    vsetvli t0, t2, e32, m1, ta, ma
    slli t1, t0, 2                  # t1 = vl * 4 (bytes per index batch)

    # Load indices (constant across reps)

    vle32.v v10, (a3)
    add a3, a3, t1
    vle32.v v11, (a3)
    add a3, a3, t1
    vle32.v v12, (a3)
    add a3, a3, t1
    vle32.v v13, (a3)
    add a3, a3, t1
    vle32.v v14, (a3)
    add a3, a3, t1
    vle32.v v15, (a3)
    add a3, a3, t1
    vle32.v v16, (a3)
    add a3, a3, t1
    vle32.v v17, (a3)

    vle32.v v18, (a4)
    add a4, a4, t1
    vle32.v v19, (a4)
    add a4, a4, t1
    vle32.v v20, (a4)
    add a4, a4, t1
    vle32.v v21, (a4)
    add a4, a4, t1
    vle32.v v22, (a4)
    add a4, a4, t1
    vle32.v v23, (a4)
    add a4, a4, t1
    vle32.v v24, (a4)
    add a4, a4, t1
    vle32.v v25, (a4)

    # Gather/scatter loop (repeated reps times)

.Lrep:
    beqz a5, .Lend

    vluxei32.v v2, (a1), v10
    vluxei32.v v3, (a1), v11
    vluxei32.v v4, (a1), v12
    vluxei32.v v5, (a1), v13
    vluxei32.v v6, (a1), v14
    vluxei32.v v7, (a1), v15
    vluxei32.v v8, (a1), v16
    vluxei32.v v9, (a1), v17

    vsuxei32.v v2, (a2), v18
    vsuxei32.v v3, (a2), v19
    vsuxei32.v v4, (a2), v20
    vsuxei32.v v5, (a2), v21
    vsuxei32.v v6, (a2), v22
    vsuxei32.v v7, (a2), v23
    vsuxei32.v v8, (a2), v24
    vsuxei32.v v9, (a2), v25

    addi a5, a5, -1
    bnez a5, .Lrep

.Lend:
    .insn i 0x0b, 2, x0, x0, 0     # end_writeset
    .insn i 0x0b, 0, x0, x0, 0     # set_index_bound 0 (disable)

.Ldone:
    ret
