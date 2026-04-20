# PLAN: vta/vma support in the python model

## Goal

Bring the python model into compliance with the RISC-V vector spec's
tail-agnostic (`vta`) and mask-agnostic (`vma`) policies, and let the kamlet
register rename allocator exploit agnostic regions for better pipelining.

Today the python model implicitly does fully-undisturbed semantics for both
tail and inactive elements. This is spec-legal (the spec note at
`v-st-ext.adoc:390-393` explicitly endorses simple in-order implementations
treating everything as undisturbed) but it forces every partial-vline write to
use `rw()` in the new rename design, which inhibits cross-iteration pipelining
on the partial last vline of any rolled loop where `vl < VLMAX`.

This work adds explicit `vta` / `vma` plumbing and lets the kamlet pick
`w() + fill-with-1s` instead of `rw()` whenever the spec permits.

## Spec background

`v-st-ext.adoc:1058-1102` divides the destination element indices of any
vector instruction into:

- **prestart** (`0 <= x < vstart`) — never written; **always undisturbed**.
  No agnostic option exists for prestart.
- **active** (`vstart <= x < vl AND mask[x]`) — always written.
- **inactive** (`vstart <= x < vl AND !mask[x]`) — controlled by `vtype.vma`.
  - `vma=0`: undisturbed (retain old value).
  - `vma=1`: agnostic — element may either retain old value or be overwritten
    with all-1s. Implementation chooses per element, may be non-deterministic
    across runs.
- **tail** (`vl <= x < VLMAX`) — controlled by `vtype.vta`.
  - `vta=0`: undisturbed.
  - `vta=1`: agnostic — same two-value choice as inactive.

Crucially, **agnostic does not permit arbitrary garbage**. The spec
constrains the value to one of {old value, all-1s}. A freshly rotated
physical register containing leftover bytes from a previous arch's lifetime
violates agnostic — it is generally neither the old value nor all-1s.

Mapping to the python model's terminology: `start_index` corresponds to
`vstart`, `n_elements` to `vl - vstart`, so `start_index + n_elements`
corresponds to `vl`.

## Why rename interacts with this

The kamlet rename design (`docs/PLAN_lamlet_rename.md`) has two allocation
modes for a destination physical register:

- `w(arch)` — pull a fresh phys from the free queue. The previous phys is
  released. Old data is gone; the fresh phys contains arbitrary garbage from
  whatever its previous owner left there. Enables WAW pipelining across
  rolled-loop iterations.
- `rw(arch)` — keep the existing phys mapped to `arch`. The old data is
  available. No rotation, so back-to-back writes to the same arch serialize.

