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
- [ ] Replace store-ew-mismatch workaround (store to scratch memory + reload at new ew)
      with a dedicated register-to-register ew remap kinstr using J2J messages.
      Currently in `vloadstore` in `lamlet/unordered.py`.
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
