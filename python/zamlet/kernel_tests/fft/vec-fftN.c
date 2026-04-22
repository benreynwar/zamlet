/*
 * Arbitrary-N (power of 2) radix-2 Cooley-Tukey DIT FFT.
 *
 * FFT_N is the transform size, passed via -DFFT_N=<N>. TWIDDLE_HEADER names
 * the generated header which defines:
 *   - omega_re/im[log2N]: successive squarings of ω_N (scalar memory).
 *     omega[j] = ω_N^(2^j).
 *   - seed_block_re/im[log2N][SEED_BLOCK_K]: seed_block[j][k] = omega[j]^k,
 *     placed in .data.vpu64. Loaded by build_seed() via unit-stride vle64.
 *   - expected_re/im[N]: DFT of the test input (VPU memory).
 *
 * Radix-(R·vl) structure with vl = min(hw_vl, N/2) and R = min(8, N/vl),
 * so R ∈ {2, 4, 8}. Load a chunk of chunk_size = R·vl complex elements
 * into R complex register groups (V_0..V_{R-1} re/im, 2R × f64m1), run
 * log2(chunk_size) FFT stages in registers, store the chunk back.
 *
 * Within a chunk, stages split by pair-distance d:
 *   - Regime A (d < vl): both butterfly sides live in the same V_i.
 *     Form vl-length H0 (A-sides) and H1 (B-sides) via a single vslideup/
 *     vslidedown per pair + masked merges — no vrgather. Stages 0..log2(vl)-1.
 *   - Regime B (d ∈ {vl, 2·vl, ..., (R/2)·vl}): butterfly sides live in
 *     different V_i; element-wise vec-vec complex butterfly. log2(R) stages.
 *
 * Regime C (inter-chunk) fires only when N > chunk_size, which (given
 * R = min(8, N/vl)) happens exactly when R = 8 and 8·vl < N. It always
 * uses an 8-register super-chunk:
 *   - Load 8 vl-length regs from 8 different chunks, run the Regime-B
 *     8-register butterfly on the super-chunk. Three FFT stages (D, 2D, 4D)
 *     per memory round-trip. P_max passes, each pass multiplies D by 8.
 *     Partial last pass possible (2- or 4-reg super-chunk).
 *
 * Twiddle sourcing. Every stage twiddle vector is derived from one seed_block
 * row (unit-stride vle64) via build_seed or build_regime_a_seed. Regime A
 * tile-replicates a length-d core to length vl. Regimes B/C split each pair's
 * twiddle as base_tw_scalar · seed_vector.
 */
#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include <math.h>
#include <riscv_vector.h>
#include "util.h"
#include "vpu_alloc.h"
#include TWIDDLE_HEADER

#ifndef FFT_N
#error "FFT_N must be defined on the command line, e.g. -DFFT_N=32"
#endif
#if FFT_N != TWIDDLE_N
#error "FFT_N must match TWIDDLE_N from the generated twiddles header"
#endif

#define N         FFT_N
#define N_FFTS    1
#define TOL       1e-9

// Compile-time upper bound on VLMAX(e64,m1). Override via -DMAX_VLMAX=. The
// actual vl is queried at runtime with vsetvli and capped to N/2.
#ifndef MAX_VLMAX
#define MAX_VLMAX 64
#endif

// Compile-time bounds on R (registers per chunk) = min(8, N/vl). R ∈ {2,4,8}.
#define MAX_R      8
#define MAX_LOG2R  3

// Number of Regime C passes. Regime C always runs at R = 8 (super-chunk of 8
// registers), so each pass covers log2(8) = 3 FFT stages at pair-distances
// ≥ chunk_size = 8·vl. log2(chunk_size) = log2(vl) + 3, so remaining stages
// after Regime A+B are log2N - log2(vl) - 3, packed 3 per pass. Worst case
// vl = 1 gives ceil(max(0, log2N - 3) / 3). For log2N ≥ 3 this equals
// (log2N - 1) / 3 with C truncating division.
#define REGIME_C_N_PASSES ((TWIDDLE_LOG2N - 1) / 3)

// Max scalar count per (P, s_rel) in Regime C. Count at (P, s_rel) is
// D_P · 2^{s_rel} / vl = (8·vl · 8^P) · 2^{s_rel} / vl = 8^(P+1) · 2^{s_rel},
// peaking at P = P_max-1, s_rel = 2: 8^P_max · 4 = 2^(3·P_max + 2).
// Use 1 when P_max = 0 so arrays decl with size ≥ 1.
#define REGIME_C_MAX_SCALARS \
    (REGIME_C_N_PASSES == 0 ? 1 : (1 << (3 * REGIME_C_N_PASSES + 2)))

void compute_indices(size_t n, size_t vl, uint32_t* read_idx, uint32_t* write_idx,
                     int reverse_bits);
void bitreverse_reorder64(size_t n, const int64_t* src, int64_t* dst,
                          const uint64_t* read_idx, const uint64_t* write_idx);

// Bitreverse indices (filled in at startup by compute_indices).
uint32_t br_read_idx32[N]  __attribute__((section(".data.vpu32")));
uint32_t br_write_idx32[N] __attribute__((section(".data.vpu32")));
uint64_t br_read_idx[N]    __attribute__((section(".data.vpu64")));
uint64_t br_write_idx[N]   __attribute__((section(".data.vpu64")));

// Working data and scratch. Stages ping-pong between these two buffers.
double data_re[N * N_FFTS] __attribute__((section(".data.vpu64")));
double data_im[N * N_FFTS] __attribute__((section(".data.vpu64")));
double tmp_re[N]           __attribute__((section(".data.vpu64")));
double tmp_im[N]           __attribute__((section(".data.vpu64")));

// Regime A tables. W_re/im[s] is the vl-length stage-s twiddle vector for
// s ∈ [0, log2_vl). Built by tile-replicating the length-d core
// [1, ω, ..., ω^(d-1)] (d = 2^s, ω = omega[log2N - s - 1]) to length vl.
// First dim bounded by TWIDDLE_LOG2N (upper bound on any sensible log2_vl).
static double W_re[TWIDDLE_LOG2N][MAX_VLMAX] __attribute__((section(".data.vpu64")));
static double W_im[TWIDDLE_LOG2N][MAX_VLMAX] __attribute__((section(".data.vpu64")));

// Regime B tables. For stage s ∈ [0, log2(R)), pair-distance d_s = vl · 2^s.
// seed[s] is a vl-length vector [1, ω_s, ω_s², ..., ω_s^(vl-1)] with
// ω_s = omega[log2N - log2_vl - s - 1]. base_tw[s][p] = ω_s^(p · vl) for
// p ∈ [0, 2^s) — the per-pair scalar applied via vec-scalar multiply.
// First dim bounded by MAX_LOG2R = 3 (R ≤ 8); second dim of base_tw
// bounded by MAX_R/2 = 4 (peak scalar count at stage log2_r-1).
static double seed_re[MAX_LOG2R][MAX_VLMAX] __attribute__((section(".data.vpu64")));
static double seed_im[MAX_LOG2R][MAX_VLMAX] __attribute__((section(".data.vpu64")));
static double base_tw_re[MAX_LOG2R][MAX_R / 2];
static double base_tw_im[MAX_LOG2R][MAX_R / 2];

