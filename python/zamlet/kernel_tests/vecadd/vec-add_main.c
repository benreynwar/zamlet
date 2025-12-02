#include <stdint.h>
#include <stddef.h>

// VPU memory starts at 0x90000000 (32-bit pool)
volatile int32_t *vpu_mem = (volatile int32_t *)0x900C0000;

// Simple exit function using HTIF
void exit_test(int code) {
    volatile uint64_t *tohost = (volatile uint64_t *)0x80001000;
    *tohost = (code << 1) | 1;
    while (1);
}

// Vector add function from assembly
void vec_add_scalar(size_t n, const int32_t* src, int32_t* dst, int32_t scalar);

#define ARRAY_SIZE 32
#define SCALAR_VALUE 42

int main() {
    int all_good = 0;

    // Initialize test data in VPU memory
    for (int i = 0; i < ARRAY_SIZE; i++) {
        vpu_mem[i] = i * 10;  // 0, 10, 20, 30, ...
    }

    // Call vector add function to add SCALAR_VALUE to each element
    vec_add_scalar(ARRAY_SIZE, vpu_mem, vpu_mem, SCALAR_VALUE);

    // Verify results
    for (int i = 0; i < ARRAY_SIZE; i++) {
        int32_t expected = i * 10 + SCALAR_VALUE;
        int32_t actual = vpu_mem[i];
        if (actual != expected) {
            all_good = 1;
            break;
        }
    }

    exit_test(all_good);
    return 0;
}
