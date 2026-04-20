# Plan: Implement All Vector Reduction Operations

## Context

Both `dotprod` (6 tests) and `unaligned` (6 tests) are blocked on `vredsum.vs` which raises
`NotImplementedError`. This is part of the LLVM/Clang migration (Phase 2 of
`docs/PLAN_llvm_vpu_spills.md`).

## Scope

All 16 RISC-V V reduction instructions:

### Single-width integer (8)
vredsum.vs, vredmaxu.vs, vredmax.vs, vredminu.vs, vredmin.vs,
vredand.vs, vredor.vs, vredxor.vs

### Widening integer (2)
vwredsumu.vs — unsigned zero-extend SEW to 2*SEW, sum into 2*SEW accumulator
vwredsum.vs  — signed sign-extend SEW to 2*SEW, sum into 2*SEW accumulator

### Single-width float (3, excluding ordered)
vfredusum.vs — unordered float sum (tree reduction, same structure as integer)
vfredmax.vs  — float max (maximumNumber)
vfredmin.vs  — float min (minimumNumber)

### Widening float (1, excluding ordered)
vfwredusum.vs — unordered widening float sum

### Out of scope (ordered, 2)
vfredosum.vs  — ordered float sum (strictly left-to-right, cannot use tree)
vfwredosum.vs — ordered widening float sum

## Approach

Implement reductions using **only existing kinstrs** — no new kinstr types, no new message
types, no new waiting items. The reduction tree is built from VidOp, VArithVxOp, VCmpViOp,
RegGather, and VArithVvOp.

### Two reduction structures

1. **Tree reduction** — used by all in-scope ops. The combine op and identity value
   change per op, but the structure is identical.

2. **Widening** — used by vwredsumu, vwredsum, vfwredusum. Source elements are SEW-wide,
   accumulator is 2*SEW-wide. Setup extends source elements to 2*SEW before the tree
   reduction proceeds at 2*SEW width.

### Out of scope
Ordered reductions (vfredosum.vs, vfwredosum.vs) require strictly left-to-right
accumulation and cannot use a tree. These will be implemented separately.

## Temp Registers

7 temp registers allocated via `alloc_temp_regs(7)`:
- temp_id: element indices [0, 1, 2, ...], set once in setup, never overwritten
- temp_idx: gather indices, recomputed each round
- temp_mask: round mask, recomputed each round
- temp_a, temp_b, temp_c, temp_d: data movement and combining, ping-pong across rounds

Pool has 8 temp registers (v32-v39), so 7 is fine.

## Tree Reduction Kinstr Sequence

For `vred<op>.vs vd, vs2, vs1, vm` with vl active elements and vlmax total:

### Setup (3 kinstrs)
```
VidOp(dst=temp_id, ew, vlmax)                            # [0, 1, 2, ...]
VBroadcastOp(dst=temp_a, scalar=identity, ew, vlmax)     # fill with op identity
VArithVxOp(ADD, dst=temp_a, src2=vs2, scalar=0,          # masked copy of active elements
           mask=mask_reg, n_elements=vl)
```

### Identity Values

Integer:
- SUM, OR, XOR: 0
- AND: ~0 (all bits set, width-dependent)
- MAXU: 0
- MAX: min signed int for element width (e.g. -2^(ew-1))
- MINU: max unsigned int for element width (e.g. 2^ew - 1)
- MIN: max signed int for element width (e.g. 2^(ew-1) - 1)

Float:
- FADD (unordered sum): +0.0 (or -0.0 when rounding down)
- FMAX: -inf
- FMIN: +inf

### Tree Rounds (5 kinstrs per round, ceil(log2(vlmax)) rounds)

Strides go small-to-large: stride=1, 2, 4, ..., vlmax/2.

Data registers ping-pong across rounds:
- Round 0: src=temp_a, dst=temp_b
- Round 1: src=temp_b, dst=temp_c
- Round 2: src=temp_c, dst=temp_d
- Round 3: src=temp_d, dst=temp_a
- Round 4: src=temp_a, dst=temp_b  (wraps)

Per round (stride = 2^k, reading from `src`, writing to `dst`):
```
VArithVxOp(AND, dst=temp_idx, src2=temp_id,              # low bits of element index
           scalar=2*stride-1, vlmax)
VCmpViOp(EQ, dst=temp_mask, src=temp_idx, simm5=0, vlmax)  # mask: index % (2*stride) == 0
VArithVxOp(ADD, dst=temp_idx, src2=temp_id,              # gather indices: vid + stride
           scalar=stride, vlmax)
RegGather(vd=dst, vs2=src, vs1=temp_idx,                 # fetch partner values
          mask=temp_mask, vlmax)
VArithVvOp(<op>, dst=dst, src1=src, src2=dst,            # combine: dst = src <op> dst
           mask=temp_mask, vlmax)
```

Non-accumulator positions in dst are garbage from the gather, but the mask ensures only
accumulator positions get the combine op. The next round's gather reads from accumulator
positions of the current dst (which have correct partial results), so garbage in
non-accumulator positions is harmless.

### Finalize (1 kinstr)
```
VArithVvOp(<op>, dst=vd, src1=last_dst, src2=vs1,        # vd[0] = tree_result <op> vs1[0]
           n_elements=1, mask=None)
```

### Cleanup
Free all 7 temp registers.

## Widening Reductions (vwredsumu, vwredsum, vfwredusum)

Source elements are SEW-wide, accumulator and result are 2*SEW-wide.

