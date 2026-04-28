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

Affected kinstrs (verified against `kamlet/kinstructions.py` and
`transactions/load.py`):

Vector-dst, partial vline possible:
- `VArithVvOp`, `VArithVxOp` (`kinstructions.py:1567,1655`)
- `VArithVvOvOp`, `VArithVxOvOp` — widening/narrowing variants
  (`kinstructions.py:1775,1892`)
- `VBroadcastOp` (`kinstructions.py:1088`)
- `VidOp` (`kinstructions.py:1151`)
- `VUnaryOvOp` (`kinstructions.py:1216`)
- `LoadImmByte`, `LoadImmWord` (`kinstructions.py:354,399`)
- `Load` (`transactions/load.py:26`)

Mask-result kinstrs (implicit `vta=True` per `v-st-ext.adoc:364-365` —
"Mask destination tail elements are always treated as tail-agnostic"):
- `VCmpViOp`, `VCmpVxOp`, `VCmpVvOp` (`kinstructions.py:537,619,708`)
- `VmLogicMmOp` (`kinstructions.py:823`) — generic mask logic family
  (replaced the original draft's `VmnandMmOp`)
- `SetMaskBits` (`kinstructions.py:999`)

For mask-result kinstrs, the `vta` field can be omitted, or always-true.

`MaskPopcountLocal` (`kinstructions.py:932`) writes a fully-defined word
per jamlet (other slots zeroed) — no partial vline, so vta/vma don't apply.

Reductions are decomposed in `oamlet/reduction.py` into ordinary kinstrs
(no dedicated reduction kinstr class). They inherit vta/vma from whatever
the underlying decomposed ops carry.

Read-only kinstrs (`StoreScalar`, `ReadRegWord`) do not need vta/vma —
they don't write a vector destination.

**Accumulator-style ops keep direct `rw()`.** Ops whose semantics include
"read prior value of dst" (the accumulator branch in `VArithVvOp` /
`VArithVxOp` at `kinstructions.py:1593`, plus `WriteRegElement`) cannot
benefit from rotation regardless of vta/vma — there's no way to provide a
fresh phys *and* preserve the active-body old value the kinstr needs to
read. Keep their direct `rw()` calls; do not route them through the
allocator helper.

### 2. Reading vta/vma at kinstr-construction time

The oamlet already stores `vtype` as the raw 8-bit immediate from
`vsetvli` / `vsetivli` / `vsetvl` (`instructions/vector.py:65,137`,
`oamlet.py:431-441` exposes `sew` / `lmul` as properties on the raw bits).
Other vtype fields (`vl`, `vsew`, `vlmul`) are read directly from `s.vtype`
at the moment a kinstr is constructed; the lamlet does not cache vtype.

Mirror that pattern: at every kinstr-construction site that has the oamlet
state `s` in scope, extract vta/vma inline:

```python
vta = bool((s.vtype >> 6) & 0x1)
vma = bool((s.vtype >> 7) & 0x1)
```

and stamp the kinstr fields. No new lamlet state.

For compound ops in `oamlet/reduction.py` and any builder in
`lamlet/unordered.py` / `lamlet/lamlet_waiting_item.py` that doesn't
already have `s` in scope: pass `vta` / `vma` through arguments to the
builder, just like `vl` and `element_width` are passed today.

### 3. Kamlet allocator helper

Add a `Kamlet` method that wraps the per-vline rename decision and returns
just the per-vline phys regs:

```python
async def alloc_dst_pregs(
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
) -> List[int]:
    ...
```

The helper does not need to communicate "was this vline rotated?" back to
the handler. The handler already has vta/vma + the per-element
classification it computes anyway, and unconditionally writing 1s into
agnostic positions is spec-legal regardless of whether the phys was
rotated:

- if rotated (`w()`): writing 1s into agnostic positions is required (no
  old value available — the only legal option).
- if not rotated (`rw()`): writing 1s into agnostic positions is also
  legal — the spec says agnostic = old value *or* all-1s, implementation
  chooses per element.

Allocator and handler reach a consistent outcome from the same inputs
without sharing state.

Per-vline decision inside the helper:

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
    use w()      # data path will fill agnostic positions with 1s
```

### 4. Data-path fill behavior

The data path writes 1s inline into agnostic positions, unconditionally
(no per-vline "is_rotated" branch — see section 3). The "is the position
agnostic" predicate combines:

- prestart: never agnostic
- inactive (mask-off, body): agnostic iff `vma`
- tail: agnostic iff `vta`

Each handler decides agnostic-or-not inline using the `vta`/`vma` from
the kinstr and the per-element classification it already computes.

**Pattern A: per-element loop (VArithV{v,x}Op, VBroadcastOp, VidOp, VUnaryOvOp)**

Today these have:

```python
if valid_element and mask_bit:
    # compute and write active element
```

Under agnostic-fill:

```python
if valid_element and mask_bit:
    write computed value
elif position_is_agnostic(...):
    write all-1s
# else: position is undisturbed (prestart, or inactive-and-not-vma, or
#       tail-and-not-vta) — leave the rf_slice byte alone
```

When this leaves a byte alone, the allocator must have picked `rw()`
(the helper's rotation rule guarantees no `w()` for vlines with any
undisturbed positions), so the byte holds the correct old-arch value.

**Pattern B: bulk word/vline writes (LoadImmByte, LoadImmWord, Load)**

These compute a per-vline byte mask and do
`update_bytes_word(old, new, mask)`. The "old" today comes from the dst
phys (rf_slice). Under agnostic-fill, build a synthesized "fill word"
with 1s in agnostic byte positions and substitute it for `old` in those
positions:

```python
fill_mask = byte mask of agnostic positions in this vline
active_mask = byte mask of active positions in this vline
synth_old = (rf_slice_old & ~fill_mask) | fill_mask  # 1s in agnostic, old elsewhere
updated_word = (synth_old & ~active_mask) | (new_word & active_mask)
write updated_word
```

Equivalently, in one step: at each byte position, write `new` if active,
else `0xFF` if agnostic, else `rf_slice_old`.

For not-rotated vlines, mixing in `rf_slice_old` is correct (preserves
old-arch value in undisturbed positions). For rotated vlines, all
unwritten bytes are agnostic by construction, so `rf_slice_old` is never
sampled in those positions.

### 5. Handler audit

Every kinstr handler refactored under the rename plan needs an audit pass:

- Pull `vta`/`vma` from `self`.
- Replace the current `if mask_present: rw() else: w()` block (and any
  inlined equivalent) with a call to `alloc_dst_pregs`. Skip this for
  accumulator-style branches that need direct `rw()` (see section 1).
- Implement the agnostic-fill pattern in the data path per section 4,
  driven by `vta`/`vma` + the existing per-element classification. No
  per-vline `is_rotated` flag needs to flow through the witem.
- For witems that store `dst_pregs` for later use in finalize (e.g.
  `WaitingLoadSimple`, `WaitingLoadJ2JWords`), also propagate `vta` /
  `vma` and the per-vline geometry needed for the agnostic predicate, so
  the late data path (running in jamlet context, possibly cycles after
  the kinstr was dispatched) can compute fill positions.

## Execution plan

Three PRs, matching the umbrella `PLAN_rvv_coverage.md` F1 split. Each is
self-contained and revertible.

### PR1 — kinstr plumbing (no behavior change)

- Add `vta: bool` and `vma: bool` fields to all dst-writing kinstrs
  listed in section 1. For mask-result kinstrs the field can be omitted
  (implicit `vta=True`).
- At every kinstr-construction site, stamp the real bits from `s.vtype`
  (section 2). This includes the construction sites in
  `instructions/vector.py`, `oamlet/reduction.py`, `lamlet/unordered.py`,
  and `lamlet/lamlet_waiting_item.py` identified during recon. For
  builders that don't have `s` in scope, plumb vta/vma through arguments.
- Allocator unchanged. Handlers don't read the new fields yet.

Behavior identical to today — the fields are dead. This PR can land
independently.

### PR2 — allocator + data-path fill (behavior change)

- Implement `Kamlet.alloc_dst_pregs` (section 3). Helper returns per-vline
  `List[int]` of phys regs.
- Wire the helper into all handlers listed in section 1 (non-accumulator
  branches only). Replace each existing `if mask_present: rw() else: w()`
  block with the helper call.
- Implement the data-path agnostic-fill (section 4) in each handler /
  witem. For witems, propagate vta/vma and per-vline geometry as needed.
- Add tests using the existing sentinel pattern (e.g. `test_strided_load.py:126-128`
  pre-fills the dest with zeros via `test_utils.zero_register` and verifies
  masked positions stay zero after the op):
  - **Positive test** (`vta=True, vma=True`, partial vl, mixed mask): pre-fill
    dest with a non-`0xFF` non-active-value sentinel (e.g. `0x55`), run the op,
    store dest to memory, assert active positions = computed value and agnostic
    positions = `0xFF`. Generalize `zero_register` into a `fill_register(reg,
    byte_pattern)` helper, or add one alongside.
  - **Negative test** (`vta=False, vma=False`, same setup): assert agnostic
    positions = sentinel (undisturbed semantics preserved). This is essentially
    what the existing tests already do with zero as the sentinel.
- Run the kernel test suite. Everything defaulted `tu, mu` must still
  pass.

This is the largest PR. Splittable per kinstr family if it grows
unwieldy: e.g. (2a) helper + per-element pattern A handlers, (2b) bulk
pattern B handlers + load witems.

### PR3 — drop forced `rw()`

- Audit any remaining sites that still force `rw()` for partial-vline
  writes "just in case" and route them through the helper.
- Add a test that confirms pipelining on rolled-loop tail iterations
  with `vta=True, vma=True` (e.g. measure issue gap shrinks vs.
  `vta=False`).

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

None outstanding. The Chisel side may diverge from this python work and
will be planned separately.