// Regime C tables. One (seed, base_tw) pair per (pass P, sub-stage s_rel).
// P_dim is max(1, REGIME_C_N_PASSES) so the arrays are valid when P_max = 0.
#define C_P_DIM (REGIME_C_N_PASSES == 0 ? 1 : REGIME_C_N_PASSES)
static double c_seed_re[C_P_DIM][3][MAX_VLMAX] __attribute__((section(".data.vpu64")));
static double c_seed_im[C_P_DIM][3][MAX_VLMAX] __attribute__((section(".data.vpu64")));
static double c_base_tw_re[C_P_DIM][3][REGIME_C_MAX_SCALARS];
static double c_base_tw_im[C_P_DIM][3][REGIME_C_MAX_SCALARS];

// Runtime parameters filled by init_tables().
static int    log2_n;       // log2(N); always equals TWIDDLE_LOG2N.
static int    log2_vl;      // log2(vl_val).
static size_t vl_val;       // vl for FFT work: min(hardware VLMAX, N/2).
static int    r_val;        // Registers per chunk: min(8, N / vl_val). In {2, 4, 8}.
static int    log2_r;       // log2(r_val).
static int    n_regime_c;   // Actual number of Regime C passes (≤ REGIME_C_N_PASSES).

// expected_re / expected_im are declared in TWIDDLE_HEADER (VPU memory).

// Extend a length-cur vector V holding [ω^0, ..., ω^(cur-1)] to length 2·cur
// by scalar-multiply + slideup. ω = omega[j] is the generator of V.
// Used by build_seed and build_regime_a_seed.
static inline void double_seed(vfloat64m1_t* V_re, vfloat64m1_t* V_im,
                               int j, size_t cur) {
    // ω^cur = omega[j]^(2^log2(cur)) = omega[j + log2(cur)], since
    // omega[m] = ω_N^(2^m).
    int log2_cur = 0;
    for (size_t c = cur; c > 1; c >>= 1) log2_cur++;
    double s_re = omega_re[j + log2_cur];
    double s_im = omega_im[j + log2_cur];

    size_t vl = __riscv_vsetvl_e64m1(cur);
    vfloat64m1_t t_re = __riscv_vfsub_vv_f64m1(
        __riscv_vfmul_vf_f64m1(*V_re, s_re, vl),
        __riscv_vfmul_vf_f64m1(*V_im, s_im, vl), vl);
    vfloat64m1_t t_im = __riscv_vfadd_vv_f64m1(
        __riscv_vfmul_vf_f64m1(*V_re, s_im, vl),
        __riscv_vfmul_vf_f64m1(*V_im, s_re, vl), vl);

    vl = __riscv_vsetvl_e64m1(cur * 2);
    *V_re = __riscv_vslideup_vx_f64m1(*V_re, t_re, cur, vl);
    *V_im = __riscv_vslideup_vx_f64m1(*V_im, t_im, cur, vl);
}

// Load seed_block[j] (a geometric progression of ratio omega[j]) and extend
// to `len` by scalar-multiply + slideup doublings. Writes the length-`len`
// result to dest_re/im. `len` must be a power of 2 ≥ 1.
static inline void build_seed(double* dest_re, double* dest_im,
                              int j, size_t len) {
    size_t cur = (len < SEED_BLOCK_K) ? len : SEED_BLOCK_K;
    size_t vl = __riscv_vsetvl_e64m1(cur);
    vfloat64m1_t V_re = __riscv_vle64_v_f64m1(&seed_block_re[j][0], vl);
    vfloat64m1_t V_im = __riscv_vle64_v_f64m1(&seed_block_im[j][0], vl);

    while (cur < len) {
        double_seed(&V_re, &V_im, j, cur);
        cur *= 2;
    }

    vl = __riscv_vsetvl_e64m1(len);
    __riscv_vse64_v_f64m1(dest_re, V_re, vl);
    __riscv_vse64_v_f64m1(dest_im, V_im, vl);
}

// Build Regime A stage-s twiddle: length-d core [1, ω, ..., ω^(d-1)] with
// ω = omega[log2N - s - 1], tile-replicated to length vl_val. d = 2^s.
static inline void build_regime_a_seed(double* dest_re, double* dest_im,
                                       int s, size_t vl_val) {
    size_t d = (size_t)1 << s;
    int j = TWIDDLE_LOG2N - s - 1;

    // Load and (if needed) extend up to length d.
    size_t cur = (d < SEED_BLOCK_K) ? d : SEED_BLOCK_K;
    size_t vl = __riscv_vsetvl_e64m1(cur);
    vfloat64m1_t V_re = __riscv_vle64_v_f64m1(&seed_block_re[j][0], vl);
    vfloat64m1_t V_im = __riscv_vle64_v_f64m1(&seed_block_im[j][0], vl);
    while (cur < d) {
        double_seed(&V_re, &V_im, j, cur);
        cur *= 2;
    }

    // Tile-replicate from length d to length vl_val via log2(vl_val/d)
    // self-slideup doublings: vslideup(V, V, cur, 2·cur) copies the low cur
    // lanes up to [cur, 2·cur), producing two tiled copies.
    while (cur < vl_val) {
        vl = __riscv_vsetvl_e64m1(cur * 2);
        V_re = __riscv_vslideup_vx_f64m1(V_re, V_re, cur, vl);
        V_im = __riscv_vslideup_vx_f64m1(V_im, V_im, cur, vl);
        cur *= 2;
    }

    vl = __riscv_vsetvl_e64m1(vl_val);
    __riscv_vse64_v_f64m1(dest_re, V_re, vl);
    __riscv_vse64_v_f64m1(dest_im, V_im, vl);
}

// Fill base_tw[s][p] = ratio^p for p ∈ [0, n). Iterative complex multiply.
static inline void fill_base_tw(double* tw_re, double* tw_im,
                                double ratio_re, double ratio_im, int n) {
    double a_re = 1.0, a_im = 0.0;
    for (int p = 0; p < n; p++) {
        tw_re[p] = a_re;
        tw_im[p] = a_im;
        double nr = a_re * ratio_re - a_im * ratio_im;
        double ni = a_re * ratio_im + a_im * ratio_re;
        a_re = nr;
        a_im = ni;
    }
}

