# Widening / Narrowing Binary Vector Arithmetic

## Context

The FFT kernel (`python/zamlet/kernel_tests/fft/vec-fft8.c`) currently fails to
run because LLVM emits `vwmulu.vx` when auto-vectorizing the 8-element widen
loop `((uint64_t)idx32[i]) << 3`. The Python simulator's decoder has no entry
for `vwmulu.vx`, so every test geometry crashes with
`ValueError: Unknown 32-bit instruction: 0xe2ab6457`.

The proper fix is not to sidestep this one instruction — it is to add
width-asymmetric binary vector arithmetic to the kamlet kernel model, since
the full RISC-V V widening family (vwadd, vwsub, vwmul, vwmacc, vfw*,
vwmaccus, etc.) will keep appearing as we push more compiled C through the
toolchain. The narrowing family (vnsrl, vnsra) is the same shape in reverse.
Handling both with one class pair keeps the design orthogonal.

## Design: two new kinstruction classes, no new `VArithOp` enum values

Mirroring the existing `VUnaryOp` / `VUnaryOvOp` split (unary vs unary with
differing src/dst widths), we add:

- `VArithVvOvOp` — binary, two vector sources, per-operand widths + signedness
- `VArithVxOvOp` — binary, vector source + scalar, per-operand widths + signedness

Both reuse existing `VArithOp` values (`ADD`, `SUB`, `MUL`, `MACC`, `SRL`,
`SRA`, `FADD`, `FSUB`, `FMUL`, `FMACC`, `FNMACC`, `FMSAC`, `FNMSAC`).
Signedness and width differences are carried as class parameters.

**As part of this change, migrate `vnsrl.wi` out of `VUnaryOvOp` into the new
classes.** NSRL is genuinely binary (value + shift amount) — it only lived in
the unary class by encoding the shift as a field. After the migration,
`VUnaryOp.NSRL` and the NSRL case in `VUnaryOvOp._convert` can be deleted,
`VUnaryOvOp`'s `shift_amount` field can be removed, and `VUnaryOvOp` is left
covering truly unary ops only (`SEXT`, `ZEXT`, `COPY`, `FCVT_*`).

### Class shape

`VArithVvOvOp` fields:
```
op: VArithOp
dst, src1, src2: int
mask_reg: int | None
n_elements: int
src1_ew, src2_ew, dst_ew: int       # independent per-operand widths
src1_signed, src2_signed: bool      # unpacking signedness
word_order: addresses.WordOrder
instr_ident: int
is_float: bool = False
```

`VArithVxOvOp` replaces `src1` with `scalar_bytes: bytes`, adds
`scalar_ew: int` and `scalar_signed: bool`.

### `admit`

Models `VUnaryOvOp.admit`. Compute `n_src1_vlines`, `n_src2_vlines`,
`n_dst_vlines` separately from each EW. Look up `src1_pregs` / `src2_pregs` /
`mask_preg` before allocating `dst_pregs`.

Accumulator ops (`self.op in ACCUM_OPS`): `rw` on dst at `n_dst_vlines` so the
2·SEW accumulator read is covered by the write lock.

Non-accumulator: `alloc_dst_pregs(..., elements_in_vline = bits_in_vline //
dst_ew)`.

### `execute`

Loop outer over jamlets, then over `n_dst_vlines`. For each dst element,
compute its logical element index and map back to the corresponding src1/src2
vlines (same trick as `VUnaryOvOp.execute`). Unpack src values with
`struct.unpack` format driven by per-operand `*_signed` + `*_ew`. Accumulator
read uses dst_ew + op-specific signedness (signed for WMACC/WMACCSU, unsigned
for WMACCU, mixed for WMACCUS — handled by `_acc_signed(op)` helper). Compute
via existing `_compute_arith`. Pack into dst at `dst_ew`.

Shift-amount masking for NSRL/NSRA uses `src2_eb` (narrowing: 2·SEW wide).
vwsll (future) would use `dst_eb`. Pass the right eb into `_compute_arith`
explicitly. Extend `_compute_arith`'s SLL/SRL/SRA paths to take an
`shift_eb` parameter (default to `eb`).

## Files to modify

1. **`python/zamlet/kamlet/kinstructions.py`**
   - Add `VArithVvOvOp` and `VArithVxOvOp` dataclasses (modeled on
     `VUnaryOvOp` at line 880 + `VArithVvOp`/`VArithVxOp` at 1187/1271)
   - Extend `_compute_arith` (line 1104) SLL/SRL/SRA cases to take optional
     `shift_eb` kwarg
   - Remove `VUnaryOp.NSRL` enum member (line 74) and the NSRL case in
     `VUnaryOvOp._convert` (line 964), and the NSRL-related
     `shift_amount` field on `VUnaryOvOp` (line 891)

