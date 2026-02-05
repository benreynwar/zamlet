/*
 * 8-point radix-2 DIT FFT using RISC-V vector intrinsics
 * Runs 128 independent 8-point FFTs
 */

#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include <math.h>
#include <riscv_vector.h>
#include "util.h"
#include "vpu_alloc.h"

#define N 8
#define N_FFTS 1
#define TOL 1e-9

// Bitreverse index arrays (32-bit, in VPU 32-bit memory)
uint32_t br_read_idx[N] __attribute__((section(".data.vpu32")));
uint32_t br_write_idx[N] __attribute__((section(".data.vpu32")));

void compute_indices(size_t n, size_t vl, uint32_t* read_idx, uint32_t* write_idx);
void bitreverse_reorder64(size_t n, const int64_t* src, int64_t* dst,
                          const uint32_t* read_idx, const uint32_t* write_idx);

// Gather indices for each stage (in VPU memory)
size_t stage0_idx_a[8] __attribute__((section(".data.vpu64"))) = {0, 0, 2, 2, 4, 4, 6, 6};
size_t stage0_idx_b[8] __attribute__((section(".data.vpu64"))) = {1, 1, 3, 3, 5, 5, 7, 7};
size_t stage1_idx_a[8] __attribute__((section(".data.vpu64"))) = {0, 1, 0, 1, 4, 5, 4, 5};
size_t stage1_idx_b[8] __attribute__((section(".data.vpu64"))) = {2, 3, 2, 3, 6, 7, 6, 7};
size_t stage2_idx_a[8] __attribute__((section(".data.vpu64"))) = {0, 1, 2, 3, 0, 1, 2, 3};
size_t stage2_idx_b[8] __attribute__((section(".data.vpu64"))) = {4, 5, 6, 7, 4, 5, 6, 7};

// Sign patterns for butterfly outputs (in VPU memory)
double stage0_signs[8] __attribute__((section(".data.vpu64"))) = {1, -1, 1, -1, 1, -1, 1, -1};
double stage1_signs[8] __attribute__((section(".data.vpu64"))) = {1, 1, -1, -1, 1, 1, -1, -1};
double stage2_signs[8] __attribute__((section(".data.vpu64"))) = {1, 1, 1, 1, -1, -1, -1, -1};

// Twiddle factors expanded for each stage (in VPU memory)
// W8^k = cos(-2*pi*k/8) + j*sin(-2*pi*k/8)
double stage0_tw_re[8] __attribute__((section(".data.vpu64"))) = {1.0, 1.0, 1.0, 1.0,
                                                                   1.0, 1.0, 1.0, 1.0};
double stage0_tw_im[8] __attribute__((section(".data.vpu64"))) = {0.0, 0.0, 0.0, 0.0,
                                                                   0.0, 0.0, 0.0, 0.0};
double stage1_tw_re[8] __attribute__((section(".data.vpu64"))) = {1.0, 0.0, 1.0, 0.0,
                                                                   1.0, 0.0, 1.0, 0.0};
double stage1_tw_im[8] __attribute__((section(".data.vpu64"))) = {0.0, -1.0, 0.0, -1.0,
                                                                   0.0, -1.0, 0.0, -1.0};
double stage2_tw_re[8] __attribute__((section(".data.vpu64"))) = {1.0, 0.707106781186548,
                                                                   0.0, -0.707106781186548,
                                                                   1.0, 0.707106781186548,
                                                                   0.0, -0.707106781186548};
double stage2_tw_im[8] __attribute__((section(".data.vpu64"))) = {0.0, -0.707106781186548,
                                                                   -1.0, -0.707106781186548,
                                                                   0.0, -0.707106781186548,
                                                                   -1.0, -0.707106781186548};

// Input/output arrays in VPU memory
double data_re[N * N_FFTS] __attribute__((section(".data.vpu64")));
double data_im[N * N_FFTS] __attribute__((section(".data.vpu64")));
double tmp_re[N] __attribute__((section(".data.vpu64")));
double tmp_im[N] __attribute__((section(".data.vpu64")));

// Expected FFT output for input [0, 1, 2, 3, 4, 5, 6, 7] + 0j
// Computed with numpy.fft.fft
double expected_re[N] = {28.0, -4.0, -4.0, -4.0, -4.0, -4.0, -4.0, -4.0};
double expected_im[N] = {0.0, 9.6568542494923806, 4.0, 1.6568542494923806,
                         0.0, -1.6568542494923806, -4.0, -9.6568542494923806};