### Approach
1. Setup: extend vs2 elements from SEW to 2*SEW into temp_a (using VUnaryOp SEXT/ZEXT)
2. Proceed with tree or sequential reduction at 2*SEW element width
3. Finalize: combine with vs1[0] (which is already 2*SEW) into vd[0]

TODO: flesh out the exact kinstr sequence when we implement this.

## Op Mapping

### Single-width integer
VRedOp → VArithOp:
- SUM → ADD
- AND → AND
- OR → OR
- XOR → XOR
- MAX → MAX
- MAXU → MAXU
- MIN → MIN
- MINU → MINU

### Single-width float
VRedOp → VArithOp:
- FREDUSUM → FADD (tree)
- FREDMAX → FMAX
- FREDMIN → FMIN

### Widening integer
VRedOp → VArithOp:
- WREDSUMU → ADD (after zero-extend to 2*SEW)
- WREDSUM → ADD (after sign-extend to 2*SEW)

### Widening float
VRedOp → VArithOp:
- FWREDUSUM → FADD (tree, after widen to 2*SEW)

## VRedOp Enum Additions

Current enum only has: SUM, MAXU, MAX, MINU, MIN, AND, OR, XOR

Need to add: FREDUSUM, FREDMAX, FREDMIN, WREDSUMU, WREDSUM, FWREDUSUM

## Files to Modify

### `python/zamlet/kamlet/kinstructions.py`
- Expand `VRedOp` enum with float, widening, and ordered variants

### `python/zamlet/decode.py`
- Add decoding for all 16 reduction instructions (currently only vredsum.vs)

### `python/zamlet/instructions/vector.py`
- Add span creation to `VreductionVs.update_state` (line 890)
- Pass span_id and vlmax to the handler
- May need separate `VreductionWideVs` class for widening reductions (different SEW
  for source vs accumulator)

### `python/zamlet/oamlet/oamlet.py`
- Implement `handle_vreduction_vs_instr` (currently raises NotImplementedError at line 1317)
- This method will:
  1. Map VRedOp to VArithOp, identity value, and reduction structure (tree vs sequential)
  2. Allocate 7 temp registers
  3. Set vrf_ordering for temp registers
  4. Compute vlmax and number of rounds
  5. For tree reductions: emit setup (3) + rounds (5 × ceil(log2(vlmax))) + finalize (1)
  6. For ordered reductions: emit sequential accumulation loop
  7. For widening: extend source elements first, then tree/sequential at 2*SEW
  8. Free temp registers

## Implementation Order

1. Tree reduction for single-width integer (unblocks dotprod/unaligned tests)
2. Decoding for all single-width integer reductions
3. Tree reduction for single-width float (unordered sum, max, min)
4. Widening integer reductions
5. Widening float reduction (vfwredusum)

## Key Details

### vlmax Calculation
vlmax = (VLEN * LMUL) / SEW. Same formula as vrgather (vector.py line 1430):
```python
elements_in_vline = params.vline_bytes * 8 // element_width
vlmax = elements_in_vline * lmul
```

### Number of Rounds
ceil(log2(vlmax)). For ew=32 with 2 jamlets (test geometry k2x1_j1x1), vlmax might be 4,
so 2 rounds = 10 kinstrs + 3 setup + 1 finalize = 14 kinstrs total.

### RegGather Masking
RegGather has a mask_reg field. It skips masked-off elements, avoiding unnecessary J2J
messages for large strides.

### VCmpViOp Output Format
VCmpViOp writes 1-bit-per-element mask results to the dst register. This is the format
expected by mask_reg in VArithVvOp and RegGather.

### Span Creation
Add span creation to `VreductionVs.update_state` (matching pattern from VrgatherVv) and
pass span_id to the handler. All kinstrs are children of this span.

### Instr Idents
Each kinstr needs a unique instr_ident from `get_instr_ident()`. With 3 + 5*rounds + 1
kinstrs per reduction, this consumes idents. The IdentQuery mechanism handles wraparound.

## Python Tests

### New file: `python/zamlet/tests/test_reduction.py`

Oamlet-level test (same pattern as `test_conditional_kamlet.py`). Directly constructs an
Oamlet, loads data into vector registers, then invokes the reduction and verifies the result.

Test cases:
1. **Basic sum** — small vector, verify vd[0] = vs1[0] + sum(vs2[*])
2. **Non-power-of-2 vl** — e.g., vl=5 with vlmax=8, verify inactive elements excluded
3. **Masked reduction** — some elements masked off, verify they don't contribute
4. **vs1[0] scalar** — verify the scalar initial value is included correctly
5. **Multiple geometries** — run across SMALL_GEOMETRIES to test local-only and
   cross-jamlet reduction paths
6. **Multiple element widths** — test with ew=8, ew=16, ew=32
7. **All integer ops** — SUM, AND, OR, XOR, MAX, MAXU, MIN, MINU
8. **Float ops** — unordered sum, max, min
9. **Widening ops** — verify source extension and 2*SEW accumulation

## Verification

### Python tests
```bash
nix-shell
python python/zamlet/tests/test_reduction.py > test_reduction.log 2>&1
```

### Kernel tests (blocked on single-width integer reductions)
```bash
bazel test //python/zamlet/kernel_tests/dotprod:test_dotprod_k2x1_j1x1 \
  --test_output=streamed --test_env=LOG_LEVEL=WARNING > dotprod_test.log 2>&1
bazel test //python/zamlet/kernel_tests/unaligned:test_unaligned_k2x1_j1x1 \
  --test_output=streamed --test_env=LOG_LEVEL=WARNING > unaligned_test.log 2>&1
```

All 6 dotprod tests and 6 unaligned tests should pass.
