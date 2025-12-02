/*************************************************************************
* Axpy Kernel
* Author: Jesus Labarta
* Barcelona Supercomputing Center
* Modified for zamlet riscv-model testing
*************************************************************************/

#include <stdlib.h>
#include <stdio.h>
#include <math.h>
#include <assert.h>
#include <string.h>
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

#define N 32
double dx[N] __attribute__((section(".data.vpu64")));
double dy[N] __attribute__((section(".data.vpu64")));

int main(int argc, char *argv[])
{
  double a = 2.5;

  // Initialize input arrays with test data
  for (size_t i = 0; i < N; i++) {
    dx[i] = (double)(i + 1);
    dy[i] = (double)(i * 2);
  }

  // Compute expected result for verification
  double expected[N];
  for (size_t i = 0; i < N; i++) {
    expected[i] = dy[i] + a * dx[i];
  }

  // Execute vector AXPY
  unsigned long cycles1, cycles2, instr2, instr1;
  instr1 = read_csr(minstret);
  cycles1 = read_csr(mcycle);

  axpy_intrinsics(a, dx, dy, N);

  asm volatile("fence");
  instr2 = read_csr(minstret);
  cycles2 = read_csr(mcycle);

  // Verify results
  int errors = 0;
  for (size_t i = 0; i < N; i++) {
    if (fabs(dy[i] - expected[i]) > 1e-10) {
      printf("ERROR at index %ld: got %f, expected %f\n", i, dy[i], expected[i]);
      errors++;
    }
  }

  if (errors == 0) {
    printf("PASSED: vec-daxpy test\n");
    printf("Cycles: %lu\n", cycles2 - cycles1);
    printf("Instructions: %lu\n", instr2 - instr1);
  } else {
    printf("FAILED: %d errors\n", errors);
    return 1;
  }

  return 0;
}