void fft8_stage(double* dst_re, double* dst_im,
                const double* src_re, const double* src_im,
                const size_t* idx_a, const size_t* idx_b,
                const double* signs,
                const double* tw_re, const double* tw_im) {
    size_t vl = __riscv_vsetvl_e64m2(N);

    // Load source data
    vfloat64m2_t v_src_re = __riscv_vle64_v_f64m2(src_re, vl);
    vfloat64m2_t v_src_im = __riscv_vle64_v_f64m2(src_im, vl);

    // Load gather indices
    vuint64m2_t v_idx_a = __riscv_vle64_v_u64m2(idx_a, vl);
    vuint64m2_t v_idx_b = __riscv_vle64_v_u64m2(idx_b, vl);

    // Gather a and b values
    vfloat64m2_t v_a_re = __riscv_vrgather_vv_f64m2(v_src_re, v_idx_a, vl);
    vfloat64m2_t v_a_im = __riscv_vrgather_vv_f64m2(v_src_im, v_idx_a, vl);
    vfloat64m2_t v_b_re = __riscv_vrgather_vv_f64m2(v_src_re, v_idx_b, vl);
    vfloat64m2_t v_b_im = __riscv_vrgather_vv_f64m2(v_src_im, v_idx_b, vl);

    // Load twiddle factors
    vfloat64m2_t v_tw_re = __riscv_vle64_v_f64m2(tw_re, vl);
    vfloat64m2_t v_tw_im = __riscv_vle64_v_f64m2(tw_im, vl);

    // Complex multiply: W * b
    vfloat64m2_t v_wb_re = __riscv_vfsub_vv_f64m2(
        __riscv_vfmul_vv_f64m2(v_tw_re, v_b_re, vl),
        __riscv_vfmul_vv_f64m2(v_tw_im, v_b_im, vl), vl);
    vfloat64m2_t v_wb_im = __riscv_vfadd_vv_f64m2(
        __riscv_vfmul_vv_f64m2(v_tw_re, v_b_im, vl),
        __riscv_vfmul_vv_f64m2(v_tw_im, v_b_re, vl), vl);

    // Apply signs and add
    vfloat64m2_t v_signs = __riscv_vle64_v_f64m2(signs, vl);
    vfloat64m2_t v_wb_re_signed = __riscv_vfmul_vv_f64m2(v_wb_re, v_signs, vl);
    vfloat64m2_t v_wb_im_signed = __riscv_vfmul_vv_f64m2(v_wb_im, v_signs, vl);

    vfloat64m2_t v_out_re = __riscv_vfadd_vv_f64m2(v_a_re, v_wb_re_signed, vl);
    vfloat64m2_t v_out_im = __riscv_vfadd_vv_f64m2(v_a_im, v_wb_im_signed, vl);

    __riscv_vse64_v_f64m2(dst_re, v_out_re, vl);
    __riscv_vse64_v_f64m2(dst_im, v_out_im, vl);
}

void fft8(double* re, double* im) {
    // Bit-reverse permutation using precomputed indices
    bitreverse_reorder64(N, (const int64_t*)re, (int64_t*)tmp_re,
                         br_read_idx, br_write_idx);
    bitreverse_reorder64(N, (const int64_t*)im, (int64_t*)tmp_im,
                         br_read_idx, br_write_idx);

    // Stage 0
    fft8_stage(re, im, tmp_re, tmp_im,
               stage0_idx_a, stage0_idx_b, stage0_signs,
               stage0_tw_re, stage0_tw_im);

    // Stage 1
    fft8_stage(tmp_re, tmp_im, re, im,
               stage1_idx_a, stage1_idx_b, stage1_signs,
               stage1_tw_re, stage1_tw_im);

    // Stage 2
    fft8_stage(re, im, tmp_re, tmp_im,
               stage2_idx_a, stage2_idx_b, stage2_signs,
               stage2_tw_re, stage2_tw_im);
}

int main(int argc, char* argv[]) {
    // Initialize with test values
    for (int f = 0; f < N_FFTS; f++) {
        for (int i = 0; i < N; i++) {
            data_re[f * N + i] = (double)(f * N + i);
            data_im[f * N + i] = 0.0;
        }
    }

    // Compute bitreverse indices (once, before FFT loop)
    size_t vl_e32;
    asm volatile ("vsetvli %0, %1, e32, m1, ta, ma" : "=r"(vl_e32) : "r"(N));
    compute_indices(N, vl_e32, br_read_idx, br_write_idx);

    printf("Running %d x FFT-8\n", N_FFTS);

    unsigned long cycles1, cycles2;
    cycles1 = read_csr(mcycle);

    for (int f = 0; f < N_FFTS; f++) {
        fft8(&data_re[f * N], &data_im[f * N]);
    }

    asm volatile("fence");
    cycles2 = read_csr(mcycle);

    printf("Cycles: %lu\n", cycles2 - cycles1);

    // Verify results
    for (int i = 0; i < N; i++) {
        double err_re = data_re[i] - expected_re[i];
        double err_im = data_im[i] - expected_im[i];
        if (err_re < 0) err_re = -err_re;
        if (err_im < 0) err_im = -err_im;
        if (err_re > TOL || err_im > TOL) {
            printf("FAIL [%d]: got (%f, %f), expected (%f, %f)\n",
                   i, data_re[i], data_im[i], expected_re[i], expected_im[i]);
            return 1;
        }
    }

    printf("PASSED\n");
    return 0;
}
