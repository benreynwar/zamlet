#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>

volatile int32_t *vpu_mem = (volatile int32_t *)0x900C0000;
volatile int32_t skip_verify = 0;
volatile int32_t n = 0;
volatile int32_t reverse_bits = 0;

static inline size_t get_vl_e64(void) {
    size_t vl;
    asm volatile ("vsetvli %0, %1, e64, m1, ta, ma" : "=r"(vl) : "r"(1024));
    return vl;
}

static inline size_t get_vl_e32(void) {
    size_t vl;
    asm volatile ("vsetvli %0, %1, e32, m1, ta, ma" : "=r"(vl) : "r"(1024));
    return vl;
}

static inline uint32_t bitreverse(uint32_t value, int n_bits) {
    uint32_t reversed = 0;
    for (int i = 0; i < n_bits; i++) {
        if (value & (1 << i)) {
            reversed |= (1 << (n_bits - 1 - i));
        }
    }
    return reversed;
}

static inline int count_bits(size_t val) {
    int bits = 0;
    while (val > 1) { val >>= 1; bits++; }
    return bits;
}

void compute_indices(size_t n, size_t vl, uint32_t* read_idx,
                     uint32_t* write_idx, int reverse_bits);
void bitreverse_reorder64(size_t n, const int64_t* src, int64_t* dst,
                          const uint32_t* read_idx,
                          const uint32_t* write_idx);

int main() {
    size_t vl_e64 = get_vl_e64();
    size_t vl_e32 = get_vl_e32();
    if ((size_t)n != 8 * vl_e32)
        exit(1);
    int n_bits = reverse_bits ? (int)reverse_bits : count_bits(n);

    // 64-bit data arrays, 32-bit index arrays
    // Layout in vpu_mem (32-bit words):
    //   src:       [0, 2*n)        (n 64-bit elements = 2*n 32-bit words)
    //   dst:       [2*n, 4*n)
    //   read_idx:  [4*n, 5*n)      (n 32-bit indices)
    //   write_idx: [5*n, 6*n)
    int64_t* src = (int64_t*)&vpu_mem[0];
    int64_t* dst = (int64_t*)&vpu_mem[2 * n];
    uint32_t* read_idx = (uint32_t*)&vpu_mem[4 * n];
    uint32_t* write_idx = (uint32_t*)&vpu_mem[5 * n];

    // Initialize src[i] = i * 7 + 3
    for (size_t i = 0; i < (size_t)n; i++) {
        src[i] = (int64_t)i * 7 + 3;
        dst[i] = 0;
    }

    compute_indices(n, vl_e32, read_idx, write_idx, n_bits);

    bitreverse_reorder64(n, src, dst, read_idx, write_idx);

    if (!skip_verify) {
        for (size_t i = 0; i < (size_t)n; i++) {
            uint32_t src_idx = bitreverse(i, n_bits);
            int64_t expected = (int64_t)src_idx * 7 + 3;
            int64_t actual = dst[i];
            if (actual != expected) {
                exit(((int)(actual & 0xFF) << 16) | (i << 8) | 0x80);
            }
        }
    }

    exit(0);
    return 0;
}
