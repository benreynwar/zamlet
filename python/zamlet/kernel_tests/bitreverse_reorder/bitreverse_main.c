#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>

volatile int32_t *vpu_mem = (volatile int32_t *)0x900C0000;
volatile int32_t skip_verify = 0;
volatile int32_t n = 0;
volatile int32_t reverse_bits = 0;

// Query hardware vector length for e32, m1
static inline size_t get_vl_e32(void) {
    size_t vl;
    // Use a large avl to get VLMAX
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

static inline int count_bits(size_t n) {
    int bits = 0;
    while (n > 1) { n >>= 1; bits++; }
    return bits;
}

void compute_indices(size_t n, size_t vl, uint32_t* read_idx, uint32_t* write_idx,
                     int reverse_bits);
void bitreverse_reorder(size_t n, const int32_t* src, int32_t* dst,
                        const uint32_t* read_idx, const uint32_t* write_idx,
                        size_t reps);

int main() {
    size_t vl = get_vl_e32();
    if ((size_t)n != 8 * vl)
        exit(1);
    int n_bits = reverse_bits ? (int)reverse_bits : count_bits(n);

    int32_t* src = (int32_t*)&vpu_mem[0];
    int32_t* dst = (int32_t*)&vpu_mem[n];
    uint32_t* read_idx = (uint32_t*)&vpu_mem[n * 2];
    uint32_t* write_idx = (uint32_t*)&vpu_mem[n * 3];

    // Initialize src[i] = i * 7 + 3
    {
        size_t rem = n;
        int32_t* p = src;
        uint32_t base = 0, seven = 7, three = 3;
        while (rem > 0) {
            size_t chunk;
            asm volatile(
                "vsetvli %0, %1, e32, m1, ta, ma\n"
                "vid.v v1\n"
                "vadd.vx v1, v1, %2\n"
                "vmul.vx v1, v1, %3\n"
                "vadd.vx v1, v1, %4\n"
                "vse32.v v1, (%5)\n"
                : "=r"(chunk)
                : "r"(rem), "r"(base), "r"(seven),
                  "r"(three), "r"(p)
                : "memory"
            );
            p += chunk;
            base += chunk;
            rem -= chunk;
        }
    }

    // Zero dst array
    {
        size_t rem = n;
        int32_t* p = dst;
        uint32_t zero = 0;
        while (rem > 0) {
            size_t chunk;
            asm volatile(
                "vsetvli %0, %1, e32, m1, ta, ma\n"
                "vmv.v.x v1, %3\n"
                "vse32.v v1, (%2)\n"
                : "=r"(chunk)
                : "r"(rem), "r"(p), "r"(zero)
                : "memory"
            );
            p += chunk;
            rem -= chunk;
        }
    }

    compute_indices(n, vl, read_idx, write_idx, n_bits);

    // Convert element indices to byte offsets
    {
        size_t rem = n;
        uint32_t* rp = read_idx;
        uint32_t* wp = write_idx;
        while (rem > 0) {
            size_t chunk;
            asm volatile(
                "vsetvli %0, %1, e32, m1, ta, ma\n"
                "vle32.v v1, (%2)\n"
                "vsll.vi v1, v1, 2\n"
                "vse32.v v1, (%2)\n"
                "vle32.v v2, (%3)\n"
                "vsll.vi v2, v2, 2\n"
                "vse32.v v2, (%3)\n"
                : "=r"(chunk)
                : "r"(rem), "r"(rp), "r"(wp)
                : "memory"
            );
            rp += chunk;
            wp += chunk;
            rem -= chunk;
        }
    }

    bitreverse_reorder(n, src, dst, read_idx, write_idx, 4);

    if (!skip_verify) {
        for (size_t i = 0; i < n; i++) {
            uint32_t src_idx = bitreverse(i, n_bits);
            int32_t expected = src_idx * 7 + 3;
            int32_t actual = dst[i];
            if (actual != expected) {
                exit(((actual & 0xFF) << 16) | (i << 8) | 0x80);
            }
        }
    }

    exit(0);  // success
    return 0;
}