// Regime A butterfly body for one register pair (A, B). Updates both in place.
//
// H0 = merge(slideup(B, d), A, low_mask); H1 = merge(B, slidedown(A, d), low_mask);
// tmp = tw · H1 (complex); H0p = H0 + tmp; H1p = H0 − tmp;
// A' = merge(slideup(H1p, d), H0p, low_mask);
// B' = merge(H1p, slidedown(H0p, d), low_mask).
//
// low_mask is 1 where `lane mod 2d < d`. tw is the stage twiddle vector.
// Caller loads both once per stage and passes them in.
static inline void ra_pair(vfloat64m1_t* A_re, vfloat64m1_t* A_im,
                           vfloat64m1_t* B_re, vfloat64m1_t* B_im,
                           size_t d, vfloat64m1_t tw_re, vfloat64m1_t tw_im,
                           vbool64_t low_mask, size_t vl) {
    vfloat64m1_t Va_re = *A_re, Va_im = *A_im;
    vfloat64m1_t Vb_re = *B_re, Vb_im = *B_im;

    // H0 = merge(slideup(Vb, d), Va, low_mask). slideup dest is Vb itself —
    // the low d lanes are unused (masked to Va).
    vfloat64m1_t slid_Vb_re = __riscv_vslideup_vx_f64m1(Vb_re, Vb_re, d, vl);
    vfloat64m1_t slid_Vb_im = __riscv_vslideup_vx_f64m1(Vb_im, Vb_im, d, vl);
    vfloat64m1_t H0_re = __riscv_vmerge_vvm_f64m1(slid_Vb_re, Va_re, low_mask, vl);
    vfloat64m1_t H0_im = __riscv_vmerge_vvm_f64m1(slid_Vb_im, Va_im, low_mask, vl);

    // H1 = merge(Vb, slidedown(Va, d), low_mask).
    vfloat64m1_t slid_Va_re = __riscv_vslidedown_vx_f64m1(Va_re, d, vl);
    vfloat64m1_t slid_Va_im = __riscv_vslidedown_vx_f64m1(Va_im, d, vl);
    vfloat64m1_t H1_re = __riscv_vmerge_vvm_f64m1(Vb_re, slid_Va_re, low_mask, vl);
    vfloat64m1_t H1_im = __riscv_vmerge_vvm_f64m1(Vb_im, slid_Va_im, low_mask, vl);

    // Butterfly: tmp = tw · H1 (complex); H0p = H0 + tmp; H1p = H0 − tmp.
    vfloat64m1_t tmp_re = __riscv_vfsub_vv_f64m1(
        __riscv_vfmul_vv_f64m1(tw_re, H1_re, vl),
        __riscv_vfmul_vv_f64m1(tw_im, H1_im, vl), vl);
    vfloat64m1_t tmp_im = __riscv_vfadd_vv_f64m1(
        __riscv_vfmul_vv_f64m1(tw_re, H1_im, vl),
        __riscv_vfmul_vv_f64m1(tw_im, H1_re, vl), vl);

    vfloat64m1_t H0p_re = __riscv_vfadd_vv_f64m1(H0_re, tmp_re, vl);
    vfloat64m1_t H0p_im = __riscv_vfadd_vv_f64m1(H0_im, tmp_im, vl);
    vfloat64m1_t H1p_re = __riscv_vfsub_vv_f64m1(H0_re, tmp_re, vl);
    vfloat64m1_t H1p_im = __riscv_vfsub_vv_f64m1(H0_im, tmp_im, vl);

    // Pack back.
    vfloat64m1_t slid_H1p_re = __riscv_vslideup_vx_f64m1(H1p_re, H1p_re, d, vl);
    vfloat64m1_t slid_H1p_im = __riscv_vslideup_vx_f64m1(H1p_im, H1p_im, d, vl);
    *A_re = __riscv_vmerge_vvm_f64m1(slid_H1p_re, H0p_re, low_mask, vl);
    *A_im = __riscv_vmerge_vvm_f64m1(slid_H1p_im, H0p_im, low_mask, vl);

    vfloat64m1_t slid_H0p_re = __riscv_vslidedown_vx_f64m1(H0p_re, d, vl);
    vfloat64m1_t slid_H0p_im = __riscv_vslidedown_vx_f64m1(H0p_im, d, vl);
    *B_re = __riscv_vmerge_vvm_f64m1(H1p_re, slid_H0p_re, low_mask, vl);
    *B_im = __riscv_vmerge_vvm_f64m1(H1p_im, slid_H0p_im, low_mask, vl);
}

// Regime B (and Regime C sub-stage) butterfly body for one register pair.
// W = (b_re + i·b_im) · (seed_re + i·seed_im); tmp = W · B;
// A' = A + tmp; B' = A − tmp. Caller loads seed vectors once per stage.
static inline void rb_pair(vfloat64m1_t* A_re, vfloat64m1_t* A_im,
                           vfloat64m1_t* B_re, vfloat64m1_t* B_im,
                           double b_re, double b_im,
                           vfloat64m1_t seed_re_v, vfloat64m1_t seed_im_v,
                           size_t vl) {
    vfloat64m1_t Va_re = *A_re, Va_im = *A_im;
    vfloat64m1_t Vb_re = *B_re, Vb_im = *B_im;

    vfloat64m1_t W_re = __riscv_vfsub_vv_f64m1(
        __riscv_vfmul_vf_f64m1(seed_re_v, b_re, vl),
        __riscv_vfmul_vf_f64m1(seed_im_v, b_im, vl), vl);
    vfloat64m1_t W_im = __riscv_vfadd_vv_f64m1(
        __riscv_vfmul_vf_f64m1(seed_im_v, b_re, vl),
        __riscv_vfmul_vf_f64m1(seed_re_v, b_im, vl), vl);

    vfloat64m1_t tmp_re = __riscv_vfsub_vv_f64m1(
        __riscv_vfmul_vv_f64m1(W_re, Vb_re, vl),
        __riscv_vfmul_vv_f64m1(W_im, Vb_im, vl), vl);
    vfloat64m1_t tmp_im = __riscv_vfadd_vv_f64m1(
        __riscv_vfmul_vv_f64m1(W_re, Vb_im, vl),
        __riscv_vfmul_vv_f64m1(W_im, Vb_re, vl), vl);

    *A_re = __riscv_vfadd_vv_f64m1(Va_re, tmp_re, vl);
    *A_im = __riscv_vfadd_vv_f64m1(Va_im, tmp_im, vl);
    *B_re = __riscv_vfsub_vv_f64m1(Va_re, tmp_re, vl);
    *B_im = __riscv_vfsub_vv_f64m1(Va_im, tmp_im, vl);
}

