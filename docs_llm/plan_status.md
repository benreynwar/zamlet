# Plan Status

One-line index of plans in `plans/`. See `ROADMAP.md` for the big picture.

## Active

- [rvv_coverage](plans/PLAN_rvv_coverage.md) — umbrella for full RVV spec
  coverage in the python model (milestone 1). Phase-ordered index that
  points at the per-feature plans below.
- [fft_kernel](plans/PLAN_fft_kernel.md) — variable-R FFT kernel; init + Regime A/B in; Regime C partial
- [per_vline_ew](plans/PLAN_per_vline_ew.md) — steps 1–3 done; 4–7 pending
  (rvv_coverage Phase 8)
- [widening_vector_arith](plans/PLAN_widening_vector_arith.md) — impl in; doc drift on `ensure_vrf_ordering`
- [llvm_vpu_spills](plans/PLAN_llvm_vpu_spills.md) — phase 1–2 done; phase 3 (LLVM patch) partial

## Todo

Scheduled by phase in `PLAN_rvv_coverage.md`; listed here for discoverability.

- [long_latency_alu](plans/PLAN_long_latency_alu.md) — per-jamlet ALU model
  with 4 pipes + framework for fflags/vxsat/rm (rvv_coverage Phase 3;
  unblocks vdiv/vfdiv/vfsqrt/vfrec7/vfrsqrt7 and the fixed-point +
  FP-correctness follow-ups)
- [vta_vma](plans/PLAN_vta_vma.md) — partial-vline-write serialization
  (rvv_coverage Phase 4; lands before per-vline-ew Phase 8 ew-remap so
  the two cleanups don't fight)
- [viota_vcompress](plans/PLAN_viota_vcompress.md) — viota.m + vcompress.vm
  (rvv_coverage Phase 6; new PrefixSumRound primitive)
- [fp_nan_boxing](plans/PLAN_fp_nan_boxing.md) — NaN-boxing + FCvt rm +
  soft-float reference (rvv_coverage Phase 7; rides on long_latency_alu
  framework)
- [mask_ops](plans/PLAN_mask_ops.md) — Step 6 needs the deleted
  `tests/test_vms_first_mask.py` recreated (rvv_coverage Phase 9).
  Implementation has landed.
- [picolibc](plans/PLAN_picolibc.md) — unstarted
- [scalar_read_vpu_test](plans/PLAN_scalar_read_vpu_test.md) — test not written

## Done / reference

- [reservation_station](plans/PLAN_reservation_station.md) — implemented; kept for the deferred-free / bypass-vs-station rationale

## Reference

- [llvm_vpu_spill_patch](plans/PLAN_llvm_vpu_spill_patch.md) — tutorial for the phase-3 LLVM work

## Recently deleted (content captured in code)

- `PLAN_lamlet_rename.md` — kamlet-side rename lives in `python/zamlet/kamlet/rename_table.py`
- `PLAN_scalar_memory_ordering.md` — ordering logic in `python/zamlet/oamlet/scalar.py`
- `PLAN_reductions.md` — `Vreduction` (vector.py) + `oamlet/reduction.py`. Ordered-float follow-up in `TODO.md`.
- `PLAN_memlet.md` — Chisel impl under `src/main/scala/zamlet/memlet/`
- `PLAN_slides_and_gathers.md` — `RegSlide` / `RegGather` in `python/zamlet/transactions/`; `Vslide` / `Vrgather*` / `Vslide1` in `instructions/vector.py`. Follow-ups in `TODO.md` and `PLAN_fp_nan_boxing.md`.
- `PLAN_trap_delivery.md` — CSR/cause constants in `python/zamlet/trap.py`; trap entry/scalar+vector access checks in `oamlet/oamlet.py`; `Mret` in `instructions/system.py`; vector fault aggregation in `lamlet/unordered.py` + `lamlet/ordered.py` + `synchronization.py`; kernel tests in `kernel_tests/trap_delivery/`. Follow-ups (fault-only-first loads, `vstart` resume) in `TODO.md`.
