#include <stdint.h>
#include <stddef.h>
#include <stdio.h>

#define N 64
#define N_BITS 6

volatile int32_t *vpu_mem = (volatile int32_t *)0x900C0000;

// Query hardware vector length for e32, m1
static inline size_t get_vl_e32(void) {
    size_t vl;
    // Use a large avl to get VLMAX
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
void bitreverse_reorder(size_t n, const int32_t* src, int32_t* dst,
                        const uint32_t* read_idx, const uint32_t* write_idx);

int main() {
    int32_t* src = (int32_t*)&vpu_mem[0];
    int32_t* dst = (int32_t*)&vpu_mem[N];
    uint32_t* read_idx = (uint32_t*)&vpu_mem[N * 2];
    uint32_t* write_idx = (uint32_t*)&vpu_mem[N * 3];

    size_t vl = get_vl_e32();
    if (vl > N) {
        vl = N;
    }

    for (int i = 0; i < N; i++) {
        src[i] = i * 7 + 3;
        dst[i] = 0;
    }

    compute_indices(N, vl, read_idx, write_idx);

    // Verify compute_indices output: write_idx[i] should equal bitreverse(read_idx[i])
    for (int i = 0; i < N; i++) {
        uint32_t expected_write = bitreverse(read_idx[i], N_BITS);
        if (write_idx[i] != expected_write) {
            // Exit with: read_idx in 31:24, expected in 23:16, actual in 15:8, i in 7:4, 0x4 flag
            exit_test((read_idx[i] << 24) | (expected_write << 16) | (write_idx[i] << 8) | (i << 4) | 0x4);
        }
    }

    for (int rep = 0; rep < 4; rep++) {
        bitreverse_reorder(N, src, dst, read_idx, write_idx);
    }

    // Exit with first failing index and value
    // Format: (actual_value << 16) | (index << 8) | 0x80
    for (int i = 0; i < N; i++) {
        uint32_t src_idx = bitreverse(i, N_BITS);
        int32_t expected = src_idx * 7 + 3;
        int32_t actual = dst[i];
        if (actual != expected) {
            exit_test(((actual & 0xFF) << 16) | (i << 8) | 0x80);
        }
    }

    exit_test(0);  // success
    return 0;
}