// Regime C pass at super_chunk_size = 2 (partial final, 1 sub-stage).
// Loads 2 vl-length registers from offsets G + k_c·D_P + r_pos·vl for
// k_c ∈ {0, 1}, runs sub-stage s_rel=0, stores back.
static void regime_c_pass_R2(int P) {
    size_t vl = vl_val;
    size_t chunk_size = vl * (size_t)MAX_R;
    size_t D_P = chunk_size << (3 * P);
    size_t chunk_group_span = (size_t)2 * D_P;
    int base_tw_stride = 1 << (3 * (P + 1));

    vfloat64m1_t seed_re_v = __riscv_vle64_v_f64m1(&c_seed_re[P][0][0], vl);
    vfloat64m1_t seed_im_v = __riscv_vle64_v_f64m1(&c_seed_im[P][0][0], vl);

    for (size_t G = 0; G < (size_t)N; G += chunk_group_span) {
        for (int r_pos = 0; r_pos < MAX_R; r_pos++) {
            size_t off0 = G + (size_t)0 * D_P + (size_t)r_pos * vl;
            size_t off1 = G + (size_t)1 * D_P + (size_t)r_pos * vl;
            vfloat64m1_t V0_re = __riscv_vle64_v_f64m1(&data_re[off0], vl);
            vfloat64m1_t V0_im = __riscv_vle64_v_f64m1(&data_im[off0], vl);
            vfloat64m1_t V1_re = __riscv_vle64_v_f64m1(&data_re[off1], vl);
            vfloat64m1_t V1_im = __riscv_vle64_v_f64m1(&data_im[off1], vl);

            // s_rel=0: 1 pair (V0, V1), a=0.
            double b0_re = c_base_tw_re[P][0][r_pos];
            double b0_im = c_base_tw_im[P][0][r_pos];
            rb_pair(&V0_re, &V0_im, &V1_re, &V1_im,
                    b0_re, b0_im, seed_re_v, seed_im_v, vl);

            __riscv_vse64_v_f64m1(&data_re[off0], V0_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off0], V0_im, vl);
            __riscv_vse64_v_f64m1(&data_re[off1], V1_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off1], V1_im, vl);
        }
    }
    (void)base_tw_stride;
}

// Regime C pass at super_chunk_size = 4 (2 sub-stages).
static void regime_c_pass_R4(int P) {
    size_t vl = vl_val;
    size_t chunk_size = vl * (size_t)MAX_R;
    size_t D_P = chunk_size << (3 * P);
    size_t chunk_group_span = (size_t)4 * D_P;
    int base_tw_stride = 1 << (3 * (P + 1));

    vfloat64m1_t seed_re_0 = __riscv_vle64_v_f64m1(&c_seed_re[P][0][0], vl);
    vfloat64m1_t seed_im_0 = __riscv_vle64_v_f64m1(&c_seed_im[P][0][0], vl);
    vfloat64m1_t seed_re_1 = __riscv_vle64_v_f64m1(&c_seed_re[P][1][0], vl);
    vfloat64m1_t seed_im_1 = __riscv_vle64_v_f64m1(&c_seed_im[P][1][0], vl);

    for (size_t G = 0; G < (size_t)N; G += chunk_group_span) {
        for (int r_pos = 0; r_pos < MAX_R; r_pos++) {
            size_t off0 = G + (size_t)0 * D_P + (size_t)r_pos * vl;
            size_t off1 = G + (size_t)1 * D_P + (size_t)r_pos * vl;
            size_t off2 = G + (size_t)2 * D_P + (size_t)r_pos * vl;
            size_t off3 = G + (size_t)3 * D_P + (size_t)r_pos * vl;
            vfloat64m1_t V0_re = __riscv_vle64_v_f64m1(&data_re[off0], vl);
            vfloat64m1_t V0_im = __riscv_vle64_v_f64m1(&data_im[off0], vl);
            vfloat64m1_t V1_re = __riscv_vle64_v_f64m1(&data_re[off1], vl);
            vfloat64m1_t V1_im = __riscv_vle64_v_f64m1(&data_im[off1], vl);
            vfloat64m1_t V2_re = __riscv_vle64_v_f64m1(&data_re[off2], vl);
            vfloat64m1_t V2_im = __riscv_vle64_v_f64m1(&data_im[off2], vl);
            vfloat64m1_t V3_re = __riscv_vle64_v_f64m1(&data_re[off3], vl);
            vfloat64m1_t V3_im = __riscv_vle64_v_f64m1(&data_im[off3], vl);

            // s_rel=0: d_regs=1, pairs (V0,V1), (V2,V3); a=0 for both.
            {
                double b0_re = c_base_tw_re[P][0][r_pos];
                double b0_im = c_base_tw_im[P][0][r_pos];
                rb_pair(&V0_re, &V0_im, &V1_re, &V1_im,
                        b0_re, b0_im, seed_re_0, seed_im_0, vl);
                rb_pair(&V2_re, &V2_im, &V3_re, &V3_im,
                        b0_re, b0_im, seed_re_0, seed_im_0, vl);
            }
            // s_rel=1: d_regs=2, 1 group, pairs (V0,V2) a=0, (V1,V3) a=1.
            {
                double b0_re = c_base_tw_re[P][1][0 * base_tw_stride + r_pos];
                double b0_im = c_base_tw_im[P][1][0 * base_tw_stride + r_pos];
                double b1_re = c_base_tw_re[P][1][1 * base_tw_stride + r_pos];
                double b1_im = c_base_tw_im[P][1][1 * base_tw_stride + r_pos];
                rb_pair(&V0_re, &V0_im, &V2_re, &V2_im,
                        b0_re, b0_im, seed_re_1, seed_im_1, vl);
                rb_pair(&V1_re, &V1_im, &V3_re, &V3_im,
                        b1_re, b1_im, seed_re_1, seed_im_1, vl);
            }

            __riscv_vse64_v_f64m1(&data_re[off0], V0_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off0], V0_im, vl);
            __riscv_vse64_v_f64m1(&data_re[off1], V1_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off1], V1_im, vl);
            __riscv_vse64_v_f64m1(&data_re[off2], V2_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off2], V2_im, vl);
            __riscv_vse64_v_f64m1(&data_re[off3], V3_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off3], V3_im, vl);
        }
    }
}

