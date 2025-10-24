#include <stdint.h>
#include <stddef.h>

volatile int32_t *vpu_mem = (volatile int32_t *)0x900C0000;

void exit_test(int code) {
    volatile uint64_t *tohost = (volatile uint64_t *)0x80001000;
    *tohost = (code << 1) | 1;
    while (1);
}

void vec_add_scalar(size_t n, const int32_t* src, int32_t* dst, int32_t scalar);

#define ARRAY_SIZE 32

int main() {
    int all_good = 0;

    int32_t *array_a = (int32_t *)vpu_mem;
    int32_t *array_b = array_a + ARRAY_SIZE;
    int32_t *array_c = array_b + ARRAY_SIZE;

    for (int i = 0; i < ARRAY_SIZE; i++) {
        array_a[i] = i;
        array_b[i] = i * 2;
        array_c[i] = i * 3;
    }

    vec_add_scalar(ARRAY_SIZE, array_a, array_a, 10);

    vec_add_scalar(ARRAY_SIZE, array_b, array_b, 20);

    vec_add_scalar(ARRAY_SIZE, array_c, array_c, 30);

    vec_add_scalar(ARRAY_SIZE, array_a, array_a, 5);

    for (int i = 0; i < ARRAY_SIZE; i++) {
        int32_t expected_a = i + 10 + 5;
        int32_t expected_b = i * 2 + 20;
        int32_t expected_c = i * 3 + 30;

        if (array_a[i] != expected_a ||
            array_b[i] != expected_b ||
            array_c[i] != expected_c) {
            all_good = 1;
            break;
        }
    }

    exit_test(all_good);
    return 0;
}
