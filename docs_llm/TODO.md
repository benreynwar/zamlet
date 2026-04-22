# TODO

- [ ] Switch kernel test C runtime from custom crt.S/syscalls.c to picolibc.
      The current runtime has custom printf/memcpy/etc that may diverge from
      standard behavior, and hand-written header shims. picolibc provides all
      of this correctly for bare-metal RISC-V with Clang.
      See `docs/PLAN_picolibc.md`.
- [ ] Add a Bazel macro that combines genrule + cocotb_binary + py_library + cocotb_test
      to reduce boilerplate in test BUILD files.
- [ ] Packet header bit packing: ReadMemWordHeader and WriteMemWordHeader fields exceed
      the 64-bit header budget. element_index alone is 22 bits but only ~10 bits remain
      after TaggedHeader. Need to decide if 64-bit limit is firm, which fields can be
      derived, and whether some fields only apply to certain message subtypes. Added
      writeset_ident to both headers without resolving packing. When no_response=True
      on WriteMemWordHeader, source_x/source_y (16 bits) are unused and could carry
      writeset_ident in hardware.
- [ ] ew remap infrastructure. Today a store-ew-mismatch is handled by
      `vloadstore` in `lamlet/unordered.py` by storing src to scratch memory and
      reloading at the new ew — slow and can't handle ew=1 because `vload` /
      `vstore` assert `ordering.ew % 8 == 0` (`unordered.py:215,230`). Plan:
      (a) Dedicated register-to-register ew remap kinstr that moves data
          between jamlets via J2J messages (no memory round-trip).
      (b) Load/store support for ew=1 restricted to aligned unit-stride access
          only. Any other ew=1 access (misaligned, strided, or indexed) is
          handled as a fault at the lamlet; the lamlet's fault handler remaps
          the affected page into a temporary memory region at the required
          layout before the op retries.
      (c) Once (a) lands, plumb `ensure_mask_ew1(reg)` at every mask-consumer
          site so mask registers are always read at ew=1 regardless of how
          they were produced. Today those sites just assert ew==1 (see the
          asserts added alongside VmLogicMm); remap is a follow-up.
      (d) Drop the manual ew=1 retag at the end of
          `tests/test_utils.py:setup_mask_register` once ew=1 loads exist —
          the helper currently bulk-loads at ew=64 and then relabels the
          vreg as ew=1 because the byte layout already matches.
- [ ] vstart / start_index is ignored by almost all kinstrs (they hardcode
      start_index=0 in execute and in alloc_dst_pregs). Only vrgather and
      the new VmLogicMm thread `s.vstart` through. RVV spec requires
      elements [0, vstart) to be undisturbed on every vector op. In practice
      today this is harmless because the toolchain always zeros vstart before
      each op, but any trap-resume path or any op that leaves a non-zero
      vstart in an operand will silently clobber the prestart region. Audit /
      fix: VBroadcastOp, VidOp, VArithV{v,x}Op, VCmpV{i,x,v}Op, VUnaryOvOp,
      VmergeVvm / VmergeVim / VmergeVx, VreductionOp, vloadstore paths (these
      honour start_index from the caller but callers typically pass 0),
      slides, and scalar moves that use it implicitly. See
      `docs/PLAN_vta_vma.md` (related tail/mask policy) and the `vrgather`
      implementation as a reference for correct plumbing.
- [ ] Narrowing shifts (vnsrl, vnsra): currently only vnsrl.wi is implemented, and it's
      hacked into VUnaryOvOp which is the wrong place for it. Need to think about how
      narrowing ops should work properly, then implement all 6 forms
      (vnsrl.wv/wx/wi, vnsra.wv/wx/wi).
- [ ] When an instruction writes to a register with a different ew than the existing
      contents, and doesn't update all elements (e.g. masked or vl < vlmax), the
      unwritten elements still have the old ew layout. May need to ew-remap the old
      contents before the partial write so everything is consistent.
- [ ] vta/vma support in the python model. Today the model implicitly does
      fully-undisturbed for both tail and inactive elements, which forces every
      partial-vline write to use rw() under the kamlet rename design and inhibits
      pipelining of partial-vl tail iterations of rolled loops. Adding explicit
      vta/vma plumbing lets the rename allocator pick w()+fill-with-1s instead of
      rw() whenever the spec permits. See `docs/PLAN_vta_vma.md`.
- [ ] Fix scalar floating-point correctness. Several issues, all orthogonal:
      (1) NaN-boxing: producers of F32 values in the 64-bit freg zero-pad instead
      of setting upper 32 bits to 1s; consumers read low 4 bytes without checking
      the NaN-box invariant, so a non-NaN-boxed freg read as F32 does not
      substitute canonical qNaN `0x7fc00000`. Affects `FmvWX`, `Flw`, `_write_fp`,
      `_write_fp_bits`, `FCvt` (F32 dst); and `_read_fp`, `_read_fp_bits`, `FCvt`
      (F32 src). Vector side: `VArithVxFloat` and any future `.vf` forms read
      `scalar_bytes = read_freg(rs1)` without the check. Design plan: thread a
      `width: int` param through `scalar.read_freg`/`write_freg`/`write_freg_future`
      so the box/unbox logic lives in one place. F64, `FMV.X.W`, `FSW` stay
      bit-preserving (width=64, slice). See `docs/PLAN_fp_nan_boxing.md` (deferred).
      (2) Rounding mode: `FCvt` ignores the `rm` field and relies on Python's host
      rounding (truncation for FP→int via `int()`, host RNE for int→FP via
      `struct.pack`). No `fcsr` plumbing, no dynamic-rm lookup.
      (3) NaN payload propagation and exception flags: Python native float
      arithmetic produces implementation-defined NaN bits and does not set
      RISC-V accrued flags (NV/DZ/OF/UF/NX) in `fcsr`.
