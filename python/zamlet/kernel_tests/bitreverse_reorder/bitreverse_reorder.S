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
    slli t3, t2, 3                  # t3 = 8 * vlmax

    # Set vl = vlmax, compute index pointer stride
    vsetvli t0, t2, e32, m1, ta, ma
    slli t1, t0, 2                  # t1 = vl * 4 (bytes per index batch)

.Lloop8:
    blt a0, t3, .Ltail

    # === LOAD PHASE: load all indices, shift, then gather ===
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
    add a3, a3, t1

    vsll.vi v10, v10, 2
    vsll.vi v11, v11, 2
    vsll.vi v12, v12, 2
    vsll.vi v13, v13, 2
    vsll.vi v14, v14, 2
    vsll.vi v15, v15, 2
    vsll.vi v16, v16, 2
    vsll.vi v17, v17, 2

    vluxei32.v v2, (a1), v10
    vluxei32.v v3, (a1), v11
    vluxei32.v v4, (a1), v12
    vluxei32.v v5, (a1), v13
    vluxei32.v v6, (a1), v14
    vluxei32.v v7, (a1), v15
    vluxei32.v v8, (a1), v16
    vluxei32.v v9, (a1), v17

    # === STORE PHASE: load all write indices, shift, then scatter ===
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
    add a4, a4, t1

    vsll.vi v18, v18, 2
    vsll.vi v19, v19, 2
    vsll.vi v20, v20, 2
    vsll.vi v21, v21, 2
    vsll.vi v22, v22, 2
    vsll.vi v23, v23, 2
    vsll.vi v24, v24, 2
    vsll.vi v25, v25, 2

    vsuxei32.v v2, (a2), v18
    vsuxei32.v v3, (a2), v19
    vsuxei32.v v4, (a2), v20
    vsuxei32.v v5, (a2), v21
    vsuxei32.v v6, (a2), v22
    vsuxei32.v v7, (a2), v23
    vsuxei32.v v8, (a2), v24
    vsuxei32.v v9, (a2), v25

    sub a0, a0, t3
    bnez a0, .Lloop8
    j .Lend

.Ltail:
    beqz a0, .Lend
    vsetvli t0, a0, e32, m1, ta, ma
    slli t1, t0, 2

    vle32.v v10, (a3)
    vle32.v v18, (a4)
    vsll.vi v10, v10, 2
    vsll.vi v18, v18, 2
    vluxei32.v v2, (a1), v10
    vsuxei32.v v2, (a2), v18

    add a3, a3, t1
    add a4, a4, t1
    sub a0, a0, t0
    j .Ltail

.Lend:
    .insn i 0x0b, 2, x0, x0, 0     # end_writeset
    .insn i 0x0b, 0, x0, x0, 0     # set_index_bound 0 (disable)

.Ldone:
    ret
