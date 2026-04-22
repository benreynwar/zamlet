# PLAN: viota.m and vcompress.vm

Replaces the older `python/zamlet/plan/VCOMPRESS_PLAN.md`, which predates our
current sync-network / mask-ops direction and had an incomplete treatment of
the striped mask layout.

## Status

Both instructions are **deferred** — not on the FFT critical path. This plan
captures the design intent so we don't re-derive it from scratch when they
come up. Pick it up when autovectorised code starts generating compress
patterns (e.g. pruning zero lanes in FHE kernels).

## Goal

- `viota.m vd, vs2, vm` — for each active element `i`, `vd[i] = popcount(vs2 & vm).mask[0..i-1]`.
- `vcompress.vm vd, vs2, vs1` — for each `i` where `vs1.mask[i] == 1`, place
  `vs2[i]` at position `popcount(vs1.mask[0..i-1])` in `vd`. Tail positions
  are tail-agnostic.

Both require a parallel prefix-sum over mask bits. `vcompress` additionally
requires a reg-to-reg scatter.

## Layout constraint (drives the whole design)

Lane `k` (k ∈ [0, J), `J = j_in_l`) owns mask/data elements at global indices
`k, J+k, 2J+k, …`. A lane's element at local position `m` has global index
`m*J + k`. A contiguous global index range `[0, i)` is spread across every
lane — no lane owns a contiguous slice.

## Required primitives

Three new primitives, each useful beyond these two instructions:

1. **J-wide cross-lane exclusive prefix scan** (1 bit per lane → 32 bits per lane).
   - Classic Hillis-Steele upsweep over lanes: `log₂(J)` rounds, each round
     has lanes with `k >= 2^d` add the value from lane `k − 2^d`.
   - Cross-lane communication uses the sync network / J2J messaging (the
     broadcast pattern sketched in the old VCOMPRESS_PLAN as
     `PrefixSumRound`, but framed as a general primitive rather than
     per-instruction machinery).
   - This primitive alone gives us a "J-wide viota" (`vl ≤ J`) which is a
     useful sub-case and a good first milestone.

2. **Intra-lane exclusive prefix scan over mask bits** (ew=1 → ew=32).
   - Each lane independently computes `S_k[m] = popcount(lane k's bits at
     positions 0..m-1)` for all `m ∈ [0, W]`, where `W = word_bytes * 8`.
   - Serial within a lane; no cross-lane traffic.

3. **Reg-to-reg indexed scatter across lanes** (inverse of `vrgather`).
   - `dst[idx[i]] = src[i]` for active `i`, where `idx[i]` names a global
     element index; routing crosses lanes.
   - Study the existing `vrgather` cross-lane code first — this is the
     inverse and probably mirrors its routing layer.

## viota.m decomposition

Using the striped-layout algebra (derived in chat):

```
viota[i] where i = local_j * J + k_out
       = sum_k S_k[local_j]                          # bits at positions 0..local_j-1, all lanes
       + sum_{k<k_out} mask_k[local_j]               # bits at position local_j in lanes before k_out
```

So:
1. Intra-lane scan → per-lane `S_k[m]` array (primitive 2).
2. Cross-lane SUM of `S_k` (existing tree-reduce SUM, pointwise across `m`)
   → array `A[m]` replicated on every lane.
3. For each position `m`, cross-lane exclusive prefix of mask bit at that
   position → per-lane `B_k[m]` (primitive 1, applied `W` times — or fused
   into an element-wise version as a later optimisation).
4. `vd[i] = A[local_j] + B_{k_out}[local_j]` — simple `VArithVv` ADD.

Incremental milestones:
- **Milestone A**: J-wide viota (`vl ≤ J`) — exercises primitive 1 in isolation.
- **Milestone B**: general viota — adds primitives 2 + 3 and the sum.

## vcompress.vm decomposition

```
idx = viota(vs1)                       # primitives 1+2 from above
scatter(src=vs2, dst=vd, indices=idx, mask=vs1)   # primitive 3
```

All three primitives reused. Tail handling is tail-agnostic past
`popcount(vs1)`; no explicit tail-fill needed under current tail policy.

## Related instructions already handled

- Permutation family is ~95% complete (`vrgather.vv/.vx/.vi/ei16`, all slides,
  scalar moves, register moves) — see `python/zamlet/plan/11_permutations.txt`.
  Only `vcompress.vm` remains in that family.
- `vdecompress` is not a real instruction — it's synthesised from
  `viota.m + vrgather.vv`. It comes for free once `viota.m` lands.

## Relation to the mask-ops plan

`docs/PLAN_mask_ops.md` lays down the sync-network extensions (idempotent ops,
`ew ∈ {1,8,16,32}`) and the `ReduceSync` / `MaskPopcountLocal` / `SetMaskBits`
kinstrs. Primitive 1 here will use the same cross-lane broadcast mechanism
but is **not** idempotent (SUM is not), so it needs its own kinstr
(tentatively `JWidePrefixSumRound` or similar) rather than riding
`ReduceSync`. It should still share the sync-before-send flow-control
pattern.

## Open questions to revisit when we pick this up

- Is primitive 1 cheaper as `W` serial J-wide scans or as a single
  element-parallel scan over a whole ew=32 vreg? The latter needs
  element-wise cross-lane slides+adds over a full register, which is more
  infrastructure but much lower latency for general viota. Start with
  serial, benchmark, decide.
- Does the scatter primitive want its own flow-control (drop/retry) given
  that multiple source elements can never target the same destination
  (injection from vs1's mask pattern guarantees distinct destinations for
  active elements)? Probably simpler than a general gather.
- Internal ("invisible") physical registers for ping-pong / temp storage:
  does lamlet already have an allocator, or do we use caller-saved
  vregs from a reserved pool?
