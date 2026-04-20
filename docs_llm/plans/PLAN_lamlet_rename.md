# PLAN: Kamlet register rename

(Originally titled "Lamlet register rename"; the design moved to the kamlet.
Filename kept for continuity.)

## Goal

Make rolled vector loops pipeline across iterations on the zamlet hardware, so
performance-oriented vector kernels can be written as simple rolled loops in C
rather than as manually unrolled assembly (or as 8x-unrolled C with many live
vectors).

This is a prerequisite for writing performant FFT and other vector kernels in
plain C without hand-tuning each one around the current model's cross-iteration
serialization.

## Motivation

### The problem

The zamlet kamlet register file today is a 40-entry physical register file:
entries 0..31 are architectural, entries 32..39 are a dedicated "temp" pool
allocated via `alloc_temp_regs` / `free_temp_regs` for scratch inside compound
lamlet operations (reductions, strided batch helpers, indexed-load batch
helpers, etc).

The kamlet's `KamletRegisterFile` is a scoreboard keyed on architectural names:
each arch reg has a single set of outstanding read tokens and a single write
token. `can_write(reg)` is false if any reader or writer is still outstanding.
Consequently, a write-after-write or write-after-read on the same architectural
name blocks until the previous op fully retires.

For a rolled gather/scatter loop such as

```
.Lloop:
  vle32.v    v0, (a3)       # load read index
  vle32.v    v1, (a4)       # load write index
  vluxei32.v v2, (a1), v0   # gather (slow — memory-bound)
  vsuxei32.v v2, (a2), v1   # scatter (slow — memory-bound)
  ...
  bnez a0, .Lloop
```

every iteration reuses v0, v1, v2. Iteration i+1's `vluxei32.v v2, (a1), v0`
cannot begin until iteration i's `vluxei32.v v2, ...` has fully retired,
because both target architectural v2. Throughput collapses to ~1 gather per
gather latency, rather than ~1 gather per dispatch cycle.

The current workaround is to manually unroll the source loop so distinct
architectural names (`v2..v9` for data, `v10..v17` for read indices, etc.) are
used across the unrolled lanes. This is what the existing hand-written
`bitreverse_reorder.S` does. Writing every vector kernel this way is tedious,
error-prone, and consumes the architectural register file even when the
hardware has plenty of physical storage available.

### The two dependency kinds and why they need different fixes

Cross-iteration dependencies on a reused arch register fall into two kinds:

1. **WAR** — iteration i reads the register, iteration i+1 writes it.
   Example: iter i's vluxei reads v0 (the index), iter i+1's vle writes v0.
   This stalls unnecessarily whenever the reader holds its read lock longer
   than it needs the value. The read lock is conservatively held until full
   witem retirement even though the consumer has already captured the value
   into its outgoing packets.

2. **WAW** — iteration i writes the register, iteration i+1 writes it.
   Example: iter i's vluxei writes v2, iter i+1's vluxei writes v2.
   The writes must serialize relative to each other to preserve the correct
   final value, and the only way to let both be in flight simultaneously is
   to give them different physical storage.

WAR is addressable by releasing read locks earlier in the witem lifecycle. WAW
fundamentally requires distinct physical storage for the in-flight and
next-iteration values, which means some form of rename.

## Architectural decision

### Rename lives in each kamlet, independently

Each kamlet owns its own `RegisterRenameTable`: an `n_vregs`-entry `arch →
phys` mapping plus a free queue of non-live physical registers. Every kinstr
the lamlet dispatches to the kamlets carries arch register indices. The kamlet
renames on dispatch, pulling a phys from its free queue for each destination
and looking up the current phys for each source. The kamlet scoreboard then
operates on phys indices.

Kamlet rename tables are independent and can diverge. Inter-kamlet messages
that reference register indices carry enough context that the sender and
receiver can each translate between their own arch and phys spaces.

Rename is **pessimistic**: a write only pulls a phys from the free queue once
a slot is actually available (i.e. not still busy in the scoreboard). No
"optimistic allocator plus safety net" — rename and scoreboard live in the same
module and share state naturally.