// Regime C pass at super_chunk_size = 8 (full, 3 sub-stages).
static void regime_c_pass_R8(int P) {
    size_t vl = vl_val;
    size_t chunk_size = vl * (size_t)MAX_R;
    size_t D_P = chunk_size << (3 * P);
    size_t chunk_group_span = (size_t)8 * D_P;
    int base_tw_stride = 1 << (3 * (P + 1));

    vfloat64m1_t seed_re_0 = __riscv_vle64_v_f64m1(&c_seed_re[P][0][0], vl);
    vfloat64m1_t seed_im_0 = __riscv_vle64_v_f64m1(&c_seed_im[P][0][0], vl);
    vfloat64m1_t seed_re_1 = __riscv_vle64_v_f64m1(&c_seed_re[P][1][0], vl);
    vfloat64m1_t seed_im_1 = __riscv_vle64_v_f64m1(&c_seed_im[P][1][0], vl);
    vfloat64m1_t seed_re_2 = __riscv_vle64_v_f64m1(&c_seed_re[P][2][0], vl);
    vfloat64m1_t seed_im_2 = __riscv_vle64_v_f64m1(&c_seed_im[P][2][0], vl);

    for (size_t G = 0; G < (size_t)N; G += chunk_group_span) {
        for (int r_pos = 0; r_pos < MAX_R; r_pos++) {
            size_t off0 = G + (size_t)0 * D_P + (size_t)r_pos * vl;
            size_t off1 = G + (size_t)1 * D_P + (size_t)r_pos * vl;
            size_t off2 = G + (size_t)2 * D_P + (size_t)r_pos * vl;
            size_t off3 = G + (size_t)3 * D_P + (size_t)r_pos * vl;
            size_t off4 = G + (size_t)4 * D_P + (size_t)r_pos * vl;
            size_t off5 = G + (size_t)5 * D_P + (size_t)r_pos * vl;
            size_t off6 = G + (size_t)6 * D_P + (size_t)r_pos * vl;
            size_t off7 = G + (size_t)7 * D_P + (size_t)r_pos * vl;
            vfloat64m1_t V0_re = __riscv_vle64_v_f64m1(&data_re[off0], vl);
            vfloat64m1_t V0_im = __riscv_vle64_v_f64m1(&data_im[off0], vl);
            vfloat64m1_t V1_re = __riscv_vle64_v_f64m1(&data_re[off1], vl);
            vfloat64m1_t V1_im = __riscv_vle64_v_f64m1(&data_im[off1], vl);
            vfloat64m1_t V2_re = __riscv_vle64_v_f64m1(&data_re[off2], vl);
            vfloat64m1_t V2_im = __riscv_vle64_v_f64m1(&data_im[off2], vl);
            vfloat64m1_t V3_re = __riscv_vle64_v_f64m1(&data_re[off3], vl);
            vfloat64m1_t V3_im = __riscv_vle64_v_f64m1(&data_im[off3], vl);
            vfloat64m1_t V4_re = __riscv_vle64_v_f64m1(&data_re[off4], vl);
            vfloat64m1_t V4_im = __riscv_vle64_v_f64m1(&data_im[off4], vl);
            vfloat64m1_t V5_re = __riscv_vle64_v_f64m1(&data_re[off5], vl);
            vfloat64m1_t V5_im = __riscv_vle64_v_f64m1(&data_im[off5], vl);
            vfloat64m1_t V6_re = __riscv_vle64_v_f64m1(&data_re[off6], vl);
            vfloat64m1_t V6_im = __riscv_vle64_v_f64m1(&data_im[off6], vl);
            vfloat64m1_t V7_re = __riscv_vle64_v_f64m1(&data_re[off7], vl);
            vfloat64m1_t V7_im = __riscv_vle64_v_f64m1(&data_im[off7], vl);

            // s_rel=0: d_regs=1, 4 groups; pairs (0,1),(2,3),(4,5),(6,7); a=0.
            {
                double b0_re = c_base_tw_re[P][0][r_pos];
                double b0_im = c_base_tw_im[P][0][r_pos];
                rb_pair(&V0_re, &V0_im, &V1_re, &V1_im,
                        b0_re, b0_im, seed_re_0, seed_im_0, vl);
                rb_pair(&V2_re, &V2_im, &V3_re, &V3_im,
                        b0_re, b0_im, seed_re_0, seed_im_0, vl);
                rb_pair(&V4_re, &V4_im, &V5_re, &V5_im,
                        b0_re, b0_im, seed_re_0, seed_im_0, vl);
                rb_pair(&V6_re, &V6_im, &V7_re, &V7_im,
                        b0_re, b0_im, seed_re_0, seed_im_0, vl);
            }
            // s_rel=1: d_regs=2, 2 groups; pairs (0,2)a=0,(1,3)a=1,(4,6)a=0,(5,7)a=1.
            {
                double b0_re = c_base_tw_re[P][1][0 * base_tw_stride + r_pos];
                double b0_im = c_base_tw_im[P][1][0 * base_tw_stride + r_pos];
                double b1_re = c_base_tw_re[P][1][1 * base_tw_stride + r_pos];
                double b1_im = c_base_tw_im[P][1][1 * base_tw_stride + r_pos];
                rb_pair(&V0_re, &V0_im, &V2_re, &V2_im,
                        b0_re, b0_im, seed_re_1, seed_im_1, vl);
                rb_pair(&V1_re, &V1_im, &V3_re, &V3_im,
                        b1_re, b1_im, seed_re_1, seed_im_1, vl);
                rb_pair(&V4_re, &V4_im, &V6_re, &V6_im,
                        b0_re, b0_im, seed_re_1, seed_im_1, vl);
                rb_pair(&V5_re, &V5_im, &V7_re, &V7_im,
                        b1_re, b1_im, seed_re_1, seed_im_1, vl);
            }
            // s_rel=2: d_regs=4, 1 group; pairs (0,4)a=0,(1,5)a=1,(2,6)a=2,(3,7)a=3.
            {
                double b0_re = c_base_tw_re[P][2][0 * base_tw_stride + r_pos];
                double b0_im = c_base_tw_im[P][2][0 * base_tw_stride + r_pos];
                double b1_re = c_base_tw_re[P][2][1 * base_tw_stride + r_pos];
                double b1_im = c_base_tw_im[P][2][1 * base_tw_stride + r_pos];
                double b2_re = c_base_tw_re[P][2][2 * base_tw_stride + r_pos];
                double b2_im = c_base_tw_im[P][2][2 * base_tw_stride + r_pos];
                double b3_re = c_base_tw_re[P][2][3 * base_tw_stride + r_pos];
                double b3_im = c_base_tw_im[P][2][3 * base_tw_stride + r_pos];
                rb_pair(&V0_re, &V0_im, &V4_re, &V4_im,
                        b0_re, b0_im, seed_re_2, seed_im_2, vl);
                rb_pair(&V1_re, &V1_im, &V5_re, &V5_im,
                        b1_re, b1_im, seed_re_2, seed_im_2, vl);
                rb_pair(&V2_re, &V2_im, &V6_re, &V6_im,
                        b2_re, b2_im, seed_re_2, seed_im_2, vl);
                rb_pair(&V3_re, &V3_im, &V7_re, &V7_im,
                        b3_re, b3_im, seed_re_2, seed_im_2, vl);
            }

            __riscv_vse64_v_f64m1(&data_re[off0], V0_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off0], V0_im, vl);
            __riscv_vse64_v_f64m1(&data_re[off1], V1_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off1], V1_im, vl);
            __riscv_vse64_v_f64m1(&data_re[off2], V2_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off2], V2_im, vl);
            __riscv_vse64_v_f64m1(&data_re[off3], V3_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off3], V3_im, vl);
            __riscv_vse64_v_f64m1(&data_re[off4], V4_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off4], V4_im, vl);
            __riscv_vse64_v_f64m1(&data_re[off5], V5_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off5], V5_im, vl);
            __riscv_vse64_v_f64m1(&data_re[off6], V6_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off6], V6_im, vl);
            __riscv_vse64_v_f64m1(&data_re[off7], V7_re, vl);
            __riscv_vse64_v_f64m1(&data_im[off7], V7_im, vl);
        }
    }
}

