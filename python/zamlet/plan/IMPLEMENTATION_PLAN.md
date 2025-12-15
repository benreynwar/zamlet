# RISC-V Vector Extension Implementation Plan

## Current Focus: Permutation Instructions (viota.m, vcompress)

See `VCOMPRESS_PLAN.md` for detailed implementation plan.

---

## Implementation Queue

### 1. Permutation & Mask Instructions ← CURRENT
- [ ] viota.m - See VCOMPRESS_PLAN.md (prefix sum infrastructure)
- [ ] vcompress - See VCOMPRESS_PLAN.md (prefix sum + RegScatter)
- [ ] vcpop.m - Mask popcount (reuse prefix sum, return final value)
- [ ] vfirst.m - Find first set mask bit (use MIN in sync network)
- [ ] vid.v - Vector element index (writes 0, 1, 2... to elements)
- [ ] vmsbf.m, vmsif.m, vmsof.m - Mask set before/including/only first
- [ ] vslideup/vslidedown
- [ ] vslide1up/vslide1down
- [ ] vrgather.vv/vx/vi - Can reuse RegGather (inverse of RegScatter)
- [ ] vrgatherei16.vv - Gather with 16-bit indices

### 2. Other Data Movement
- [ ] vmv1r.v, vmv2r.v, vmv4r.v, vmv8r.v - Whole register moves
- [ ] vl1r.v, vl2r.v, etc. / vs1r.v, vs2r.v, etc. - Whole register load/store
- [ ] Fault-only-first loads (vle*ff.v)

### 3. Segment Load/Store
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
- Synchronization network ✓
- Monitor/tracing system ✓
