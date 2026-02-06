#include <stdint.h>
#include <stddef.h>

#define N 64
#define N_BITS 6

// 64-bit data in VPU 64-bit pool, 32-bit indices in VPU 32-bit pool
volatile int64_t *vpu_mem64 = (volatile int64_t *)0x90100000;
volatile uint32_t *vpu_mem32 = (volatile uint32_t *)0x900C0000;

static inline size_t get_vl_e32(void) {
    size_t vl;
    asm volatile ("vsetvli %0, %1, e32, m1, ta, ma" : "=r"(vl) : "r"(1024));
    return vl;
}

void exit_test(int code) {
    volatile uint64_t *tohost = (volatile uint64_t *)0x80001000;
    *tohost = (code << 1) | 1;
    while (1);
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

void compute_indices(size_t n, size_t vl, uint32_t* read_idx, uint32_t* write_idx);
void bitreverse_reorder64(size_t n, const int64_t* src, int64_t* dst,
                          const uint32_t* read_idx, const uint32_t* write_idx);

int main() {
    int64_t* src = (int64_t*)&vpu_mem64[0];
    int64_t* dst = (int64_t*)&vpu_mem64[N];
    uint32_t* read_idx = (uint32_t*)&vpu_mem32[0];
    uint32_t* write_idx = (uint32_t*)&vpu_mem32[N];

    size_t vl = get_vl_e32();
    if (vl > N) {
        vl = N;
    }

    for (int i = 0; i < N; i++) {
        src[i] = (int64_t)i * 7 + 3;
        dst[i] = 0;
    }

    compute_indices(N, vl, read_idx, write_idx);

    // Verify compute_indices output
    for (int i = 0; i < N; i++) {
        uint32_t expected_write = bitreverse(read_idx[i], N_BITS);
        if (write_idx[i] != expected_write) {
            exit_test((read_idx[i] << 24) | (expected_write << 16)
                      | (write_idx[i] << 8) | (i << 4) | 0x4);
        }
    }

    bitreverse_reorder64(N, src, dst, read_idx, write_idx);

    // Verify: dst[i] should equal src[bitreverse(i)]
    for (int i = 0; i < N; i++) {
        uint32_t src_idx = bitreverse(i, N_BITS);
        int64_t expected = (int64_t)src_idx * 7 + 3;
        int64_t actual = dst[i];
        if (actual != expected) {
            exit_test(((int)(actual & 0xFF) << 16) | (i << 8) | 0x80);
        }
    }

    exit_test(0);
    return 0;
}
