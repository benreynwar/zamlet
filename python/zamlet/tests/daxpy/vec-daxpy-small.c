/*************************************************************************
* Minimal Axpy Test for debugging
* Tests: y = a*x + y with just 2 elements
*************************************************************************/

#include <stdlib.h>
#include <stdio.h>
#include <math.h>
#include <riscv_vector.h>
#include "util.h"
#include "vpu_alloc.h"

void axpy_intrinsics(double a, double *dx, double *dy, size_t n) {
  for (size_t i = 0; i < n;) {
    long gvl = __riscv_vsetvl_e64m8(n - i);
    vfloat64m8_t v_dx = __riscv_vle64_v_f64m8(&dx[i], gvl);
    vfloat64m8_t v_dy = __riscv_vle64_v_f64m8(&dy[i], gvl);
    vfloat64m8_t v_res = __riscv_vfmacc_vf_f64m8(v_dy, a, v_dx, gvl);
    __riscv_vse64_v_f64m8(&dy[i], v_res, gvl);
    i += gvl;
  }
}

#define N 16
double dx[N] __attribute__((section(".data.vpu64")));
double dy[N] __attribute__((section(".data.vpu64")));

int main(int argc, char *argv[])
{
  double a = 2.0;

  // Initialize with simple values
  for (size_t i = 0; i < N; i++) {
    dx[i] = (double)(i + 1);
    dy[i] = (double)(i * 2);
  }

  // Compute expected result
  double expected[N];
  for (size_t i = 0; i < N; i++) {
    expected[i] = dy[i] + a * dx[i];
  }

  printf("Computing: dy = %f * dx + dy for N=%d\n", a, N);

  axpy_intrinsics(a, dx, dy, N);

  printf("Checking results...\n");

  int errors = 0;
  for (size_t i = 0; i < N; i++) {
    if (fabs(dy[i] - expected[i]) > 1e-10) {
        exit(i+1);
    }
  }

  if (errors == 0) {
    printf("PASSED\n");
    return 0;
  } else {
    printf("FAILED: %d errors\n", errors);
    return 1;
  }
}