// Dispatching wrapper. n_sub_stages is implicit in super_chunk_size
// (super_chunk_size = 2^n_sub_stages), so the specialized passes don't need it.
static void regime_c_pass(int P, int super_chunk_size, int n_sub_stages) {
    (void)n_sub_stages;
    switch (super_chunk_size) {
        case 2: regime_c_pass_R2(P); break;
        case 4: regime_c_pass_R4(P); break;
        case 8: regime_c_pass_R8(P); break;
        default: __builtin_unreachable();
    }
}

static void init_tables(void) {
    log2_n = TWIDDLE_LOG2N;

    // Query hardware VLMAX at e64,m1 (AVL > 2·VLMAX forces vl = VLMAX), then
    // cap to N/2: the chunk structure needs at least one register pair per
    // butterfly, i.e. 2·vl elements of data.
    size_t hw_vlmax = __riscv_vsetvl_e64m1((size_t)1 << 30);
    vl_val = hw_vlmax < (size_t)(N / 2) ? hw_vlmax : (size_t)(N / 2);
    // Re-issue vsetvli so subsequent ops use the capped length.
    (void)__riscv_vsetvl_e64m1(vl_val);

    log2_vl = 0;
    for (size_t v = vl_val; v > 1; v >>= 1) log2_vl++;

    // R = min(8, N / vl). Since vl ≤ N/2, N/vl ≥ 2, so R ∈ {2, 4, 8}.
    size_t n_over_vl = (size_t)N / vl_val;
    r_val = (int)(n_over_vl < (size_t)MAX_R ? n_over_vl : (size_t)MAX_R);
    log2_r = 0;
    for (int r = r_val; r > 1; r >>= 1) log2_r++;

    // Regime A: per-stage vl-length twiddle vector W[s], s ∈ [0, log2_vl).
    for (int s = 0; s < log2_vl; s++) {
        build_regime_a_seed(&W_re[s][0], &W_im[s][0], s, vl_val);
    }

    // Regime B: per-stage seed[s] and base_tw[s][p] for s ∈ [0, log2_r).
    // seed ratio ω_s = omega[log2N - log2_vl - s - 1]; per-pair scalar
    // base_tw[s][p] = ω_s^(p · vl) = omega[log2N - log2_vl - s - 1 + log2_vl]^p
    //                              = omega[log2N - s - 1]^p.
    for (int s = 0; s < log2_r; s++) {
        int j_seed = log2_n - log2_vl - s - 1;
        build_seed(&seed_re[s][0], &seed_im[s][0], j_seed, vl_val);

        int j_base = log2_n - s - 1;
        fill_base_tw(&base_tw_re[s][0], &base_tw_im[s][0],
                     omega_re[j_base], omega_im[j_base], 1 << s);
    }

    // Regime C: fires only when R = 8 and chunk_size = 8·vl < N. Count passes
    // from the runtime vl, capped at the compile-time REGIME_C_N_PASSES bound.
    n_regime_c = 0;
    if (r_val == MAX_R && vl_val * MAX_R < (size_t)N) {
        int remaining = log2_n - log2_vl - 3;
        n_regime_c = (remaining + 2) / 3;
    }
    for (int P = 0; P < n_regime_c; P++) {
        for (int s_rel = 0; s_rel < 3; s_rel++) {
            int j_seed = log2_n - log2_vl - 4 - 3 * P - s_rel;
            if (j_seed < 0) break;  // partial final pass — fewer sub-stages.
            build_seed(&c_seed_re[P][s_rel][0], &c_seed_im[P][s_rel][0],
                       j_seed, vl_val);

            // c_base_tw[P][s_rel][p_lin] = ω_s^(p_lin · vl), where
            // ω_s = omega[j_seed]. Step = ω_s^vl = omega[j_seed + log2_vl].
            // Count: D_P · 2^{s_rel} / vl = 8^(P+1) · 2^{s_rel}.
            int j_base = j_seed + log2_vl;
            int n_p = 1 << (3 * (P + 1) + s_rel);
            fill_base_tw(&c_base_tw_re[P][s_rel][0], &c_base_tw_im[P][s_rel][0],
                         omega_re[j_base], omega_im[j_base], n_p);
        }
    }
}

// Helper: build Regime A per-stage (d, low_mask, tw) setup.
static inline void ra_setup(int s, size_t vl,
                            size_t* d_out, vbool64_t* low_mask_out,
                            vfloat64m1_t* tw_re_out, vfloat64m1_t* tw_im_out) {
    *d_out = (size_t)1 << s;
    vuint64m1_t idx = __riscv_vid_v_u64m1(vl);
    vuint64m1_t idx_mod = __riscv_vand_vx_u64m1(idx, (uint64_t)(2 * *d_out - 1), vl);
    *low_mask_out = __riscv_vmsltu_vx_u64m1_b64(idx_mod, (uint64_t)*d_out, vl);
    *tw_re_out = __riscv_vle64_v_f64m1(&W_re[s][0], vl);
    *tw_im_out = __riscv_vle64_v_f64m1(&W_im[s][0], vl);
}

// Run one radix-(2·vl) chunk (R=2). log2_vl Regime A stages, 1 Regime B stage.
static inline void run_chunk_R2(size_t chunk_base) {
    size_t vl = vl_val;

    vfloat64m1_t V0_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 0 * vl], vl);
    vfloat64m1_t V0_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 0 * vl], vl);
    vfloat64m1_t V1_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 1 * vl], vl);
    vfloat64m1_t V1_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 1 * vl], vl);

    for (int s = 0; s < log2_vl; s++) {
        size_t d; vbool64_t low_mask; vfloat64m1_t tw_re, tw_im;
        ra_setup(s, vl, &d, &low_mask, &tw_re, &tw_im);
        ra_pair(&V0_re, &V0_im, &V1_re, &V1_im, d, tw_re, tw_im, low_mask, vl);
    }

    // Regime B s=0: pair (V0, V1), a=0.
    {
        vfloat64m1_t seed_re_v = __riscv_vle64_v_f64m1(&seed_re[0][0], vl);
        vfloat64m1_t seed_im_v = __riscv_vle64_v_f64m1(&seed_im[0][0], vl);
        double b0_re = base_tw_re[0][0];
        double b0_im = base_tw_im[0][0];
        rb_pair(&V0_re, &V0_im, &V1_re, &V1_im,
                b0_re, b0_im, seed_re_v, seed_im_v, vl);
    }

    __riscv_vse64_v_f64m1(&data_re[chunk_base + 0 * vl], V0_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 0 * vl], V0_im, vl);
    __riscv_vse64_v_f64m1(&data_re[chunk_base + 1 * vl], V1_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 1 * vl], V1_im, vl);
}

