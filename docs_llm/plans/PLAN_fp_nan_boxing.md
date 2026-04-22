# PLAN: FP NaN-boxing

**STATUS: DEFERRED** (2026-04-20). Tracked in `docs/TODO.md` as part of a broader
"fix scalar FP correctness" item. When that work resumes, this design is the
starting point. Until then, VfmvFs and other new F32-producing sites follow the
existing (spec-incorrect but self-consistent) zero-padding convention.

## Goal

Make the Python model honour the RISC-V F-extension NaN-boxing rule for F32 values
stored in 64-bit FP registers. Today the codebase uses a self-consistent "zero-pad
on write, read low 4 bytes on read" convention; nothing currently misbehaves, but
programs that legitimately mix F32 and F64 on the same `f` register would see
different results from a spec-correct implementation.

## Background — the rule

When `FLEN > 32` (as here: FLEN=64), every instruction that writes an F32 result
into an `f` register must set the upper `FLEN-32` bits to all 1s ("NaN-box"):

- F32-as-double: `0xFFFFFFFF_<f32 bits>`, which is a NaN under F64 interpretation.

Every instruction that reads an F32 operand from an `f` register must check the
NaN-box invariant. On violation, the operand value substitutes canonical quiet NaN
`0x7FC00000` (the low 32 bits are **not** used).

Exempt: bit-preserving narrow moves `FMV.X.W` (F32→int) and `FSW` (F32→memory) —
both copy the raw low 32 bits regardless of NaN-box state.

F64 arithmetic, `FMV.X.D`, `FMV.D.X`, `FLD`, `FSD`, and all compressed F64 variants
are untouched — they use the full register width.

## Design — scalar API carries width

Thread a bit-width through the three scalar FP-register accessors. Width in {32, 64};
no default (every caller declares intent explicitly).

```python
# oamlet/scalar.py
_F32_NAN_BOX_UPPER = b'\xff\xff\xff\xff'
_F32_CANONICAL_QNAN = (0x7fc00000).to_bytes(4, 'little')

def read_freg(self, freg_num, width: int) -> bytes:
    """width=64: raw 8 bytes.
    width=32: 4 bytes; canonical qNaN low bytes if NaN-box invariant violated.
    Bit-preserving sites (FMV.X.W, FSW) pass width=64 and slice [:4]."""

def write_freg(self, freg_num, value: bytes, span_id, width: int) -> None:
    """value is width/8 bytes. width=32 NaN-boxes into upper 32 bits."""

def write_freg_future(self, freg_num, future, span_id, width: int) -> None:
    """width=64: future resolves to 8 bytes, raw.
    width=32: future resolves to 4 bytes; internally wrapped via
    clock.create_task to NaN-box before the register slot sees it."""
```

All three are the single concentration point for NaN-box behaviour.

## Site-by-site changes

### `instructions/float.py`

| Site | Current | New |
|---|---|---|
| `_write_fp` (:46) | pad with `bytes(4)` if F32 | `width = 64 if is_double else 32`; pass 4 or 8 bytes |
| `_write_fp_bits` (:58) | same | same |
| `_read_fp` (:41) | `read_freg[:w]` | `read_freg(..., width=32 or 64)` |
| `_read_fp_bits` (:53) | same | same |
| `FmvWX` (:71) | zero-extend 32-bit to 8 bytes | `width=32`, pass 4 bytes |
| `FmvXW` (:93) | low 4 bytes, sign-extend to int | `width=64`, slice `[:4]` (raw, spec-correct) |
| `FmvDX` (:138) | 8 bytes | `width=64` |
| `FmvXD` (:116) | 8 bytes | `width=64` |
| `Flw` (:163) | `utils.pad` zero-extend | `update_resolve` returns 4 bytes; `write_freg_future(..., width=32)` |
| `Fld` (:199) | 8 bytes | `width=64` |
| `Fsw` (:224) | low 4 bytes | `width=64`, slice `[:4]` (raw, spec-correct) |
| `Fsd` (:250) | 8 bytes | `width=64` |
| `FCvt` dst (:498) | pad if F32 | `width=32 if F32 else 64` |
| `FCvt` src (:487) | low `src_w` bytes | `width=32 if F32 else 64` |

### `instructions/compressed.py`

| Site | Current | New |
|---|---|---|
| `CFldsp` (:597) | 8-byte future | `width=64` |
| `CFsdsp` (:623) | 8 bytes | `width=64` |
| `CFld` (:868) | 8-byte future | `width=64` |
| `CFsd` (:895) | 8 bytes | `width=64` |

All already F64. No behavioural change; just the explicit width.

### `instructions/vector.py`

| Site | Current | New |
|---|---|---|
| `VArithVxFloat` (:525) | `read_freg` (8 raw bytes) | `width=element_width`; feeds into `scalar_bytes` for the kinstr |
| new `VfmvSf` | (to be added) | `read_freg(..., width=element_width)` then truncate |
| new `Vfslide1` | (to be added) | `read_freg(..., width=element_width)` then truncate |
| new `VfmvFs` | (to be added) | `write_freg_future(..., width=element_width)` |

### `lamlet/lamlet_waiting_item.py`

`LamletWaitingReadRegElement` gets an `fp_mode: bool` flag. When true, `resolve()`
returns `element_width/8` raw bytes instead of sign-extending to `word_bytes`.

Only `VfmvFs` sets `fp_mode=True` (and uses `read_register_element_fp` or an
equivalent kwarg path through `Oamlet.read_register_element`).

## Execution order (when resumed)

1. Update `scalar.py`: add `width` param to the three methods. Breaks all callers
   until step 2 lands; do back-to-back.
2. Update `float.py` and `compressed.py` call sites. Run existing FP tests; most
   should still pass. Any that inspect raw freg bytes and expect zero-padding
   need to be updated to expect 0xff upper bytes.
3. Add `test_fp_nanbox.py` with the invariants below. Confirms the scalar path
   before vector work starts.
4. Migrate `VArithVxFloat` to the new API. Gains NaN-box check for F32 `.vf`
   scalar operands.
5. Revisit `VfmvFs` / `VfmvSf` / `Vfslide1` sites (by then they will exist with
   zero-padding) and retrofit `width=element_width`; add `fp_mode` path to
   `LamletWaitingReadRegElement`.

## Test invariants

`python/zamlet/tests/test_fp_nanbox.py` covers:

- `FMV.W.X`: upper 4 freg bytes = `0xff` after writing.
- `FLW`: upper 4 freg bytes = `0xff` after load.
- `FADD.S` on a freg whose upper bits are not all 1 returns `0x7FC00000` payload.
- `FMV.X.W` copies raw low 32 bits regardless of NaN-box state (spec-exempt).
- `FSW` stores raw low 32 bits regardless of NaN-box state (spec-exempt).
- Round-trip `FMV.W.X` → `FMV.X.W` preserves the low 32 bits.
- `FCVT.S.D` / `FCVT.D.S`: narrow-side NaN-boxing applies only to the F32 side.

For the vector side (folded into the new-instruction tests):

- `vfmv.f.s` with SEW=32 produces a NaN-boxed freg.
- `vfmv.s.f` / `vfslide1*.vf` reading a non-NaN-boxed freg sees canonical qNaN
  as the injected scalar.

## Out of scope (of this plan; separate fixes)

- Half-precision (Zfh) support — the `width` param generalises if we ever add
  F16, but no changes required now.
- FCSR / rounding-mode handling for conversions — orthogonal correctness axis.
- NaN payload propagation beyond canonical-qNaN substitution — Python native
  float arithmetic already loses payloads; fixing requires a bit-exact FP
  library, which is a separate project.
