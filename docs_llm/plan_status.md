# Plan Status

One-line index of plans in `plans/`. See `ROADMAP.md` for the big picture.

## Active

- [mask_ops](plans/PLAN_mask_ops.md) — five mask ops to unblock FFT N=32 (current focus)
- [fft_kernel](plans/PLAN_fft_kernel.md) — variable-R FFT kernel; init + Regime A/B in; Regime C partial
- [per_vline_ew](plans/PLAN_per_vline_ew.md) — steps 1–3 done; 4–7 pending
- [widening_vector_arith](plans/PLAN_widening_vector_arith.md) — impl in; doc drift on `ensure_vrf_ordering`
- [llvm_vpu_spills](plans/PLAN_llvm_vpu_spills.md) — phase 1–2 done; phase 3 (LLVM patch) partial

## Todo

- [picolibc](plans/PLAN_picolibc.md) — unstarted
- [scalar_read_vpu_test](plans/PLAN_scalar_read_vpu_test.md) — test not written

## Deferred

- [vta_vma](plans/PLAN_vta_vma.md) — pick up when partial-vline-write serialization dominates
- [fp_nan_boxing](plans/PLAN_fp_nan_boxing.md) — part of broader FP correctness work
- [viota_vcompress](plans/PLAN_viota_vcompress.md) — waits for compress patterns in kernels

## Reference

- [llvm_vpu_spill_patch](plans/PLAN_llvm_vpu_spill_patch.md) — tutorial for the phase-3 LLVM work

## Recently deleted (content captured in code)

_(entries land here as plans are retired — short pointer to where the
behaviour lives)_