For an instruction that writes every byte of every destination vline,
`w()` is always safe — the fresh phys gets fully overwritten. For an
instruction that leaves any byte un-written, the un-written bytes inherit
whatever was in the freshly allocated phys, which is unconstrained garbage.
That violates both undisturbed (which requires the *old arch's* value) and
agnostic (which permits only old or all-1s).

So under the current "no vta/vma fields" model, the safe rule is:

> Use `rw()` for any vline that has any unwritten position. Use `w()` only
> for fully-written vlines.

This is correct but pessimistic. With explicit `vta`/`vma` knowledge we can
upgrade individual partial vlines to `w()` whenever their unwritten regions
fall under an agnostic policy, by writing all-1s into those positions in
the data path.

## Design

### 1. Kinstruction encoding

Add two boolean fields to every kinstruction that writes a vector
destination:

```python
vta: bool  # tail-agnostic
vma: bool  # mask-agnostic
```

Affected kinstrs (non-exhaustive — audit during implementation):

- `VArithVvOp`, `VArithVxOp`
- `VCmpViOp`, `VCmpVxOp`, `VCmpVvOp`
- `VBroadcastOp`, `VidOp`
- `VUnaryOvOp`
- `VmnandMmOp` (mask result, vta-only — see below)
- `Load`, `LoadImmByte`, `LoadImmWord`, `LoadWord`
- `VreductionOp` (when revived)

Read-only kinstrs (`Store`, `StoreWord`, `StoreScalar`, `ReadRegWord`) do
not need vta/vma — they don't write a vector destination.

`WriteRegElement` is a single-element patch and is inherently RMW; vta/vma
do not apply.

For mask-result instructions (`VCmpV*`, `VmnandMmOp`): the spec says
"Mask destination tail elements are always treated as tail-agnostic"
(`v-st-ext.adoc:364-365`). So mask results have an implicit `vta=True` and
the field can be omitted, or always-true.

### 2. Lamlet vtype tracking

The lamlet currently does not track vtype. Add:

- `Lamlet.current_vta: bool` and `Lamlet.current_vma: bool`, set to `False`
  by default.
- An update path for when the program executes a `vsetvli` /
  `vsetivli` / `vsetvl`. The lamlet already has logic for `vsetvl` (find
  it); extend it to capture vta/vma from the immediate.
- When the lamlet builds any vector kinstr, stamp `vta=self.current_vta`
  and `vma=self.current_vma`.

For compound ops in `lamlet/unordered.py` and `oamlet/reduction.py` etc.,
the helper functions that build kinstrs need to accept (or read from
`lamlet`) the current vta/vma.

### 3. Kamlet allocator helper

Add a `Kamlet` method that wraps the per-vline rename decision:

```python
def alloc_dst_pregs(
    self,
    base_arch: int,
    start_vline: int,
    end_vline: int,
    start_index: int,
    n_elements: int,
    elements_in_vline: int,
    mask_present: bool,
    vta: bool,
    vma: bool,
) -> dict[int, AllocedPreg]:
    ...
```

where `AllocedPreg` carries:
- `phys: int` — the allocated physical register.
- `is_rotated: bool` — True if `w()` was used (fresh phys), False if `rw()`.
- `agnostic_positions: AgnosticDescriptor` — describes which byte/element
  positions in this vline are agnostic (need to be filled with 1s by the
  data path). Empty if `is_rotated=False` or if no agnostic positions exist.

Per-vline decision:

```
has_prestart = (vline_idx == start_vline) and (start_index % elements_in_vline != 0)
has_inactive = mask_present                # any active body element could be masked off
has_tail     = (vline_idx == end_vline) and ((start_index + n_elements) % elements_in_vline != 0)

needs_undisturbed = (
    has_prestart or
    (has_inactive and not vma) or
    (has_tail and not vta)
)

if needs_undisturbed:
    use rw()
else:
    use w() and the data path must fill agnostic positions with 1s
```

### 4. Data-path fill behavior

The user's directive: rather than running a separate "fill with 1s" pass
before the active-write loop, the data path can write 1s inline whenever
it would otherwise skip a position. The exact mechanism depends on the
instruction:

**Pattern A: per-element loop (VArithV{v,x}Op, VBroadcastOp, VidOp, VUnaryOvOp)**

Today these have:

```python
if valid_element and mask_bit:
    # compute and write active element
```

Under agnostic-fill, the else branch writes all-1s (only when the dst phys
was rotated and the position is agnostic). Roughly:

```python
if valid_element and mask_bit:
    write computed value
elif preg_was_rotated_and_position_is_agnostic(...):
    write all-1s
# else: position is undisturbed, leave the rf_slice byte alone
#       (which is correct because the dst phys was NOT rotated, so the byte
#       still holds the old arch's value)
```

The "is the position agnostic" predicate combines:
- prestart: never agnostic
- inactive (mask-off, body): agnostic iff `vma`
- tail: agnostic iff `vta`

Each instruction handler decides this inline using the `vta`/`vma` from
the kinstr and the per-element classification it already computes.

**Pattern B: bulk word/vline writes (Load simple/notsimple, Store, LoadWord)**

These compute a per-vline byte mask `mask` and do
`update_bytes_word(old, new, mask)`. The "old" comes from the dst phys
(rf_slice). Under agnostic-fill, when the dst phys is rotated, "old"
should effectively be all-1s in the agnostic positions and undefined
elsewhere (we don't care because those bytes will be overwritten by the
active mask anyway). So the update becomes:

```python
fill_mask = bitmask of agnostic byte positions
old_word = (1s where fill_mask, 0 elsewhere)  # synthesized, not read from rf_slice
updated_word = (old_word & ~active_mask) | (new_word & active_mask)
write updated_word
```

Equivalently: pre-compute `old_or_fill = active_mask ? new_word : (fill_mask ? 0xFF : 0)` and write that.

Each load/store handler audits its update logic and handles the rotated
case explicitly. For the not-rotated case, the existing
`update_bytes_word(rf_slice_old, new, mask)` path stays the same.

### 5. Handler audit

Every kinstr handler refactored under the rename plan needs an audit pass:

- Pull `vta`/`vma` from `self`.
- Replace the current `if mask_present: rw() else: w()` block with a
  call to `alloc_dst_pregs`.
- For each rotated vline (`is_rotated=True`), implement the agnostic-fill
  pattern in the data path per the patterns above.
- For witems that store `dst_pregs` for later use in finalize (e.g.
  `WaitingLoadSimple`, `WaitingLoadJ2JWords`), also store the per-vline
  `agnostic_positions` so that the late data path (running in jamlet
  context, possibly cycles after the kinstr was dispatched) knows what to
  fill.

## Execution plan

### Stage 1 — kinstr fields and lamlet stamping

- Add `vta: bool` and `vma: bool` to all dst-writing kinstrs.
- Default to `False, False` in every constructor in
  `lamlet/unordered.py`, `oamlet/oamlet.py`, `oamlet/reduction.py`, etc.
- Add `current_vta` / `current_vma` state to the lamlet and a code path
  to update them on `vsetvli`. Stamp every emitted dst-writing kinstr.

Until subsequent stages land, vta/vma are always False everywhere and the
behavior is identical to today.

### Stage 2 — `Kamlet.alloc_dst_pregs` helper

- Implement the helper as described above. Returns per-vline phys,
  rotated flag, and agnostic descriptor.
- Initially, callers can ignore the agnostic descriptor; the helper still
  produces correct rw/w decisions.

### Stage 3 — wire helper into refactored handlers

- Replace the current `if mask_present: rw() else: w()` blocks in:
  `VArithVvOp`, `VArithVxOp`, `VCmpV*` (no mask, but still partial-vline),
  `VBroadcastOp`, `VidOp`, `VUnaryOvOp`, `handle_load_imm_byte_instr`,
  `handle_load_imm_word_instr`, `handle_load_word_instr`,
  `handle_load_instr_simple`, `handle_load_instr_notsimple`.
- For witem-backed handlers, propagate the agnostic descriptor onto the
  witem alongside `dst_pregs`.

After this stage the rename allocator is using vta/vma but the data path
still doesn't fill 1s. That's safe because vta/vma are still always
`False` from stage 1, so no vline is ever rotated in a partial state, so
no fill is ever required.

### Stage 4 — data-path agnostic fill

- Audit each kinstr handler / witem data path.
- Implement the inline 1s-fill per the patterns in section 4.
- Add a test that exercises rotation under `vta=True` and `vma=True` and
  verifies the agnostic positions are all-1s after the operation.

### Stage 5 — turn on vta/vma in the lamlet

- Implement the actual `vsetvli` parsing in the lamlet so that
  `current_vta` / `current_vma` reflect the program's intent.
- Verify that the existing kernel test suite still passes (everything
  defaulted `tu, mu` should be unaffected).
- Add tests that explicitly use `ta, ma` and confirm pipelining improves
  on rolled loops with `vl < VLMAX` tail iterations.

## Out of scope

- Hardware (Chisel) implementation. This is python-model only for now.
- Bit-budget tightening of kinstruction encodings to fit vta/vma. The
  python kinstrs are dataclass-based and can grow freely; the Chisel
  encoding will need to find one bit each, but that's part of the
  separate kinstruction bit-budget cleanup tracked in `docs/TODO.md`.
- Per-element non-deterministic agnostic patterns. The python model will
  pick a single fixed policy (always-fill-1s when allowed) rather than
  varying per-element or per-execution as the spec permits.

## Open questions

- Does the lamlet currently parse `vsetvli` immediates at all, or does it
  receive vtype updates through some higher-level path? Need to find the
  current vsetvl handling and figure out where to inject vta/vma capture.
- For instructions whose output is itself a mask register (`VCmpV*`,
  `VmnandMmOp`), the spec mandates implicit `vta=True`. Confirm whether
  these need a separate code path or whether the helper can detect them
  via the destination element width.
- Does the Chisel side need any preparatory hooks before this lands in
  python, so the two stay close to the same shape?