### Register file and free-queue sizing

`n_vregs` (currently 40) is a single parameter that is both the architectural
name space and the physical slot count:

- Names 0..31 are ISA arch regs, always mapped (user program state).
- Names 32..39 are **scratch names**, usually unmapped. Their phys slots sit in
  the free queue whenever no compound op is holding them.

Steady-state free queue depth ≈ 8, because scratch names are usually dead.
That gives ~8 in-flight rolled-loop iterations of pipelining headroom for
kernels that write a single arch reg per iteration.

To increase pipelining depth later, increase `n_vregs` (e.g. 48 = 32 + 16
scratch). Both the arch field and the phys field in kinstructions and
scoreboard entries have width `log2Ceil(n_vregs)`, so scaling is a single
parameter change.

### Multi-vline kinstructions carry an arch base only

The python model already packs many consecutive vlines into one kinstruction
(e.g. `VArithVvOp`, `Load`, `Store` sweep over `n_elements` elements spanning
multiple vlines via `src+i` / `dst+i`). This shortcut is kept. Under
kamlet-side rename, the kinstr carries one arch base per register role; the
kamlet iterates internally over the vlines and renames each one independently.
No per-vline phys hints are stuffed into the encoding — multi-vline kinstrs
stay tight.

### `FreeTemp` kinstruction for scratch release

Scratch arch names (32..39) do not rotate their phys automatically via WAW the
way user arch regs do, because the lamlet does not keep rewriting them once a
compound op is done. Without an explicit release, phys slots assigned to
scratch arch regs would stay live in the kamlet's view forever and the free
queue would slowly shrink.

A new `FreeTemp(arch)` kinstruction tells the kamlet:
- The current arch → phys mapping is dead; return the phys to the free queue.
- Mark `arch[N]` as invalid.

If a subsequent kinstr reads an invalidated arch before writing it, that is a
lamlet bug and the kamlet asserts. The freed phys does not become reusable
until the scoreboard drains its existing entries; the free queue is just a
candidate list, the scoreboard remains authoritative.

The lamlet emits `FreeTemp` at the end of every compound operation, for every
scratch arch index it used.

### Lamlet scratch-arch tracker replaces `alloc_temp_regs`

The lamlet no longer owns a rename table. It keeps a tiny tracker of "which
scratch arch names (32..n_vregs-1) are currently held by an active compound
op." When a compound op starts it picks an unused scratch arch name; when the
op ends it emits `FreeTemp` and marks the scratch name unused again.

This replaces `alloc_temp_regs` / `free_temp_regs` / `_temp_regs` /
`get_scratch_page` in `oamlet.py`. It is strictly smaller than a full rename
table: no arch → phys mapping, no free queue, just a bit vector of "in use."

## Scope

### In scope

- Kamlet `RegisterRenameTable`: dispatch-time rename for every kinstruction
  that references vector registers, per-kamlet independent state.
- `FreeTemp` kinstruction: encoding, lamlet-side emission, kamlet-side
  handler.
- Replacement of the lamlet's `alloc_temp_regs` / `free_temp_regs` with a
  scratch-arch tracker. Callers:
  - `python/zamlet/oamlet/reduction.py` (~lines 280, 315)
  - `python/zamlet/lamlet/unordered.py` (strided batch helper, indexed batch
    helper `_vloadstore_indexed_unordered_batched` at ~line 554)
  - `python/zamlet/oamlet/oamlet.py` (~line 1259)
- Every compound op must emit `FreeTemp` at the end for every scratch it used.
- Rolled-loop port of `bitreverse_reorder64` from assembly to C.

### Out of scope

- Expanding `n_vregs` beyond 40 for this pass. Pipelining depth stays at ~8.
- Bit-budget cleanup of all kinstructions, Chisel-compatible encodings for
  python-only vector ops, opcode allocation, mask field design. Tracked in
  `docs/TODO.md`.
