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
    uint8_t all_good = 0x00;
    // Write a test value to VPU memory
    int n = 2048;

    for (int i = 0; i < n; i++) {
      uint8_t test_value = i;
      vpu_mem[i] = test_value;
    }
    for (int i = 0; i < n; i++) {
      uint8_t test_value = i;
      uint8_t read_value = vpu_mem[i];
      // Check if they match
      if (read_value != test_value) {
          all_good = 1;
      }
    }
    exit_test(all_good);

    return 0;
}
