#include <stdint.h>

// VPU memory starts at 0x90000000 (32-bit pool)
volatile uint8_t *vpu_mem = (volatile uint8_t *)0x900C0000;

// Simple exit function using HTIF
void exit_test(int code) {
    volatile uint64_t *tohost = (volatile uint64_t *)0x80001000;
    *tohost = (code << 1) | 1;
    while (1);
}

int main() {
    // Write a test value to VPU memory
    uint8_t test_value = 0x42;
    vpu_mem[0] = test_value;

    // Read it back
    uint8_t read_value = vpu_mem[0];

    // Check if they match
    if (read_value == test_value) {
        exit_test(0);  // Success
    } else {
        exit_test(1);  // Failure
    }

    return 0;
}
