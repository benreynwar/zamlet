#include <stdint.h>
#include <stddef.h>
#include <string.h>

// VPU memory for 64-bit elements starts at 0x90100000
volatile uint8_t *vpu_mem = (volatile uint8_t *)0x90100000;

// Simple exit function using HTIF
void exit_test(int code) {
    volatile uint64_t *tohost = (volatile uint64_t *)0x80001000;
    *tohost = (code << 1) | 1;
    while (1);
}

// Vector load-store function from assembly
// Loads n elements from src+src_byte_off, stores to dst+dst_byte_off
// Byte offsets can be any value (truly unaligned)
void vec_load_store_unaligned(size_t n, const uint8_t* src, size_t src_byte_off,
                               uint8_t* dst, size_t dst_byte_off);

#define ARRAY_SIZE 16
// Byte offsets - start with 0 to verify basic functionality
#define SRC_BYTE_OFFSET 0
#define DST_BYTE_OFFSET 4

int main() {
    int errors = 0;

    // Initialize source data as bytes, then we'll read it as 64-bit elements
    // Fill with a known pattern
    for (int i = 0; i < (ARRAY_SIZE + 2) * 8 + SRC_BYTE_OFFSET; i++) {
        vpu_mem[i] = (uint8_t)(i & 0xFF);
    }

    // Clear destination area (starting at byte 256 to have separation)
    for (int i = 0; i < (ARRAY_SIZE + 4) * 8 + DST_BYTE_OFFSET; i++) {
        vpu_mem[256 + i] = 0;
    }

    // Pointers to base of source and destination regions
    uint8_t *src_base = (uint8_t *)&vpu_mem[0];
    uint8_t *dst_base = (uint8_t *)&vpu_mem[256];

    // Perform unaligned vector load/store
    vec_load_store_unaligned(ARRAY_SIZE, src_base, SRC_BYTE_OFFSET,
                             dst_base, DST_BYTE_OFFSET);

    // Verify results by comparing bytes
    for (int i = 0; i < ARRAY_SIZE * 8; i++) {
        uint8_t expected = src_base[SRC_BYTE_OFFSET + i];
        uint8_t actual = dst_base[DST_BYTE_OFFSET + i];
        if (actual != expected) {
            errors++;
        }
    }

    exit_test(errors);
    return 0;
}
