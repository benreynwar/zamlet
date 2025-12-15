# RISC-V Vector Extension Implementation Plan

## Current Focus: Permutation Instructions (viota.m, vcompress)

See `VCOMPRESS_PLAN.md` for detailed implementation plan.

---

## Implementation Queue

Operations are grouped by whether they require cross-jamlet communication, which is the primary
implementation complexity driver.

### Cross-Jamlet Communication Required

These operations need data or coordination across jamlet boundaries.

#### 1. Permutation & Mask Instructions ← CURRENT
See `VCOMPRESS_PLAN.md` for detailed implementation.

- [ ] viota.m - Prefix sum of mask bits. Uses `PrefixSumRound` kinstr with log2(j_in_l) rounds.
      Each round: sender broadcasts partial sum to next 2^k jamlets.
- [ ] vcompress - Prefix sum (viota) + `RegScatter` to move enabled elements to computed positions.
- [ ] vcpop.m - J2J reduction tree with SUM. Each jamlet counts local mask bits, tree combines.
      Return scalar result to x register. (Can't use sync network - no SUM support.)
- [ ] vfirst.m - Each jamlet finds local first set bit (or MAX if none). Sync network MIN
      aggregation finds global minimum. If all MAX, return -1.
- [ ] vmsbf.m, vmsif.m, vmsof.m - Use vfirst.m result. Each jamlet compares its element indices
      against the global first position. Pure local computation after vfirst.m completes.
- [ ] vslideup/vslidedown - J2J data movement. For slidedown by N: element i receives from
      element i+N. Elements crossing jamlet boundaries use J2J messaging (similar to
      unaligned load/store). Elements sliding out of range are zero-filled.
- [ ] vslide1up/vslide1down - Same as above but N=1 and element 0 (or vl-1) comes from scalar.
- [ ] vrgather.vv/vx/vi - `RegGather` kinstr (inverse of RegScatter). For each dst element i,
      read index[i], send request to jamlet holding src[index[i]], receive and write to dst[i].
- [ ] vrgatherei16.vv - Same as vrgather but index_ew fixed at 16 bits.

#### 2. Reductions
See `09_reductions.txt` for detailed spec coverage.

**Implementation approach** - J2J reduction tree:
1. Each jamlet computes local partial reduction over its elements
2. Tree reduction using J2J messaging over log2(j_in_l) rounds:
   - Round 0: jamlets 1,3,5,... send partials to jamlets 0,2,4,... and combine
   - Round 1: jamlets 2,6,10,... send to jamlets 0,4,8,... and combine
   - Round k: jamlets where (index % 2^(k+1)) == 2^k send to jamlets where (index % 2^(k+1)) == 0
   - Continue until jamlet 0 has the final result
3. Jamlet 0 writes result to element 0 of destination register (combined with scalar from vs1[0])

**Infrastructure needed**:
- New kinstr: `ReductionRound` - similar structure to `PrefixSumRound` but simpler (pairs only)
- New transaction: `WaitingReductionRound` - handles J2J message send/receive for tree reduction
- Message types: `REDUCTION_REQ/RESP` (or reuse existing J2J infrastructure)
- Reduction op enum: SUM, MAX, MAXU, MIN, MINU, AND, OR, XOR (integer); FSUM, FMAX, FMIN (FP)

**Single-width integer**:
- [ ] vredsum.vs - J2J tree with SUM (sync network doesn't support SUM)
- [ ] vredmax.vs / vredmaxu.vs - Sync network MAX or J2J tree (sync network supports MAX)
- [ ] vredmin.vs / vredminu.vs - Sync network MIN or J2J tree (sync network supports MIN)
- [ ] vredand.vs / vredor.vs / vredxor.vs - J2J tree (sync network doesn't support bitwise)

**Widening integer** (2*SEW accumulator):
- [ ] vwredsum.vs / vwredsumu.vs - Widen elements before local reduction, tree uses 2*SEW partials

**Single-width floating-point**:
- [ ] vfredosum.vs - **Complex**: Must sum in strict element order. Options:
      (a) Serial chain: jamlet 0→1→2→...→n-1, each adds its elements to running sum (slow)
      (b) Use vfredusum implementation (allowed by spec as valid implementation)
- [ ] vfredusum.vs - Same J2J tree as integer, but FP add. Spec allows any deterministic tree.
- [ ] vfredmax.vs / vfredmin.vs - Could use sync network MIN/MAX, but FP NaN handling may
      complicate this (need to check if sync network can handle FP comparison semantics)

**Widening floating-point**:
- [ ] vfwredosum.vs / vfwredusum.vs - Promote elements to 2*SEW before local reduction, tree
      uses 2*SEW partials

#### 3. Scalar-Vector Element Access
Element 0 lives in a specific jamlet determined by word_order. Scalar registers live in lamlet.

**Implementation approach**:
- Lamlet determines which jamlet holds element 0: `j_coords = vw_index_to_j_coords(0)`
- For vmv.x.s: Send request to that jamlet, jamlet reads RF, sends value back to lamlet
- For vmv.s.x: Lamlet sends scalar value to that jamlet, jamlet writes to RF element 0

- [ ] vmv.x.s - New message type `READ_REG_ELEMENT_REQ/RESP`. Jamlet reads element 0, returns.
- [ ] vmv.s.x - New message type `WRITE_REG_ELEMENT_REQ/RESP`. Jamlet writes element 0.
- [ ] vfmv.f.s / vfmv.s.f - Same as above, just FP register instead of integer.

### Local Operations (No Cross-Jamlet Communication)

These operations work independently within each jamlet.

#### 4. Element Index Generation
- [ ] vid.v - Vector element index (each jamlet computes its own indices)

#### 5. Whole Register Operations
- [ ] vmv1r.v, vmv2r.v, vmv4r.v, vmv8r.v - Whole register moves (local copy)
- [ ] vl1r.v, vl2r.v, etc. / vs1r.v, vs2r.v, etc. - Whole register load/store

#### 6. Special Loads
- [ ] Fault-only-first loads (vle*ff.v) - Local with vl update coordination

#### 7. Segment Load/Store
- [ ] vlseg2-8 / vsseg2-8 (unit-stride)
- [ ] vlsseg2-8 / vssseg2-8 (strided)
- [ ] vluxseg / vsuxseg (unordered indexed)
- [ ] vloxseg / vsoxseg (ordered indexed)

---

## Already Implemented

### Memory Operations
- Unit-stride load/store (vle/vse) ✓
- Strided load/store (vlse/vsse) ✓
- Indexed load/store unordered (vluxei/vsuxei) ✓
- Indexed load/store ordered (vloxei/vsoxei) ✓
- Page fault handling ✓

### Infrastructure
- ReadMemWord/WriteMemWord transactions ✓
- LoadStride/StoreStride transactions ✓
- Synchronization network (with MIN aggregation) ✓
- Monitor/tracing system ✓