- Chisel RTL changes. Python model only.
- Any Tomasulo / reservation-station machinery.
- Rewriting existing unrolled kernels to rolled form. Only `bitreverse_reorder64`
  is ported as the first demonstration.

### Open questions

- **Does any inter-kamlet or kamlet → jamlet message carry a register index
  whose interpretation assumes sender and receiver share a rename table?**
  The architectural claim is that each kamlet can translate phys ↔ arch
  locally, so cross-kamlet divergence is fine. Worth a targeted grep before
  committing — look for messages carrying `RegAddr` between kamlets, and
  confirm each such message survives independent per-kamlet rename.
- **Where exactly does each compound op end?** Each caller of the old
  `alloc_temp_regs` needs a clearly identified "release point" where
  `FreeTemp` gets emitted. If any path can exit early without reaching the
  release, that's a scratch leak.
- **Does `oamlet.vrf_ordering: List[Ordering|None]` (indexed by arch) still
  make sense?** It is lamlet-side state and remains keyed on arch. Should be
  a no-op change but worth verifying.
- **Does the kamlet scoreboard (`KamletRegisterFile` in
  `register_file_slot.py`) need any change beyond "sees phys indices instead
  of arch"?** Should be a drop-in substitution, but any code path that
  assumes `reg < 32` would misbehave.

## Execution steps

### Step 1: witem finalize split — **SKIPPED**

Not much advantage: source reads are needed until the response comes back
(a dropped packet re-enters `_send_req` and re-reads the index/mask/src
registers), so reads can only be released once all transactions are COMPLETE,
which is essentially when the witem retires anyway.

### Step 2: lamlet rename table — **SUPERSEDED**

A `RegisterRenameTable` was added at `python/zamlet/lamlet/rename_table.py`
and `oamlet`'s `alloc_temp_regs` / `free_temp_regs` were routed through it.
Under the kamlet-side design this needs to move: the full rename table lives
in the kamlet, and the lamlet keeps only a small scratch-arch tracker. The
Step 2 file can be salvaged as a starting point for the kamlet-side table;
the lamlet-side delegate code needs to be rewritten as the tracker.

### Step 3: kamlet-side rename — current step

Substeps:

1. **Move rename table into the kamlet.** Port (or copy and adapt)
   `python/zamlet/lamlet/rename_table.py` to `python/zamlet/kamlet/`. Each
   `Kamlet` constructs its own instance. Initial mapping: arch 0..31 →
   phys 0..31; arch 32..n_vregs-1 invalid; free queue = phys 32..n_vregs-1.

2. **Wire rename into the kamlet dispatch path.** Before
   `wait_for_rf_available` / `rf_info.start`, translate each kinstr's source
   arch fields via `lookup_read` and each destination arch field via
   `allocate_write`. The scoreboard sees phys indices from this point on.
   For multi-vline kinstrs, the kamlet iterates over `base + i` for each
   vline and renames each independently.

3. **Add the `FreeTemp` kinstr.** Define the dataclass in
   `kamlet/kinstructions.py` (no Chisel encoding needed for this pass — the
   bit-budget cleanup is in TODO). Add a kamlet handler that invalidates
   `arch[N]` and pushes the current phys to the free queue tail. Assert on
   read-after-invalidate.

4. **Replace `alloc_temp_regs` / `free_temp_regs` with the scratch-arch
   tracker** on the lamlet side. Keep the same call sites but now they just
   bit-flip a "scratch in use" vector and return an arch index.

5. **Emit `FreeTemp` at the end of every compound op.** Audit every current
   caller of `alloc_temp_regs` and identify the exit point where the scratch
   becomes dead. Emit one `FreeTemp` per scratch arch used.

6. **Delete `python/zamlet/lamlet/rename_table.py`** (the lamlet no longer
   owns a rename table). Remove all remaining references.

7. **Verify the open questions above** (cross-kamlet register-index
   messages, compound-op release points, scoreboard phys-index assumptions).

