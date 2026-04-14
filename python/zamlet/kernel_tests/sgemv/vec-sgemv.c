#include <stddef.h>

void vec_sgemv(size_t m, size_t n, const float* v, const float* mat, float* c) {
    for (size_t i = 0; i < m; i++) {
        float vi = v[i];
        for (size_t j = 0; j < n; j++) {
            c[j] += vi * mat[i * n + j];
        }
    }
}