// Run one radix-(4·vl) chunk (R=4). log2_vl Regime A stages, 2 Regime B stages.
static inline void run_chunk_R4(size_t chunk_base) {
    size_t vl = vl_val;

    vfloat64m1_t V0_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 0 * vl], vl);
    vfloat64m1_t V0_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 0 * vl], vl);
    vfloat64m1_t V1_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 1 * vl], vl);
    vfloat64m1_t V1_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 1 * vl], vl);
    vfloat64m1_t V2_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 2 * vl], vl);
    vfloat64m1_t V2_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 2 * vl], vl);
    vfloat64m1_t V3_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 3 * vl], vl);
    vfloat64m1_t V3_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 3 * vl], vl);

    for (int s = 0; s < log2_vl; s++) {
        size_t d; vbool64_t low_mask; vfloat64m1_t tw_re, tw_im;
        ra_setup(s, vl, &d, &low_mask, &tw_re, &tw_im);
        ra_pair(&V0_re, &V0_im, &V1_re, &V1_im, d, tw_re, tw_im, low_mask, vl);
        ra_pair(&V2_re, &V2_im, &V3_re, &V3_im, d, tw_re, tw_im, low_mask, vl);
    }

    // Regime B s=0: pairs (V0,V1), (V2,V3); a=0 both.
    {
        vfloat64m1_t seed_re_v = __riscv_vle64_v_f64m1(&seed_re[0][0], vl);
        vfloat64m1_t seed_im_v = __riscv_vle64_v_f64m1(&seed_im[0][0], vl);
        double b0_re = base_tw_re[0][0];
        double b0_im = base_tw_im[0][0];
        rb_pair(&V0_re, &V0_im, &V1_re, &V1_im,
                b0_re, b0_im, seed_re_v, seed_im_v, vl);
        rb_pair(&V2_re, &V2_im, &V3_re, &V3_im,
                b0_re, b0_im, seed_re_v, seed_im_v, vl);
    }
    // Regime B s=1: pairs (V0,V2) a=0, (V1,V3) a=1.
    {
        vfloat64m1_t seed_re_v = __riscv_vle64_v_f64m1(&seed_re[1][0], vl);
        vfloat64m1_t seed_im_v = __riscv_vle64_v_f64m1(&seed_im[1][0], vl);
        double b0_re = base_tw_re[1][0];
        double b0_im = base_tw_im[1][0];
        double b1_re = base_tw_re[1][1];
        double b1_im = base_tw_im[1][1];
        rb_pair(&V0_re, &V0_im, &V2_re, &V2_im,
                b0_re, b0_im, seed_re_v, seed_im_v, vl);
        rb_pair(&V1_re, &V1_im, &V3_re, &V3_im,
                b1_re, b1_im, seed_re_v, seed_im_v, vl);
    }

    __riscv_vse64_v_f64m1(&data_re[chunk_base + 0 * vl], V0_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 0 * vl], V0_im, vl);
    __riscv_vse64_v_f64m1(&data_re[chunk_base + 1 * vl], V1_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 1 * vl], V1_im, vl);
    __riscv_vse64_v_f64m1(&data_re[chunk_base + 2 * vl], V2_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 2 * vl], V2_im, vl);
    __riscv_vse64_v_f64m1(&data_re[chunk_base + 3 * vl], V3_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 3 * vl], V3_im, vl);
}

