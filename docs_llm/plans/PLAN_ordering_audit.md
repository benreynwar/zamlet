# PLAN: vector instruction ordering audit

## Goal

Finish unifying the `ensure_vrf_ordering` / `set_vrf_ordering_for_write` pattern
across every vector instruction class, the load/store helpers they dispatch to,
and the direct-kinstr call sites. Fix the real bugs surfaced by the audit;
leave deliberate deviations (ew=1 direct-stamp, fresh-temp-reg direct-stamp)
alone until the ew=1 remap infrastructure lands.

Driver: RESTART.md item 1 — load/store remap unification. The vmv.v.v
masked-slide FFT failure (item 3 in RESTART.md) sits downstream of this and is
tracked separately.

## Reference matrix

From RESTART.md §1; the pattern every vector op should follow:

| Role | Fix |
|---|---|
| any src read (ALU src, index, mask, all store srcs) | `ensure_vrf_ordering` (in-place) |
| dst full write | `set_vrf_ordering_for_write` (stamp only) |
| dst partial write | `set_vrf_ordering_for_write` (remap then stamp) |

Reference dispatch class: `VArithVv.update_state` at
`python/zamlet/instructions/vector.py:1991`.

`ensure_vrf_ordering` is in `python/zamlet/oamlet/oamlet.py:403`;
`set_vrf_ordering_for_write` at `:464`.

## Audit status

All classes in `instructions/vector.py` have been walked. Results:

### Real bugs (worth fixing)

**B1. `vloadstore` vl arithmetic — `lamlet/unordered.py:441,445`**

```python
await lamlet.ensure_vrf_ordering(
    reg_base, ordering.ew, parent_span_id,
    vstart=start_index, vl=start_index + n_elements)   # BUG
# ...
await lamlet.ensure_vrf_ordering(
    mask_reg, 1, parent_span_id,
    vstart=start_index, vl=start_index + n_elements)   # BUG
```

Per the helper-family convention (see `oamlet.vload` at `oamlet.py:1605-1607`
passing `vl=n_elements` directly), `n_elements` here already means vl
(exclusive end), not a count. `vl=start_index + n_elements` therefore computes
`vstart + vl`, which overshoots. Fix: replace with `vl=n_elements`.

Same class of bug that `_vloadstore_indexed_unordered` had and has already
been fixed per RESTART.md 1c.

**B2. Ordered indexed load — `lamlet/ordered.py:464` (`vload_indexed_ordered`)**

Missing `ensure_vrf_ordering` on:
- `index_reg` (src read of indices)
- `mask_reg` (src read of mask)

Unordered counterpart has both at `unordered.py:749-760`. Ordered path silently
skips the checks.

**B3. Ordered indexed store — `lamlet/ordered.py:585` (`vstore_indexed_ordered`)**

Missing `ensure_vrf_ordering` on:
- `vs` (data source — stores must ensure data reg matches instr ew)
- `index_reg`
- `mask_reg`

### Missing masked-compare support (pre-existing; out of ordering scope)

**M1. Masked compares silently drop the mask — `VCmpVi/Vv/Vx/VvFloat/VxFloat`**

All five classes accept `vm=0` (producing `,v0.t` in `__str__`) but
`update_state` never reads `self.vm` or threads a `mask_reg` through to
`VCmpViOp/VCmpVvOp/VCmpVxOp`. The masked encoding therefore behaves
identically to the unmasked one.

Should be filed as its own follow-up — distinct from the ordering work but
surfaced by the audit.

### Deliberate deviations from the matrix (leave as-is)

**D1. Direct `s.vrf_ordering[...] = …` stamps instead of `set_vrf_ordering_for_write`:**

- `VCmpVi` (`vector.py:607-608`), `VCmpVv` (`:662-663`), `VCmpVx` (`:718-720`),
  `VCmpVvFloat` (`:786-788`), `VCmpVxFloat` (`:845-847`): dst is a mask at
  ew=1. Consistent with RESTART.md's "ew=1 can't round-trip through memory"
  rule.
- `VmLogicMm` (`:935`): same.
- `VmsFirstMask` (`:1547`): dst is ew=1.
- `VcpopM`, `VfirstM`, `VmsFirstMask` stamp temp regs (accum_ew=32) directly
  at `:1373, :1378, :1479, :1483, :1576, :1580` — OK because `alloc_temp_regs`
  yields fresh regs with no prior ordering, so no remap is needed.
- `VmvNr` (`:1834`): whole-register copy; direct copy of src's ordering to dst.
- `oamlet/reduction.py` temp regs (`:289, :310, :329, :331`): fresh-temp-reg
  argument again.

Keep these until ew=1 remap infrastructure lands. At that point, fold the
ew=1 cases back through `set_vrf_ordering_for_write` so the stamping path is
uniform. Tracked under "ew remap infrastructure" in `docs_llm/TODO.md`.

### Minor / latent (pattern-consistent, fix opportunistically)

**N1. `Vreduction` scalar-accum read — `vector.py:1929`**

