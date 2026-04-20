# PLAN: mask operations (vcpop, vfirst, vmsbf/vmsif/vmsof, viota)

## Goal

Implement the six RVV mask instructions currently missing from the Python model:

- `vcpop.m rd, vs2, vm` — population count of active mask bits → scalar.
- `vfirst.m rd, vs2, vm` — index of first set bit (or `-1`) → scalar.
- `vmsbf.m vd, vs2, vm` — set bits strictly before first set bit of vs2.
- `vmsif.m vd, vs2, vm` — set bits up to and including first set bit.
- `vmsof.m vd, vs2, vm` — set only the first set bit.
- `viota.m vd, vs2, vm` — **deferred** (needs scan primitive; not on FFT path).

Immediate driver: `vcpop.m` is blocking FFT N=32.

Spec reference: `~/Code/riscv-isa-manual/src/v-st-ext.adoc`, "Vector Mask
Instructions" chapter (lines 4037–4422).

## Key invariants

- Mask instructions operate on a **single vector register regardless of LMUL**
  (spec line 4046–4048). `vl_max` at `ew=1` is bounded by one vline's worth of
  bits (`word_bytes * j_in_l * 8`).
- `vstart == 0` required for all six — raise illegal-instruction otherwise.
- `vcpop.m` / `vfirst.m` must write `x[rd]` even when `vl == 0` (values `0` and
  `-1` respectively).
- **Mask bit layout**: lane `k` (k ∈ [0, J), `J = j_in_l`) owns mask bits at
  global element indices `k, J+k, 2J+k, …`. A lane's bit at local position
  `m` has global element_index `m*J + k`. Any cross-lane aggregation over
  element indices must use the global index, not a within-lane bit position.

## Infrastructure additions

### Sync-network aggregations

The sync network currently aggregates MIN only. Extend aggregation to all
**idempotent** operations across widths `ew ∈ {1, 8, 16, 32}`.

| Op | Input ew | Output ew | Notes |
|---|---|---|---|
| `AND`, `OR` | 1, 8, 16, 32 | same as input | bitwise per-element |
| `MIN`, `MINU`, `MAX`, `MAXU` | 8, 16, 32 | same as input | signed/unsigned |
| `MIN_EL_INDEX`, `MAX_EL_INDEX` | 1 only | 32 | register-wide scan |

Aggregate is delivered directly to every jamlet and to the lamlet (no
rebroadcast needed). `MIN_EL_INDEX` with no set bit returns sentinel
`0xFFFFFFFF` (`= -1` signed, `= UINT32_MAX` unsigned). `MAX_EL_INDEX` with no
set bit returns sentinel `0`.

`MIN_EL_INDEX` / `MAX_EL_INDEX` report the **global RVV element_index**
(= `local_position * J + lane_id`) of the selected set bit, not the
within-lane bit position. Each lane's local contribution is computed with
that mapping before the cross-lane min/max.

`SUM` is **not** supported by the sync network (not idempotent). SUM reductions
go through the existing tree decomposition in `oamlet/reduction.py`.

### New kinstrs

**`ReduceSync`** — cross-jamlet idempotent reduction via sync network.
Parameters: `src` vreg, `dst` vreg, `op`, `ew`. Writes the aggregate to every
word of `dst` on every jamlet; lamlet also captures it.

**`MaskPopcountLocal`** (ew=1 → ew=32) — per-jamlet popcount of active mask
bits in `src`. Writes one 32-bit count per word of `dst`. Only needed by
`vcpop.m`.

**`SetMaskBits`** (ew=32 → ew=1) — reads a vreg where every word holds the
same `value`. For each destination mask bit, `i` is the bit's **global RVV
element_index** (= `local_position * J + lane_id`); the kinstr writes an
**unsigned** comparison: `LT` → `i < value`, `LE` → `i <= value`,
`EQ` → `i == value`.

## Instruction decompositions

Handled in a new `oamlet/mask_ops.py` that mirrors `oamlet/reduction.py`.
Masked form (`vm=0`) is a frontend decompose step: pre-AND `vs2` with `v0`
into a temp via existing `vmand.mm`, then run the rest on the temp.

```
# Prelude common to all decompositions:
if masked (vm == 0):
    VmLogicMm(tmp_mask, vs2, v0, AND)
    src = tmp_mask
else:
    src = vs2

# vcpop.m rd, vs2, vm
MaskPopcountLocal(src, tmp32)            # per-jamlet popcount, ew=32
tree_reduce_sum(tmp32, rd)               # existing reduction.py SUM path

# vfirst.m rd, vs2, vm
ReduceSync(src, tmp32, MIN_EL_INDEX, ew=1)
rd <- tmp32[word 0]                      # sentinel 0xFFFFFFFF = -1 signed

# vmsbf.m / vmsif.m / vmsof.m vd, vs2, vm
ReduceSync(src, valvec, MIN_EL_INDEX, ew=1)
SetMaskBits(valvec, vd, mode)
    # vmsbf -> LT  (all 1s when no bit set, since 0xFFFFFFFF is max)
    # vmsif -> LE
    # vmsof -> EQ  (all 0s when no bit set)
```

Sentinel + unsigned-compare semantics make the "no set bit" edge cases fall
out without any lamlet-side branching on the aggregate (which the lamlet
couldn't observe in time anyway).

## Work order

1. Extend sync-network aggregations to the idempotent op set + `ew ∈ {1,8,16,32}`.
2. Add `ReduceSync` kinstr + focused unit test.
3. Add `MaskPopcountLocal` kinstr + focused unit test.
4. Implement `vcpop.m` (decode + instruction class + `mask_ops.py` entry).
   Run FFT N=32 — primary success criterion for this step.
5. Implement `vfirst.m` (reuses `ReduceSync(MIN_EL_INDEX)`).
6. Add `SetMaskBits` kinstr + test. Implement `vmsbf.m` / `vmsif.m` / `vmsof.m`.
7. Mark `viota.m` deferred in `python/zamlet/plan/10_mask_operations.txt` with
   rationale (needs scan primitive; only critical for `vcompress`).

## Deferred / future work

- `viota.m` — parallel prefix sum over active mask bits. Requires a scan
  primitive (intra-jamlet local scan + cross-jamlet prefix-sum). Only needed
  by `vcompress.vm` (separate kinstr) and by compiler autovectorization of
  compress-like patterns. Revisit when `vcompress` is prioritised.
- Ordered FP reductions (`vfredosum.vs`, `vfwredosum.vs`) — separate from this
  plan, tracked in `09_reductions.txt`.
- Consolidate other existing cross-jamlet MIN/MAX reductions onto `ReduceSync`
  once it lands, if cheaper than the current tree decomposition.
