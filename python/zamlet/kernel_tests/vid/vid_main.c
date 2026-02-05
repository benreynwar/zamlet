#include <stdint.h>
#include <stddef.h>

volatile int32_t *vpu_mem = (volatile int32_t *)0x900C0000;

void exit_test(int code) {
    volatile uint64_t *tohost = (volatile uint64_t *)0x80001000;
    *tohost = (code << 1) | 1;
    while (1);
}

#define N 16

int main() {
    size_t vl;
    asm volatile ("vsetvli %0, %1, e32, m1, ta, ma" : "=r"(vl) : "r"(256));

    // Match bitreverse layout exactly
    int32_t* src = (int32_t*)&vpu_mem[0];
    int32_t* arr_dst = (int32_t*)&vpu_mem[N];
    volatile int32_t *dst = &vpu_mem[N * 2];  // read_idx position

    // Scalar writes to src and arr_dst first (like bitreverse does)
    for (int i = 0; i < N; i++) {
        src[i] = i * 7 + 3;
        arr_dst[i] = 0;
    }

    // Scalar writes to dst (like bitreverse does for read_idx)
    for (size_t i = 0; i < vl; i++) {
        dst[i] = 0xAAAAAAAA;
    }

    // vid.v creates [0, 1, 2, ...] in v0
    // vse32.v stores to dst
    // Include vsetvli like bitreverse does
    asm volatile (
        "vsetvli zero, %0, e32, m1, ta, ma\n"
        "vid.v v0\n"
        "vse32.v v0, (%1)\n"
        :
        : "r"(vl), "r"(dst)
        : "memory"
    );

    // Scalar read to verify
    for (size_t i = 0; i < vl; i++) {
        int32_t actual = dst[i];
        if (actual != (int32_t)i) {
            // Exit with: index in bits 15:8, actual low byte in bits 7:0
            exit_test((i << 8) | (actual & 0xFF) | 0x10000);
        }
    }

    exit_test(0);
    return 0;
}