Success criterion: entire existing test suite passes with kamlet-side rename
active, with scratch arch regs correctly released by `FreeTemp`.

### Step 4: write rolled `bitreverse_reorder64.c`

Replace `python/zamlet/kernel_tests/bitreverse_reorder/bitreverse_reorder64.S`
with a rolled C loop using `riscv_vector.h` intrinsics.

Signature unchanged:
`void bitreverse_reorder64(size_t n, const int64_t* src, int64_t* dst,
                           const uint32_t* read_idx, const uint32_t* write_idx)`

Structure:
```c
if (n == 0) return;
unsigned bits = 64 - __builtin_clzl(n * sizeof(int64_t) - 1);
zamlet_set_index_bound(bits);
zamlet_begin_writeset();
while (n > 0) {
    size_t vl = __riscv_vsetvl_e64m1(n);
    vuint32mf2_t r = __riscv_vle32_v_u32mf2(read_idx, vl);
    vuint32mf2_t w = __riscv_vle32_v_u32mf2(write_idx, vl);
    vint64m1_t   d = __riscv_vluxei32_v_i64m1(src, r, vl);
    __riscv_vsuxei32_v_i64m1(dst, w, d, vl);
    read_idx += vl;
    write_idx += vl;
    n -= vl;
}
zamlet_end_writeset();
zamlet_set_index_bound(0);
```

Uses the existing `zamlet_custom.h` header for custom-opcode wrappers. Update
`python/zamlet/kernel_tests/bitreverse_reorder/BUILD` to replace the `.S`
with the `.c`.

Success criterion: `bitreverse-reorder64` kernel builds, and the existing
kernel test driver (`bitreverse_main64.c`) verifies correctness.

### Step 5: inspect and measure

- Dump the generated RISC-V assembly and confirm no unexpected behaviour
  (single vsetvli before the loop, clean loop body, no spurious spills).
- Run the kernel and inspect the span tree. Confirm: multiple gathers in
  flight, free queue not backpressuring, no kamlet-scoreboard stalls visible.
- Compare cycle counts against the existing hand-written
  `bitreverse_reorder.S` (32-bit unrolled variant), adjusted for element-size
  difference. Rolled C should be within a small constant factor of — ideally
  matching or better than — the hand-unrolled assembly.

### Step 6: unblock and run vec-fft8

- Re-enable the FFT test in `python/zamlet/kernel_tests/fft/BUILD` (currently
  commented out with "Need to fix since bitreverse changes").
- Run `vec-fft8.c` end-to-end. Confirm it passes.
- Inspect `fft8_stage` generated assembly and span trace. Under rename, the
  many live temporaries should no longer force spills; if they do, that is an
  orthogonal compiler investigation.

Success criterion: FFT-8 test passes end-to-end.

## Restart notes

If this plan is resumed in a fresh context:

- The LLVM VPU stack spill patch is already landed — see
  `docs/PLAN_llvm_vpu_spills.md`. Spilling in compiled kernels works.
- `python/zamlet/kernel_tests/common/zamlet_custom.h` already exists with
  wrappers for the three custom-opcode instructions
  (`zamlet_set_index_bound`, `zamlet_begin_writeset`, `zamlet_end_writeset`).
- The kamlet register file scoreboard lives in
  `python/zamlet/register_file_slot.py` (`KamletRegisterFile` class).
- The (to-be-moved) rename table lives in
  `python/zamlet/lamlet/rename_table.py` and needs to be relocated to the
  kamlet and rewired per Step 3.
- Kinstruction bit-budget cleanup is a separate pass, tracked in `docs/TODO.md`,
  not a blocker for the rename work.
- The `bitreverse_reorder` directory has both `bitreverse_reorder.S`
  (32-bit 8x-unrolled hand-tuned, used by a gather/scatter benchmark) and
  `bitreverse_reorder64.S` (64-bit rolled, used by `vec-fft8.c`). This plan
  replaces the 64-bit one with a rolled C version; the 32-bit one is
  untouched.