- [ ] Ordered float reductions: `vfredosum.vs` and `vfwredosum.vs`. Out of scope
      for the original reductions work because they require strictly left-to-right
      accumulation and cannot use a tree. The unordered variants (FREDUSUM,
      FWREDUSUM) are in.
- [ ] Masked `vslide1up.vx` / `vslide1down.vx`. The `Vslide1` class currently
      asserts `vm=1`. Boundary-lane scalar injection needs to read
      `v0[inject_idx]` at the lamlet before issuing the `WriteRegElement`.
- [ ] Non-overlap / register-group-overlap and `vstart` checking for the Ov
      classes, slides, and gathers. RVV spec forbids certain vd/vs overlaps;
      `vstart >= vl` should make the op a no-op.
- [ ] Vector segment loads/stores (vlseg/vsseg + strided/indexed/ff variants).
      Today `VlsegV` and `VssegV` decode but call `s.vsegload`/`s.vsegstore`
      which don't exist; everything else (vlsseg, vluxseg, vloxseg, vsuxseg,
      vsoxseg, vlseg*ff, vle*ff) is unimplemented. Plan, in this order:
      (a) **Fast path first** — NFIELDS ∈ {2,4,8}. Treat as a wide-ew load with
          `ew = nf * field_ew`, giving new effective ew values 128/256/512. With
          the existing consecutive jamlet placement, segment `i` lands entirely
          in jamlet `i mod n_j` at slot `i / n_j`, and the destination field
          registers `v_d..v_d+nf-1` line up at the same `(jamlet, slot)`. So the
          deinterleave is a local in-jamlet fan-out — zero cross-jamlet traffic.
          Required changes:
            - Address generator gains a "burst per element" mode: each element
              step emits `ew / word_size` contiguous word addresses, all routed
              to the same jamlet/slot.
            - During the op, `v_d..v_d+nf-1` are treated as a coupled wide-ew
              register group (like LMUL=nf). Enforce `vd mod nf == 0` and
              `EMUL * nf <= 8`. Hazard tracking covers the whole group.
            - Writeback in each jamlet routes burst word `f` to `v_d+f` at the
              local slot.
            - Strided/indexed segment variants reuse the same per-jamlet
              fan-out; only the address source changes (rs2 stride / vs2 index).
      (b) **Slow path second** — NFIELDS ∈ {3,5,6,7}. `nf * field_ew` isn't a
          power of two and the wide-ew mapping breaks. Fall back to nf
          independent strided passes (stride = nf*field_ew, base offsets
          0, field_ew, ..., (nf-1)*field_ew). Each pass is a vanilla strided
          load/store at normal ew. Correctness only; performance is nf×.
      (c) Fault-only-first variants (`vle*ff`, `vlseg*ff`) last — needs
          jamlet-coordinated vl trimming, lower priority.
      Architectural constraint implied by the fast path: the byte→jamlet
      stripe unit is ew-dependent (ew=64 → 8B stripe, ew=512 → 64B stripe), so
      the byte→page mapping is only well-defined relative to the page's ew
      tag. Raising max pseudo-ew to 512 widens the stripe unit 8×, which
      forces:
        - Minimum page size must hold one full stripe across all jamlets at
          the new max ew (n_j × max_pseudo_ew / 8 bytes), otherwise a page
          can't fully own a contiguous stripe of the data it appears to
          contain.
        - Page-tag bookkeeping must accept 128/256/512 as legal page ews, not
          just transient access modes.
        - Mixed-ew access on a 512-tagged page requires the same remap
          machinery already planned for ew=1 (see ew-remap TODO above).
      Spec ref: `riscv-isa-manual/src/v-st-ext.adoc` lines 1758-1957.
- [ ] Kinstruction bit-budget cleanup. Give every python kinstruction a proper
      bit-packed encoding (`FIELD_SPECS` + `encode()`) matching Chisel-compatible
      64-bit layouts, and design Chisel bundles for the python-only vector ops
      (`VArithV{v,x}Op`, `VCmpV{i,x,v}Op`, `VBroadcastOp`, `VidOp`, `VUnaryOvOp`,
      `VreductionOp`, `VmnandMmOp`, `RegGather`). Also allocate opcodes for
      `IndexedInstr` family (`LoadIdxUnord`/`StoreIdxUnord`/`LoadIdxElement`/
      `StoreIdxElement`) which are currently defined in Chisel but unwired in
      `KInstrOpcode`. Decide mask field representation for bundles that don't have
      one today (`WordInstr`, `J2JInstr`, `StoreScalarInstr`). Delete dead
      `LoadStride`/`StoreStride` kinstruction classes (strided path goes through
      `Load`/`Store` with `stride_bytes`, these classes are imported but never
      instantiated). Verify whether Chisel's `WitemEntry.scala` still uses the
      stride witem types for actual work.