// Run one radix-(8·vl) chunk (R=8). log2_vl Regime A stages, 3 Regime B stages.
static inline void run_chunk_R8(size_t chunk_base) {
    size_t vl = vl_val;

    vfloat64m1_t V0_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 0 * vl], vl);
    vfloat64m1_t V0_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 0 * vl], vl);
    vfloat64m1_t V1_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 1 * vl], vl);
    vfloat64m1_t V1_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 1 * vl], vl);
    vfloat64m1_t V2_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 2 * vl], vl);
    vfloat64m1_t V2_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 2 * vl], vl);
    vfloat64m1_t V3_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 3 * vl], vl);
    vfloat64m1_t V3_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 3 * vl], vl);
    vfloat64m1_t V4_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 4 * vl], vl);
    vfloat64m1_t V4_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 4 * vl], vl);
    vfloat64m1_t V5_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 5 * vl], vl);
    vfloat64m1_t V5_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 5 * vl], vl);
    vfloat64m1_t V6_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 6 * vl], vl);
    vfloat64m1_t V6_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 6 * vl], vl);
    vfloat64m1_t V7_re = __riscv_vle64_v_f64m1(&data_re[chunk_base + 7 * vl], vl);
    vfloat64m1_t V7_im = __riscv_vle64_v_f64m1(&data_im[chunk_base + 7 * vl], vl);

    for (int s = 0; s < log2_vl; s++) {
        size_t d; vbool64_t low_mask; vfloat64m1_t tw_re, tw_im;
        ra_setup(s, vl, &d, &low_mask, &tw_re, &tw_im);
        ra_pair(&V0_re, &V0_im, &V1_re, &V1_im, d, tw_re, tw_im, low_mask, vl);
        ra_pair(&V2_re, &V2_im, &V3_re, &V3_im, d, tw_re, tw_im, low_mask, vl);
        ra_pair(&V4_re, &V4_im, &V5_re, &V5_im, d, tw_re, tw_im, low_mask, vl);
        ra_pair(&V6_re, &V6_im, &V7_re, &V7_im, d, tw_re, tw_im, low_mask, vl);
    }

    // Regime B s=0: pairs (0,1),(2,3),(4,5),(6,7); a=0 all.
    {
        vfloat64m1_t seed_re_v = __riscv_vle64_v_f64m1(&seed_re[0][0], vl);
        vfloat64m1_t seed_im_v = __riscv_vle64_v_f64m1(&seed_im[0][0], vl);
        double b0_re = base_tw_re[0][0];
        double b0_im = base_tw_im[0][0];
        rb_pair(&V0_re, &V0_im, &V1_re, &V1_im,
                b0_re, b0_im, seed_re_v, seed_im_v, vl);
        rb_pair(&V2_re, &V2_im, &V3_re, &V3_im,
                b0_re, b0_im, seed_re_v, seed_im_v, vl);
        rb_pair(&V4_re, &V4_im, &V5_re, &V5_im,
                b0_re, b0_im, seed_re_v, seed_im_v, vl);
        rb_pair(&V6_re, &V6_im, &V7_re, &V7_im,
                b0_re, b0_im, seed_re_v, seed_im_v, vl);
    }
    // Regime B s=1: pairs (0,2)a=0,(1,3)a=1,(4,6)a=0,(5,7)a=1.
    {
        vfloat64m1_t seed_re_v = __riscv_vle64_v_f64m1(&seed_re[1][0], vl);
        vfloat64m1_t seed_im_v = __riscv_vle64_v_f64m1(&seed_im[1][0], vl);
        double b0_re = base_tw_re[1][0];
        double b0_im = base_tw_im[1][0];
        double b1_re = base_tw_re[1][1];
        double b1_im = base_tw_im[1][1];
        rb_pair(&V0_re, &V0_im, &V2_re, &V2_im,
                b0_re, b0_im, seed_re_v, seed_im_v, vl);
        rb_pair(&V1_re, &V1_im, &V3_re, &V3_im,
                b1_re, b1_im, seed_re_v, seed_im_v, vl);
        rb_pair(&V4_re, &V4_im, &V6_re, &V6_im,
                b0_re, b0_im, seed_re_v, seed_im_v, vl);
        rb_pair(&V5_re, &V5_im, &V7_re, &V7_im,
                b1_re, b1_im, seed_re_v, seed_im_v, vl);
    }
    // Regime B s=2: pairs (0,4)a=0,(1,5)a=1,(2,6)a=2,(3,7)a=3.
    {
        vfloat64m1_t seed_re_v = __riscv_vle64_v_f64m1(&seed_re[2][0], vl);
        vfloat64m1_t seed_im_v = __riscv_vle64_v_f64m1(&seed_im[2][0], vl);
        double b0_re = base_tw_re[2][0];
        double b0_im = base_tw_im[2][0];
        double b1_re = base_tw_re[2][1];
        double b1_im = base_tw_im[2][1];
        double b2_re = base_tw_re[2][2];
        double b2_im = base_tw_im[2][2];
        double b3_re = base_tw_re[2][3];
        double b3_im = base_tw_im[2][3];
        rb_pair(&V0_re, &V0_im, &V4_re, &V4_im,
                b0_re, b0_im, seed_re_v, seed_im_v, vl);
        rb_pair(&V1_re, &V1_im, &V5_re, &V5_im,
                b1_re, b1_im, seed_re_v, seed_im_v, vl);
        rb_pair(&V2_re, &V2_im, &V6_re, &V6_im,
                b2_re, b2_im, seed_re_v, seed_im_v, vl);
        rb_pair(&V3_re, &V3_im, &V7_re, &V7_im,
                b3_re, b3_im, seed_re_v, seed_im_v, vl);
    }

    __riscv_vse64_v_f64m1(&data_re[chunk_base + 0 * vl], V0_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 0 * vl], V0_im, vl);
    __riscv_vse64_v_f64m1(&data_re[chunk_base + 1 * vl], V1_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 1 * vl], V1_im, vl);
    __riscv_vse64_v_f64m1(&data_re[chunk_base + 2 * vl], V2_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 2 * vl], V2_im, vl);
    __riscv_vse64_v_f64m1(&data_re[chunk_base + 3 * vl], V3_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 3 * vl], V3_im, vl);
    __riscv_vse64_v_f64m1(&data_re[chunk_base + 4 * vl], V4_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 4 * vl], V4_im, vl);
    __riscv_vse64_v_f64m1(&data_re[chunk_base + 5 * vl], V5_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 5 * vl], V5_im, vl);
    __riscv_vse64_v_f64m1(&data_re[chunk_base + 6 * vl], V6_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 6 * vl], V6_im, vl);
    __riscv_vse64_v_f64m1(&data_re[chunk_base + 7 * vl], V7_re, vl);
    __riscv_vse64_v_f64m1(&data_im[chunk_base + 7 * vl], V7_im, vl);
}

// Dispatching wrapper.
static inline void run_chunk(size_t chunk_base) {
    switch (r_val) {
        case 2: run_chunk_R2(chunk_base); break;
        case 4: run_chunk_R4(chunk_base); break;
        case 8: run_chunk_R8(chunk_base); break;
        default: __builtin_unreachable();
    }
}

int main(int argc, char* argv[]) {
    (void)argc;
    (void)argv;

    // Input: x[i] = i + 0j, matching the expected[] table in the generated
    // twiddles header. Populate tmp_re/im so bitreverse_reorder64 can write
    // the bit-reversed layout directly into data_re/im.
    for (size_t i = 0; i < (size_t)N; i++) {
        tmp_re[i] = (double)i;
        tmp_im[i] = 0.0;
    }

    // Bit-reverse indices. compute_indices emits 32-bit element indices at
    // the current e32 vl; widen + byte-scale (<<3 for e64) to 64-bit byte
    // offsets for bitreverse_reorder64.
    size_t vl_e32;
    asm volatile ("vsetvli %0, %1, e32, m1, ta, ma" : "=r"(vl_e32) : "r"(N));
    int n_bits = 0;
    for (size_t v = N; v > 1; v >>= 1) n_bits++;
    compute_indices(N, vl_e32, br_read_idx32, br_write_idx32, n_bits);
    for (size_t i = 0; i < (size_t)N; i++) {
        br_read_idx[i]  = ((uint64_t)br_read_idx32[i])  << 3;
        br_write_idx[i] = ((uint64_t)br_write_idx32[i]) << 3;
    }

    init_tables();

    // Bit-reverse tmp → data. After this, data holds the reordered input;
    // FFT runs in-place on data_re/im.
    bitreverse_reorder64(N, (const int64_t*)tmp_re, (int64_t*)data_re,
                         br_read_idx, br_write_idx);
    bitreverse_reorder64(N, (const int64_t*)tmp_im, (int64_t*)data_im,
                         br_read_idx, br_write_idx);

    printf("Running FFT-%d (vl=%zu, R=%d)\n", N, vl_val, r_val);

    unsigned long cycles1, cycles2;
    cycles1 = read_csr(mcycle);

    size_t chunk_size = (size_t)r_val * vl_val;
    for (size_t cb = 0; cb < (size_t)N; cb += chunk_size) {
        run_chunk(cb);
    }

    for (int P = 0; P < n_regime_c; P++) {
        int remaining = log2_n - log2_vl - 3 - 3 * P;
        int n_sub = (remaining < 3) ? remaining : 3;
        int super_chunk = 1 << n_sub;
        regime_c_pass(P, super_chunk, n_sub);
    }

    asm volatile("fence");
    cycles2 = read_csr(mcycle);

    printf("Cycles: %lu\n", cycles2 - cycles1);

    for (size_t i = 0; i < (size_t)N; i++) {
        double err_re = data_re[i] - expected_re[i];
        double err_im = data_im[i] - expected_im[i];
        if (err_re < 0) err_re = -err_re;
        if (err_im < 0) err_im = -err_im;
        if (err_re > TOL || err_im > TOL) {
            printf("FAIL [%zu]: got (%f, %f), expected (%f, %f)\n",
                   i, data_re[i], data_im[i], expected_re[i], expected_im[i]);
            return 1;
        }
    }

    printf("PASSED\n");
    return 0;
}