Asserts `s.vrf_ordering[self.vs1].ew == accum_ew` instead of calling
`ensure_vrf_ordering(vs1, ...)`. Also missing `await_vreg_write_pending(vs1,
...)`. Strict — fine for current callers, but not general.

**N2. `VmvSx` / `VfmvSf` — `vector.py:1708-1710, 1767-1769`**

Call `ensure_vrf_ordering(vd, ew, vl=1, allow_uninitialized=True)` for a
partial write of element 0, instead of
`set_vrf_ordering_for_write(vd, ew, vstart=0, vl=1, masked=False,
emul=n_vlines)`. Works when `vd`'s ew already matches (no remap needed); the
matrix calls for the write-side helper. RESTART.md's follow-up list already
flags the related vl=1 precision question at this site.

**N3. `VmvNr` concurrency — `vector.py:1804`**

Missing `await_vreg_write_pending` on both src and dst. Other classes wait
before direct-assigning; concurrent writes could race.

### Clean (audited, no findings)

`VleV`, `VlrV`, `VseV`, `VsrV`, `VlseV`, `VsseV` (rely on the audited
`oamlet.vload`/`vstore` path), `VArithVxFloat`, `VmvVi`, `VmvVx`, `VmergeVx`,
`VmergeVvm`, `VmergeVim`, `VmvXs`, `VfmvFs`, `Vid`, `VUnary`, `VArithVv`,
`VArithVvFloat`, `VArithVx`, `VArithVi`, `VArithVvOv`, `VArithVxOv`,
`VIndexedLoad`/`VIndexedStore` (delegate to well-covered unordered path; the
ordered path is B2/B3), `Vslide`, `Vslide1`, `Vrgather`, `VrgatherVxVi`,
`instructions/custom.py`, `instructions/compressed.py`,
`lamlet/vregister.py`, test direct-kinstr sites in
`tests/test_conditional_kamlet.py`.

## Execution order

1. **B1** — `lamlet/unordered.py:441,445`: `vl=start_index + n_elements` →
   `vl=n_elements`. Re-run the smoke tests covering stores:
   `test_strided_store`, `test_indexed_store`, and a vecadd/sgemv kernel.
2. **B2 + B3** — mirror the unordered path's
   `ensure_vrf_ordering(index_reg | mask_reg | src_data_reg, ...)` calls into
   `ordered.py`'s load/store functions. `test_ordered_indexed_load` and
   `test_ordered_indexed_store` are the coverage.
3. Run RESTART.md §2 pytest block to confirm no regressions:

   ```
   nix-shell --run 'python -m pytest \
       python/zamlet/tests/test_widening_arith.py \
       python/zamlet/tests/test_reduction.py \
       python/zamlet/tests/test_vcpop.py \
       python/zamlet/tests/test_vfirst.py \
       python/zamlet/tests/test_reg_slide.py \
       python/zamlet/tests/test_reg_gather.py \
       python/zamlet/tests/test_reg_gather_vx_vi.py \
       python/zamlet/tests/test_vfmv_scalar.py \
       python/zamlet/tests/test_ordered_indexed_load.py \
       python/zamlet/tests/test_indexed_load.py \
       python/zamlet/tests/test_indexed_store.py \
       python/zamlet/tests/test_ordered_indexed_store.py \
       python/zamlet/tests/test_strided_load.py \
       python/zamlet/tests/test_strided_store.py \
       python/zamlet/tests/test_conditional_kamlet.py \
       -x'
   ```

4. **M1** — masked compares: plumb `mask_reg` through
   `VCmpViOp`/`VCmpVvOp`/`VCmpVxOp` kinstrs and the kamlet's compare
   implementation so the `,v0.t` encoding actually gates writes.
5. **N1** — `Vreduction`: replace the `assert vrf_ordering[vs1].ew == accum_ew`
   with `ensure_vrf_ordering(vs1, accum_ew, ...)` and add
   `await_vreg_write_pending(vs1, ...)`.
6. **N2** — `VmvSx` / `VfmvSf`: switch to
   `set_vrf_ordering_for_write(vd, ew, vstart=0, vl=1, masked=False,
   emul=n_vlines)` so the partial-write path goes through the write-side
   helper.
7. **N3** — `VmvNr`: add `await_vreg_write_pending` on src and dst before the
   direct-assign copy.

## Relationship to other plans

- `PLAN_per_vline_ew.md` owns the broader ew-remap / per-vline-ew work. The
  ew=1 deviations (D1) resolve themselves when per-vline-ew Step 4+ extends
  remap to mask registers.
- The vmv.v.v masked-slide failure (RESTART.md §3) is downstream: once this
  audit is clean, the vmv.v.v `dest_ew` parameter change becomes the next
  target.

## Out of scope

- Rewriting `await_vreg_write_pending` to take element ranges (RESTART.md
  follow-ups).
- Renaming `n_elements` → `vl` / `start_index` → `vstart` across the helper
  family (RESTART.md follow-ups; worth doing after B1 lands so the names
  can't mask a repeat of the bug, but mechanical).
- `_vline_is_partial` sign error in `oamlet.py` (RESTART.md follow-ups).
