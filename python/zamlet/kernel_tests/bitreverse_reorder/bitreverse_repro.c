#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>

static inline uint32_t bitreverse(uint32_t value, int n_bits) {
    uint32_t reversed = 0;
    for (int i = 0; i < n_bits; i++) {
        if (value & (1 << i)) {
            reversed |= (1 << (n_bits - 1 - i));
        }
    }
    return reversed;
}

volatile int32_t n_bits = 0;
volatile int32_t input_val = 0;

int main() {
    uint32_t result = bitreverse((uint32_t)input_val, (int)n_bits);
    if (result != 0) {
        exit(result);
    }
    exit(0);
    return 0;
}
