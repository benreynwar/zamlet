# Plan Status

One-line index of plans in `plans/`. See `ROADMAP.md` for the big picture.

## Active

- [ordering_audit](plans/PLAN_ordering_audit.md) — vector ordering audit findings; B1-B3 bugs, M1/N1-N3 cleanup (current focus)
- [mask_ops](plans/PLAN_mask_ops.md) — five mask ops to unblock FFT N=32 (current focus)
- [fft_kernel](plans/PLAN_fft_kernel.md) — variable-R FFT kernel; init + Regime A/B in; Regime C partial
- [per_vline_ew](plans/PLAN_per_vline_ew.md) — steps 1–3 done; 4–7 pending
- [llvm_vpu_spills](plans/PLAN_llvm_vpu_spills.md) — phase 1–2 done; phase 3 (LLVM patch) partial
- [docs_overhaul](plans/PLAN_docs_overhaul.md) — restructure docs around stripe-as-unit-of-locality; Ben writes prose, Claude advises only

## Todo

- [long_latency_alu](plans/PLAN_long_latency_alu.md) — per-jamlet ALU model
  with 4 pipes + framework for fflags/vxsat/rm (unblocks vdiv/vfdiv/vfsqrt/
  vfrec7/vfrsqrt7 and the fixed-point + FP-correctness follow-ups)
- [picolibc](plans/PLAN_picolibc.md) — unstarted
- [scalar_read_vpu_test](plans/PLAN_scalar_read_vpu_test.md) — test not written

## Deferred

- [vta_vma](plans/PLAN_vta_vma.md) — pick up when partial-vline-write serialization dominates
- [fp_nan_boxing](plans/PLAN_fp_nan_boxing.md) — part of broader FP correctness work; also covers `vfmv.f.s`/`vfmv.s.f`/`vfslide1*` sites
- [viota_vcompress](plans/PLAN_viota_vcompress.md) — waits for compress patterns in kernels

## Done / reference

- [reservation_station](plans/PLAN_reservation_station.md) — implemented; kept for the deferred-free / bypass-vs-station rationale

## Reference

- [llvm_vpu_spill_patch](plans/PLAN_llvm_vpu_spill_patch.md) — tutorial for the phase-3 LLVM work

## Recently deleted (content captured in code)

- `PLAN_widening_vector_arith.md` — `VArithVvOv`/`VArithVxOv` (`instructions/vector.py`)
  + `VArithVvOvOp`/`VArithVxOvOp` (`kamlet/kinstructions.py`); decoder entries
  in `decode.py` cover the full int + float widening family and the migrated
  NSRL/NSRA narrowing-shift family. Coverage: `tests/test_widening_arith.py`.
  Out-of-scope `vnclip`/`vnclipu` tracked in RESTART.md's longer-term items.
- `PLAN_lamlet_rename.md` — kamlet-side rename lives in `python/zamlet/kamlet/rename_table.py`
- `PLAN_scalar_memory_ordering.md` — ordering logic in `python/zamlet/oamlet/scalar.py`
- `PLAN_reductions.md` — `Vreduction` (vector.py) + `oamlet/reduction.py`. Ordered-float follow-up in `TODO.md`.
- `PLAN_memlet.md` — Chisel impl under `src/main/scala/zamlet/memlet/`
- `PLAN_slides_and_gathers.md` — `RegSlide` / `RegGather` in `python/zamlet/transactions/`; `Vslide` / `Vrgather*` / `Vslide1` in `instructions/vector.py`. Follow-ups in `TODO.md` and `PLAN_fp_nan_boxing.md`.
- `PLAN_trap_delivery.md` — CSR/cause constants in `python/zamlet/trap.py`; trap entry/scalar+vector access checks in `oamlet/oamlet.py`; `Mret` in `instructions/system.py`; vector fault aggregation in `lamlet/unordered.py` + `lamlet/ordered.py` + `synchronization.py`; kernel tests in `kernel_tests/trap_delivery/`. Follow-ups (fault-only-first loads, `vstart` resume) in `TODO.md`.
