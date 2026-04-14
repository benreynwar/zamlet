/*
 * void bitreverse_reorder64(size_t n, const int64_t* src, int64_t* dst,
 *                           const uint32_t* read_idx, const uint32_t* write_idx)
 *
 * Bit-reversal reordering of 64-bit elements using precomputed 32-bit byte-offset
 * indices: dst[write_idx[i]] = src[read_idx[i]] for all i in [0, n).
 *
 * Uses RVV intrinsics: vluxei32 for the gather, vsuxei32 for the unordered
 * scatter. The kamlet register rename lets iterations pipeline across the
 * gather/scatter even though every iteration reuses the same architectural
 * destination registers.
 */

#include <stddef.h>
#include <stdint.h>
#include <riscv_vector.h>
#include "zamlet_custom.h"

void bitreverse_reorder64(size_t n,
                          const int64_t* __restrict__ src,
                          int64_t* __restrict__ dst,
                          const uint64_t* __restrict__ read_idx,
                          const uint64_t* __restrict__ write_idx) {
    if (n == 0) return;

    // Bound indexed byte offsets to the minimum range that covers [0, n*8).
    // Lets the lamlet pre-check all pages in that range and skip per-element
    // fault detection. Largest element index is n-1, so the largest byte
    // offset the gather/scatter will use is (n-1)*8 < n*8.
    unsigned bits = 64 - __builtin_clzl((unsigned long)(n * sizeof(int64_t)) - 1UL);
    zamlet_set_index_bound(bits);
    zamlet_begin_writeset();

    for (size_t avl = n; avl > 0; ) {
        size_t vl = __riscv_vsetvl_e64m1(avl);
        vuint64m1_t ri = __riscv_vle64_v_u64m1(read_idx, vl);
        vuint64m1_t wi = __riscv_vle64_v_u64m1(write_idx, vl);
        vint64m1_t data = __riscv_vluxei64_v_i64m1(src, ri, vl);
        __riscv_vsuxei64_v_i64m1(dst, wi, data, vl);
        read_idx += vl;
        write_idx += vl;
        avl -= vl;
    }

    zamlet_end_writeset();
    zamlet_set_index_bound(0);
}
