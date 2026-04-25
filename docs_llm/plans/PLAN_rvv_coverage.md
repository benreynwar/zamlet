# PLAN: full RVV spec coverage in the Python model

Umbrella for milestone 1 of `docs_llm/ROADMAP.md` ("Python model covers the
full RVV spec"). This file is an index and ordering — the *what* and *why*
for each item lives in the existing per-feature `PLAN_*.md`, in
`docs_llm/TODO.md`, or in the per-category trackers under
`python/zamlet/plan/0[1-9]_*.txt` and `1[0-2]_*.txt`.

Phases below are ordered by dependency, not by size. Within a phase items can
be picked up in any order unless noted.

## Phase 1 — Cross-cutting cleanup

These touch the same APIs that later phases extend; landing them first avoids
churn in the bigger items.

- [ ] `final_index` / `n_elements` rename across lamlet/oamlet/transaction
      APIs. `docs_llm/TODO.md` lines 59–68. Use `final_index` for exclusive
      end, `n_elements` for count; today both conventions appear in
      `lamlet/unordered.py` and make trap-resume / vstart fragile.
- [ ] `vstart`-on-entry resume across every kinstr. `TODO.md` lines 46–58.
      Audit list: `VBroadcastOp`, `VidOp`, `VArithV{v,x}Op`, `VCmpV{i,x,v}Op`,
      `VUnaryOvOp`, `VmergeVvm`/`VmergeVim`/`VmergeVx`, `VreductionOp`,
      `vloadstore`, slides, scalar moves. Today the toolchain zeros vstart
      so the bug is silent; phase 5 fault-only-first will exercise it.
- [ ] `vstart >= vl` no-op + register-group overlap checks for Ov classes,
      slides, gathers. `TODO.md` line 112.

## Phase 2 — Local single-op gaps (no infra)

Pure decode + per-jamlet execution. No new transactions, no cross-jamlet
plumbing. Knocks out a chunk of the coverage map quickly.

- [ ] Integer min/max element-wise: `vminu.v{v,x}`, `vmin.v{v,x}`,
      `vmaxu.v{v,x}`, `vmax.v{v,x}`. Tracker `05_integer_arithmetic.txt`
      (MIN/MAX OPERATIONS). Reduction forms already in.
- [ ] High-half multiply: `vmulh.v{v,x}`, `vmulhu.v{v,x}`, `vmulhsu.v{v,x}`.
      Tracker `05_*` (MULTIPLY OPERATIONS).
- [ ] Add-with-carry / sub-with-borrow + mask producers: `vadc`/`vmadc`/
      `vsbc`/`vmsbc` in .vv/.vx/.vi forms. Tracker `05_*` (ADD-WITH-CARRY
      / SUBTRACT-WITH-BORROW). Introduces mask-write-from-arith path.
- [ ] FP compare set: `vmfeq`/`vmfne`/`vmflt`/`vmfle`/`vmfgt`/`vmfge` .vv
      and .vf. Tracker `07_float_arithmetic.txt` (FP COMPARE).
- [ ] `vfclass.v`. Tracker `07_*` (FP CLASSIFY).
- [ ] `vfmerge.vfm`, `vfmv.v.f`. Tracker `07_*` (FP MERGE/MOVE).
- [ ] `vsetvl` (register-source vtype). Tracker `01_configuration.txt`.
- [ ] Masked `vslide1up.vx` / `vslide1down.vx`. `TODO.md` line 110.
      Boundary-lane scalar inject under v0.
- [ ] Narrowing shifts done properly: `vnsrl.wv`/`vnsrl.wx`, all three
      `vnsra.w{v,x,i}` forms. `TODO.md` line 69. Currently only
      `vnsrl.wi` is hacked into `VUnaryOvOp`.
- [ ] `vlm.v` / `vsm.v` (mask byte load/store). Tracker
      `02_memory_unit_stride.txt`.
- [ ] `vlenb` CSR exposure. Tracker `01_*`.
- [ ] Widening-arith finishing touches. `docs_llm/plans/PLAN_widening_vector_arith.md`.

## Phase 3 — Long-latency ALU framework

Single biggest enabler. Lands the per-jamlet pipe model + the
`rm`/`fflags`/`vxsat` framework that fixed-point and FP correctness
both ride on.

- [ ] Implement `docs_llm/plans/PLAN_long_latency_alu.md` in full.
      Includes:
      - per-jamlet pipes (int_alu / imul / idiv / fma) with latency model
        in `WaitingItem` machinery,
      - `rm` input + flag outputs on the ALU waiting item,
      - per-jamlet sticky `fflags` / `vxsat` accumulators,
      - sync-network OR-reduce primitive (shared between fflags and vxsat),
      - CSR slots for `vxrm` / `vxsat` / `fcsr`.
- [ ] Ops that ride the framework (drop the ⚠ marks in `07_*` / `08_*`
      once they have proper rm/fflags/latency):
      - [ ] `vdiv.v{v,x}`, `vdivu.v{v,x}`, `vrem.v{v,x}`, `vremu.v{v,x}`
        (radix-2 SRT, dedicated idiv unit).
      - [ ] `vfdiv.v{v,f}`, `vfrdiv.vf` (Newton-Raphson on FMA pipe).
      - [ ] `vfsqrt.v` (Newton-Raphson on FMA pipe).
      - [ ] `vfrec7.v`, `vfrsqrt7.v` (ROM lookup; the seed stage exposed
        as instructions).

## Phase 4 — VTA/VMA partial-vline serialization

Cross-cutting allocator change. Land before phase 8 ew-remap so the two
cleanups don't fight.

- [ ] Implement `docs_llm/plans/PLAN_vta_vma.md` in full. Lets the rename
      allocator pick `w() + fill-with-1s` instead of forcing `rw()` on
      every partial-vline write; unblocks pipelining of partial-vl tail
      iterations. Plumb `vta`/`vma` through every vector op.

## Phase 5 — Big spec areas built on Phases 1+3+4

- [ ] **Fixed-point chapter** (`12_fixed_point.txt`, 33 ops, 0% today).
      Depends on Phase 3 (`vxrm`/`vxsat`/`rm_in`/sticky/OR-reduce). Spec
      ref: `riscv-isa-manual/src/v-st-ext.adoc` chapter 13.
      - [ ] `vxrm` / `vxsat` CSRs wired (stubs at
        `instructions/system.py:23-25`).
      - [ ] Saturating add/sub: `vsaddu`/`vsadd`/`vssubu`/`vssub` in
        .vv/.vx (+ .vi where applicable).
      - [ ] Averaging add/sub: `vaaddu`/`vaadd`/`vasubu`/`vasub`.
      - [ ] Saturating fractional multiply: `vsmul.v{v,x}`.
      - [ ] Scaling shifts: `vssrl.v{v,x,i}`, `vssra.v{v,x,i}`.
      - [ ] Narrowing clip: `vnclip.w{v,x,i}`, `vnclipu.w{v,x,i}`.
- [ ] **Non-unit-stride segment ops**. `TODO.md` lines 115–156, tracker
      `04_memory_segment.txt`. Spec ref:
      `riscv-isa-manual/src/v-st-ext.adoc` lines 1758–1957.
      - [ ] Path (a) — fast path for nf ∈ {2,4,8} as wide-ew load with
        new ew=128/256/512. Covers vlsseg / vssseg /
        vluxseg / vsuxseg / vloxseg / vsoxseg in those nf values. Touches
        address generator, page-tag bookkeeping (page ews 128/256/512
        legal), hazard tracking on coupled register groups.
      - [ ] Path (b) — slow path for nf ∈ {3,5,6,7} as nf strided passes.
- [ ] **Fault-only-first loads**. `TODO.md` line 141. Depends on Phase 1
      vstart resume + trap delivery (already in).
      - [ ] `vle8ff.v` / `vle16ff.v` / `vle32ff.v` / `vle64ff.v`.
      - [ ] `vlseg*ff.v` once segment fast path lands.
- [ ] ew remap on partial write with mismatched-ew old contents.
      `TODO.md` line 73.

## Phase 6 — Permutation / reductions completion

- [ ] **`viota.m`**. Tracker `10_mask_operations.txt`,
      `docs_llm/plans/PLAN_viota_vcompress.md`. Needs new
      `PrefixSumRound` kinstr + `WaitingPrefixSumRound` transaction
      (cross-jamlet scan, log₂(j_in_l) rounds). New piece of cross-jamlet
      infra; doesn't gate anything else.
- [ ] **`vcompress.vm`**. Same plan. Uses viota result + `RegScatter`.
- [ ] **Ordered FP reductions**: `vfredosum.vs`, `vfwredosum.vs`.
      `TODO.md` line 105. Spec allows tree implementation as a valid impl,
      so cheapest is to alias to the unordered tree; if we want strict
      left-to-right, do the serial chain.

## Phase 7 — FP correctness

- [ ] Implement `docs_llm/plans/PLAN_fp_nan_boxing.md` in full. Phase 3
      has already landed the accumulation path; only per-op `fflags_out`
      population and the soft-float reference need to land here.
      - [ ] NaN-boxing: thread `width: int` through `scalar.read_freg` /
        `write_freg` / `write_freg_future`. Fix `FmvWX`, `Flw`,
        `_write_fp`, `_write_fp_bits`, `FCvt` (F32 dst); `_read_fp`,
        `_read_fp_bits`, `FCvt` (F32 src); `VArithVxFloat` and any future
        `.vf` forms; `vfmv.f.s`, `vfmv.s.f`, `vfslide1*`. `TODO.md` line 83.
      - [ ] `FCvt` rounding mode: dynamic-rm lookup, replace host
        `int()` truncation. `TODO.md` line 96.
      - [ ] NaN payload + per-element fflags via soft-float reference
        (SoftFloat-3 port or mpmath). `TODO.md` lines 98–104.

## Phase 8 — Per-vline ew completion

- [ ] Implement `docs_llm/plans/PLAN_per_vline_ew.md` steps 4–7 (steps 1–3
      done).
      - [ ] Step 4: merge VPU memory pools.
      - [ ] Steps 5–7: VPU-stack placement for spills, etc.
- [ ] ew remap infrastructure. `TODO.md` lines 17–45.
      - [ ] Dedicated J2J ew-remap kinstr (no memory round-trip).
      - [ ] ew=1 native aligned unit-stride load/store; misaligned/strided/
        indexed ew=1 falls into a lamlet fault remap path.
      - [ ] Plumb `ensure_mask_ew1(reg)` at every mask-consumer site (drop
        the asserts added alongside `VmLogicMm`).
      - [ ] Drop the manual ew=1 retag at the end of
        `tests/test_utils.py:setup_mask_register`.
      - [ ] Staggered J2J schedule so neither read nor write port is
        one-sided on small↔large remaps.
- [ ] Page-system updates for max pseudo-ew = 512 (consequence of segment
      fast path): minimum page size, page-tag bookkeeping, mixed-ew access
      remap rules. `TODO.md` lines 144–156.

## Phase 9 — Housekeeping

- [ ] **Fence**: decode-and-no-op (`TODO.md` line 180) — correct for
      current single-hart no-DMA system. Real drain ("wait for all
      outstanding completion syncs to fire") waits until there's an
      external memory agent.
- [ ] **Kinstr bit-budget cleanup** (`TODO.md` line 190): proper
      `FIELD_SPECS` / `encode()` for python-only kinstrs, opcodes for
      `IndexedInstr` family, drop dead `LoadStride` / `StoreStride`
      classes, mask-field representation for `WordInstr` / `J2JInstr` /
      `StoreScalarInstr`.
- [ ] **Packet header bit packing** (`TODO.md` line 12): resolve 64-bit
      header overflow in `ReadMemWordHeader` / `WriteMemWordHeader`.
- [ ] Recreate `tests/test_vms_first_mask.py` (deleted from disk despite
      `vmsbf`/`vmsif`/`vmsof` impl having landed in commit `4d28467`).
      Sibling patterns in `tests/test_vfirst.py`, `tests/test_vcpop.py`.
      Re-enable in `tests/BUILD`.

## PR-sized chunks and dependencies

Each chunk below is intended as a single PR (or a small series). "Depends on"
means the listed chunk must merge before this one can be made green. Chunks
with no listed dependency can start immediately.

The phase narrative above explains *why* the order is what it is; this
section is the *what to build next* view.

### Critical path

`A1 → A2 → I1` (cross-cutting cleanup → fault-only-first scalar) is the
longest sequential chain. `B1 → G0 → G1..G4` (ALU framework → fixed-point
chapter) is the next. Everything else can run alongside these.

### A. Cross-cutting cleanup

- **A1** — `final_index` / `n_elements` rename across lamlet/oamlet/transaction
  APIs (`TODO.md` L59).
  Depends: none.
  Mechanical but cross-cutting; lands first to make A2 / I1 tractable.
- **A2** — `vstart`-on-entry resume audit + fix (`TODO.md` L46).
  Depends: A1.
  Large surface (every kinstr's `execute()` and `alloc_dst_pregs()`); may
  split per kinstr family.
- **A3** — `vstart >= vl` no-op + register-group overlap checks for Ov /
  slides / gathers (`TODO.md` L112).
  Depends: A1 (light — could land in parallel with A2).

### B. Long-latency ALU framework

- **B1** — Framework PR per `PLAN_long_latency_alu.md`: per-jamlet pipes,
  `WaitingItem` extensions, sync OR-reduce primitive, `vxrm` / `vxsat` /
  `fcsr` CSR slots, all single-cycle ops re-routed onto framework as
  latency-1 baseline.
  Depends: none. Big PR; do not split (the whole point is uniform plumbing).
- **B2** — `vdiv` / `vdivu` / `vrem` / `vremu` (idiv pipe, radix-2 SRT).
  Depends: B1.
- **B3** — `vfdiv` / `vfrdiv` / `vfsqrt` (Newton-Raphson on FMA pipe).
  Depends: B1.
- **B4** — `vfrec7.v` / `vfrsqrt7.v` (ROM lookup).
  Depends: B1.

B2 / B3 / B4 are mutually independent.

### C. Single-op gaps (Phase 2)

All independent of each other and of A / B / D.

- **C1** — integer min/max element-wise (`vminu` / `vmin` / `vmaxu` / `vmax`
  .vv/.vx).
- **C2** — high-half multiply (`vmulh` / `vmulhu` / `vmulhsu` .vv/.vx).
- **C3** — carry/borrow ops (`vadc` / `vmadc` / `vsbc` / `vmsbc` in .vv/.vx
  /.vi).
  Introduces mask-write-from-arith path; do .vv first then siblings reuse.
- **C4** — FP compare set (`vmfeq` / `vmfne` / `vmflt` / `vmfle` / `vmfgt` /
  `vmfge`) + `vfclass.v`.
- **C5** — `vfmerge.vfm` + `vfmv.v.f`.
- **C6** — `vsetvl` (register-source vtype) + `vlenb` CSR + `vlm.v` /
  `vsm.v`.
- **C7** — masked `vslide1up.vx` / `vslide1down.vx` (`TODO.md` L110).
- **C8** — narrowing shifts done properly: `vnsrl.wv` / `vnsrl.wx` and all
  three `vnsra.w{v,x,i}` (`TODO.md` L69).
  Needs design decision on where they live; currently `vnsrl.wi` is hacked
  into `VUnaryOvOp`.
- **C9** — widening-arith finishing touches per
  `PLAN_widening_vector_arith.md` (doc drift on `ensure_vrf_ordering`).

### D. Permutation + ordered reductions (Phase 6)

- **D1** — `viota.m` + new `PrefixSumRound` kinstr +
  `WaitingPrefixSumRound` transaction.
  Depends: none.
- **D2** — `vcompress.vm` (uses viota result + `RegScatter`).
  Depends: D1.
- **D3** — ordered FP reductions (`vfredosum.vs`, `vfwredosum.vs`).
  Depends: none.
  Cheapest path: alias to unordered tree (spec-permitted); serial chain if
  we want strict left-to-right.

### E. Housekeeping (Phase 9)

All independent.

- **E1** — recreate `tests/test_vms_first_mask.py` and re-enable in
  `tests/BUILD`. Sibling patterns in `tests/test_vfirst.py` /
  `tests/test_vcpop.py`.
- **E2** — fence decode-and-no-op (`TODO.md` L180).
- **E3** — kinstr bit-budget cleanup (`TODO.md` L190).
  May split: opcode allocation for `IndexedInstr` family is one PR,
  `FIELD_SPECS` / `encode()` for python-only kinstrs another, dead
  `LoadStride` / `StoreStride` deletion a third.
- **E4** — packet header bit packing (`TODO.md` L12).

### F. VTA/VMA (Phase 4)

- **F1** — `PLAN_vta_vma.md` full implementation.
  Depends: none.
  Large; splittable as: (i) thread `vta` / `vma` through kinstr/decode
  with no behavior change, (ii) allocator change (rename picks
  `w() + fill-with-1s`), (iii) drop per-op `rw()` forcing now that allocator
  is smarter. Must land before L1–L7 (per-vline ew completion) so the two
  allocator-touching efforts don't fight.

### G. Fixed-point chapter (Phase 5)

- **G0** — `vxrm` / `vxsat` CSR wiring (stubs at
  `instructions/system.py:23-25` → real OR-reduce-on-read).
  Depends: B1.
- **G1** — saturating add/sub (`vsaddu` / `vsadd` / `vssubu` / `vssub` in
  .vv/.vx and .vi where applicable).
  Depends: G0.
- **G2** — averaging add/sub (`vaaddu` / `vaadd` / `vasubu` / `vasub`).
  Depends: G0.
- **G3** — saturating fractional multiply + scaling shifts (`vsmul.v{v,x}`,
  `vssrl.v{v,x,i}`, `vssra.v{v,x,i}`).
  Depends: G0.
- **G4** — narrowing clip (`vnclip.w{v,x,i}`, `vnclipu.w{v,x,i}`).
  Depends: G0.

G1 / G2 / G3 / G4 are mutually independent.

### H. Segment non-unit-stride (Phase 5)

- **H1** — Path-(b) slow path: nf ∈ {3,5,6,7} via nf strided passes for
  `vlsseg` / `vssseg` / `vluxseg` / `vsuxseg` / `vloxseg` / `vsoxseg`.
  Depends: none.
  Lands first to get correctness coverage on awkward nf values; performance
  is nf×.
- **H2** — Page-system updates for max pseudo-ew=512 (min page size,
  page-tag bookkeeping for ew=128/256/512, mixed-ew remap rules)
  (`TODO.md` L144–156).
  Depends: none.
  Prerequisite for H3; could land standalone since the new ews are legal
  even before any op uses them.
- **H3** — Path-(a) fast-path framework: address generator burst-per-element
  mode + register-group hazard tracking (`vd mod nf == 0`, `EMUL * nf <= 8`)
  + writeback fan-out routing.
  Depends: H2.
- **H4** — `vlsseg` / `vluxseg` / `vloxseg` fast-path variants for
  nf ∈ {2,4,8}.
  Depends: H3.
- **H5** — `vssseg` / `vsuxseg` / `vsoxseg` fast-path variants for
  nf ∈ {2,4,8}.
  Depends: H3.

### I. Fault-only-first (Phase 5)

- **I1** — `vle8ff.v` / `vle16ff.v` / `vle32ff.v` / `vle64ff.v`
  (`TODO.md` L141).
  Depends: A2.
- **I2** — `vlseg*ff.v` variants for the relevant nf.
  Depends: I1, plus H4 (fast path) for nf ∈ {2,4,8} or H1 (slow path) for
  nf ∈ {3,5,6,7}.

### J. ew remap on partial-write with mismatched-ew old contents

- **J1** — `TODO.md` L73.
  Depends: none.

### K. FP correctness (Phase 7)

- **K1** — `FCvt` rounding mode: dynamic-rm lookup, replace host `int()`
  truncation (`TODO.md` L96).
  Depends: B1.
- **K2** — NaN-boxing pass through `scalar.read_freg` / `write_freg` /
  `write_freg_future` and every consumer site (`TODO.md` L83,
  `PLAN_fp_nan_boxing.md`).
  Depends: B1 (light — could land in parallel; framework just makes the
  width plumbing easier).
- **K3** — soft-float reference + per-op `fflags_out` population
  (`TODO.md` L98).
  Depends: B1.
  Largest in K series; may split per op family.

### L. Per-vline ew completion (Phase 8)

- **L1** — `PLAN_per_vline_ew.md` step 4: merge VPU memory pools.
  Depends: F1.
- **L2** — `PLAN_per_vline_ew.md` steps 5–7: VPU-stack placement for spills.
  Depends: L1.
- **L3** — Dedicated J2J ew-remap kinstr (no memory round-trip)
  (`TODO.md` L17 (a)).
  Depends: F1.
- **L4** — ew=1 native aligned unit-stride load/store (`TODO.md` L17 (b)).
  Depends: L3.
- **L5** — Plumb `ensure_mask_ew1(reg)` at every mask-consumer site; drop
  the asserts added alongside `VmLogicMm` (`TODO.md` L17 (c)).
  Depends: L3.
- **L6** — Drop manual ew=1 retag at end of
  `tests/test_utils.py:setup_mask_register` (`TODO.md` L17 (d)).
  Depends: L4.
- **L7** — Staggered J2J schedule for small↔large remaps
  (`TODO.md` L17 (e)).
  Depends: L3.

### Ready-to-start (chunks with no upstream deps)

- **A1** (cleanup), **B1** (framework), **C1**–**C9** (single-op gaps),
  **D1** (viota), **D3** (ordered FP reductions), **E1**–**E4**
  (housekeeping), **F1** (VTA/VMA), **H1** (segment slow path), **H2**
  (page-system max-ew=512), **J1** (ew partial-write remap).

That's 20+ chunks that can be picked up in any order from a fresh start.

### Merge-conflict hotspots

- **`python/zamlet/decode.py`** — every C / D / G / H / I op edits this. Safe
  for parallel work because ops use different funct6/funct3 dispatch lines,
  but expect to rebase the dispatch table.
- **`python/zamlet/kamlet/kinstructions.py`** — new kinstr classes; safe
  since classes don't overlap.
- **`python/zamlet/instructions/vector.py`** — new wrapper classes; safe.
- **`python/zamlet/lamlet/unordered.py`** — A2 (vstart resume), G1–G4
  (fixed-point), H3–H5 (segment fast path) all want to edit this. Stagger
  or rebase.
- **`WaitingItem` hierarchy** — B1 (framework), D1 (`PrefixSumRound`),
  H3 (segment fast path) may overlap. B1 should land first if any of these
  are concurrent.
- **rename allocator** — F1 (VTA/VMA) and L1–L7 (per-vline ew completion)
  both edit it. F1 first.

## Per-category trackers (ground truth for spec coverage)

When picking up an item, the per-category tracker is the per-instruction
status of record. Update the tracker's `Status: ✓/⚠/✗` and Implementation
Summary in the same change as the kinstr lands.

- `01_configuration.txt`
- `02_memory_unit_stride.txt`
- `03_memory_strided_indexed.txt`
- `04_memory_segment.txt`
- `05_integer_arithmetic.txt`
- `06_integer_widening_narrowing.txt`
- `07_float_arithmetic.txt`
- `08_float_widening_conversions.txt`
- `09_reductions.txt`
- `10_mask_operations.txt`
- `11_permutations.txt`
- `12_fixed_point.txt`
