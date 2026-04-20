# Plan: Slide and Gather Variants

## Context

`vec-fftN.c` compiles for N=32 but `test_fftN32_k2x1_j1x1` fails in the python simulator because
`vslideup.vx` is not decoded. The FFT kernel uses `vslideup.vx` and `vslidedown.vx` in
`ra_pair()` for the Regime A butterfly. Adding just those two instructions is the minimum to
unblock the FFT work (`docs/PLAN_fft_kernel.md`).

The wider permutation coverage (per `python/zamlet/plan/11_permutations.txt`) is ~40%. The
remaining data-movement gap is 8 slides + 3 gather variants + `vcompress.vm` + FP scalar moves.
Several of those are near-free given the machinery we add for slides and the primitives we
already have, so it's worth picking up the cheap ones in the same pass before returning to FFT.

## Scope

**In:**
1. `vslideup.vx`, `vslideup.vi`, `vslidedown.vx`, `vslidedown.vi`
2. `vrgather.vx`, `vrgather.vi`
3. `vslide1up.vx`, `vslide1down.vx`
4. `vrgatherei16.vv`

**Out (deferred):**
- `vfslide1up.vf`, `vfslide1down.vf` — depend on adding `VfmvSf`. Pick up when a kernel needs
  them (FFT doesn't).
- `vcompress.vm` — needs prefix-sum machinery, separate work item.
- `vfmv.f.s`, `vfmv.s.f` — unrelated scalar moves, do when needed.

## Design

### One new kinstr: `RegSlide`

Sibling of `RegGather` in `python/zamlet/transactions/`. Reuses the cross-jamlet
`ReadRegElement` transaction and the same locking / completion-sync pattern. Differs only in
how the source element index is computed for each destination lane:

- `RegGather`: `idx = vs1[i]` (read from index vector register)
- `RegSlide`: `idx = i ± offset` (computed from lane position and a scalar offset)

Slideup's tail-undisturbed region (`i < offset`) reuses `RegGather`'s "skip element" path.
Slidedown's out-of-range case (`i + offset ≥ vlmax`) reuses the "write 0" path.

Fields: `vd`, `vs2`, `offset`, `direction ∈ {up, down}`, `start_index`, `n_elements`,
`data_ew`, `word_order`, `vlmax`, `mask_reg`, `instr_ident`. No `vs1`, no scalar payload.

**Python-only for now.** A Chisel-compatible 64-bit encoding for `RegSlide` (and the
existing `RegGather`, `VArithV{v,x}Op`, etc.) is a larger design task: fitting everything in
64 bits likely requires moving `vsetvli`-stable state (`data_ew`, `lmul`, `word_order`,
`vlmax`) into parameter memory via `WriteParam` and referencing it from kinstrs by
`paramIdx`. That's infrastructure work — param-memory slot allocation in the lamlet, a python
`WriteParamInstr` kinstr, and a vtype-entry layout shared across every vector kinstr. It
belongs with the broader kinstr bit-budget cleanup tracked in `docs/TODO.md`, not this plan.

`RegSlide` lands as python-only, matching `RegGather`'s current state. Encoding is deferred
until the unified vtype-param-mem design is done.

### `vrgather.vx` / `vrgather.vi` — pure lamlet decomposition

No new kinstr. The lamlet does the element fetch itself via the existing
`oamlet.read_register_element(vreg, element_index, element_width)` primitive
(`python/zamlet/oamlet/oamlet.py:432`), then issues a `VBroadcastOp` with the returned value.

Flow for `vrgather.vx vd, vs2, rs1`:
1. Wait on `x[rs1]`, read index.
2. If `idx ≥ vlmax`: emit `VBroadcastOp(dst=vd, scalar=0, ...)`.
3. Else: `await read_register_element(vs2, idx, sew)`, then `VBroadcastOp(scalar=value)`.

`vrgather.vi` is the same with the immediate in place of `rs1`.

### `vslide1up.vx` / `vslide1down.vx` — lamlet decomposition

No new kinstr. Decompose at the lamlet into:
1. `VmvSx`-equivalent write of the scalar into lane 0 (for `slide1up`) or lane `vl-1` (for
   `slide1down`) of a scratch vreg.
2. `RegSlide` by 1 with source = `vs2` and destination = `vd`, with the scratch lane supplying
   the inject value via the "tail-undisturbed / fill-with-scalar" merge.

Exact sequencing needs to be worked out when we get to this item; the fallback is writing the
scalar directly to the correct lane of `vd` after the slide. Either way no new kinstr.

### `vrgatherei16.vv` — decoder wiring only

`RegGather` already carries separate `index_ew` and `data_ew` fields, and
`lamlet/vregister.vrgather()` passes them through. `vrgatherei16.vv` is `vrgather.vv` with
`index_ew = 16` regardless of SEW. Implementation is a decoder case and a small RISC-V
instruction class that calls the same lamlet dispatch with `index_ew=16`.

## Implementation Order

1. ✓ `RegSlide` kinstr (`transactions/reg_slide.py`), modeled on `transactions/reg_gather.py`.
2. ✓ Lamlet dispatch `vslide()` (`lamlet/vregister.py`), modeled on `vrgather`.
3. ✓ `Vslide` RISC-V class (`instructions/vector.py`) for `.vx` and `.vi`, both directions
   (up/down folded into one class with a `direction: SlideDirection` field).
4. ✓ Decode (`decode.py`) — OPIVX funct3=100 and OPIVI funct3=011, funct6 0x0E (up), 0x0F
   (down).
5. ✓ Unit tests for slides — `python/zamlet/tests/test_reg_slide.py`, parameterized over
   kind × direction × data_ew × vl × offset.
6. **FFT unblocked here.** The N=32 and larger FFT tests progress past the slide decode error.
7. ✓ `Vrgather.vx` / `Vrgather.vi` — `VrgatherVxVi` class, lamlet decomposition via
   `ReadRegWord` + `VBroadcastOp` (async broadcast from `LamletWaitingVrgatherBroadcast`).
   Decoder wiring. Test: `test_reg_gather_vx_vi.py`.
8. ✓ `Vrgatherei16.vv` — same `Vrgather` class with `index_ew_fixed=16` (no separate class;
   `RegGather` already carried independent `index_ew` / `data_ew`). Decoder wiring.
   Covered by `test_reg_gather`'s arbitrary `(data_ew, index_ew)` sweep.
9. ✓ `Vslide1up.vx` / `Vslide1down.vx` — `Vslide1` class (up/down folded together).
   Decomposes to `_dispatch_vslide(offset=1)` + `WriteRegElement` at the boundary lane with
   the scalar truncated to SEW. Tested alongside the other slides in `test_reg_slide.py`.
   Currently unmasked-only (asserts `vm=1`).

## Testing

- New focused unit tests for each instruction, following the pattern of existing tests in
  `python/zamlet/tests/` (name conventions parameterize geometry, ew, vl, seed).
- Cross-check against expected RVV semantics: tail-undisturbed for slideup, out-of-range zeros
  for slidedown, constant-index broadcast for `vrgather.v{x,i}`, 16-bit-index path for
  `vrgatherei16`.
- Re-run FFT N=32 across the 6 geometries after step 6.

## Follow-ups

- Masked `vslide1up.vx` / `vslide1down.vx` (`Vslide1` currently asserts `vm=1`). The
  boundary-lane scalar injection needs to read `v0[inject_idx]` at the lamlet before issuing
  the `WriteRegElement`.
- `vfmv.f.s`, `vfmv.s.f` — FP scalar moves. Needed before `vfslide1*`.
- `vfslide1up.vf`, `vfslide1down.vf` — waiting on `VfmvSf`; pick up when a kernel forces them.
- `vcompress.vm` — prefix-sum-based, separate kinstr needed.
- Chisel-compatible 64-bit encoding for `RegSlide` (and the existing `RegGather`,
  `VArithV{v,x}Op`, etc.): see `docs/TODO.md` "Kinstruction bit-budget cleanup". Likely
  requires a vtype-param-memory scheme (`WriteParam` holding `data_ew + lmul + word_order +
  vlmax`, referenced by `paramIdx` from every vector kinstr).
- Non-overlap checking for slides (vd vs vs2) and vstart behavior (no-op if `vstart ≥ vl`).