2. **`python/zamlet/instructions/vector.py`**
   - Add `VArithVvOv` and `VArithVxOv` oamlet-side wrapper classes (modeled
     on `VArithVv` at line 1344 / `VArithVx` at ~1480). Each `update_state`
     determines `src_ew`, `dst_ew`, and per-operand signedness from the op
     and the shape flag (vv/vx base vs wv/wx wide), calls
     `s.assert_vrf_ordering(src, src_ew)` and
     `s.set_vrf_ordering(vd, dst_ew)`, and emits the new kinstruction.
   - The wrapper carries a `shape` flag (`'base'` for .vv/.vx, `'wide'` for
     .wv/.wx) and signedness flags; decoder fills them per instruction.
   - Delete the NSRL branch of the `VUnary` wrapper that forwards to
     `VUnaryOvOp(NSRL)`; route `vnsrl.wi` through the new `VArithVxOv`
     instead.

3. **`python/zamlet/decode.py`**
   - Under `opcode == 0x57`, add entries for the widening int/float add,
     sub, mul, mac, and mac-variant families (full funct6 × funct3 matrix
     below).
   - Migrate the `funct6 == 0x2c and funct3 == 0x3` NSRL entry to build
     `V.VArithVxOv(op=SRL, shape='narrow', ...)` instead of `V.VUnary(NSRL)`.
   - Decoder table (from the spec's funct6 wavedrom, verified in
     `/home/ben/Code/riscv-isa-manual/src/images/wavedrom/v-inst-table.edn`):

     | funct6  | funct3=2/6 (int)  | funct3=1/5 (float) |
     |---------|-------------------|--------------------|
     | 110000  | vwaddu .vv/.vx    | vfwadd .vv/.vf     |
     | 110001  | vwadd  .vv/.vx    | —                  |
     | 110010  | vwsubu .vv/.vx    | vfwsub .vv/.vf     |
     | 110011  | vwsub  .vv/.vx    | —                  |
     | 110100  | vwaddu.wv/.wx     | vfwadd.wv/.wf      |
     | 110101  | vwadd.wv/.wx      | —                  |
     | 110110  | vwsubu.wv/.wx     | vfwsub.wv/.wf      |
     | 110111  | vwsub.wv/.wx      | —                  |
     | 111000  | vwmulu  .vv/.vx   | vfwmul .vv/.vf     |
     | 111010  | vwmulsu .vv/.vx   | —                  |
     | 111011  | vwmul   .vv/.vx   | —                  |
     | 111100  | vwmaccu  .vv/.vx  | vfwmacc  .vv/.vf   |
     | 111101  | vwmacc   .vv/.vx  | vfwnmacc .vv/.vf   |
     | 111110  | vwmaccus .vx only | vfwmsac  .vv/.vf   |
     | 111111  | vwmaccsu .vv/.vx  | vfwnmsac .vv/.vf   |

     ~47 new decoder entries.

## Verification

1. Build the kernel:
   `nix-shell --run "bazel build //python/zamlet/kernel_tests/fft:vec-fft8"`
2. Run the FFT test (currently all 6 geometries fail at decode):
   `nix-shell --run "bazel test //python/zamlet/kernel_tests/fft:test_fft --test_output=streamed"`
   Expect `PASSED` printed from the kernel and all 6 geometries green.
3. Re-run bitreverse regression to confirm no regression in non-widening
   path:
   `bazel test //python/zamlet/kernel_tests/bitreverse_reorder:test_bitreverse_reorder64_n16_k2x2_j2x1 --test_output=streamed`
4. No Python-side unit tests reference `vnsrl` today (verified), so NSRL
   migration has no direct test coverage — C-side `encoding.h` macros are
   assembler-only and unaffected. If we later find a kernel that uses
   `vnsrl.wi`, it will exercise the migrated path through the new class.

## Also in scope (trivial additions alongside NSRL migration)

Since we are building the Ov classes anyway, wire up the rest of the
narrowing shift family at the same time — decoder entries only, no new
class work:

- `vnsrl.vv`, `vnsrl.vx` (funct6 0x2c, funct3 0x0 and 0x4): same op as
  `vnsrl.wi` with a vector or scalar shift amount instead of an immediate.
- `vnsra.vi`, `vnsra.vv`, `vnsra.vx` (funct6 0x2d): op=`SRA` on the Ov
  class.

## Out of scope (defer, with reasons)

- **`vnclip` / `vnclipu`** — narrowing *saturating* shift. Although shape
  is width-asymmetric binary, the saturation behaviour is a new semantic
  (not just a clip-to-dst-width truncation — the result is clamped to the
  signed/unsigned range of the destination, with `vxsat` side effects).
  Requires new `VArithOp.NCLIP` / `VArithOp.NCLIPU` values and saturation
  logic in `_compute_arith`, which is beyond width-asymmetric arithmetic.

- **`vfwredusum`** (widening float reduction) — not part of the Ov class
  path. Reductions are decomposed elsewhere into per-element operations
  plus a tree reduce. If we ever want the widening-reduction primitive
  in-model, it would sit in `Vreduction` (whose `_WIDENING` set already
  reserves the enum); it is structurally unrelated to these two new
  classes.
