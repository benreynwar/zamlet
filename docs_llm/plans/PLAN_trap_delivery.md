# PLAN: Page Fault Trap Delivery

## Context

Today the python model silently mishandles page faults during loads and stores:

- **Vector** (`VleV`, `VseV`, `VlrV`, `VsrV`, `VlseV`, `VsseV`, `VlsegV`, `VssegV`,
  `VIndexedLoad`, `VIndexedStore` in `python/zamlet/instructions/vector.py`): each
  calls `s.vload`/`s.vstore` and discards the returned `VectorOpResult`. The
  underlying machinery (`unordered.vloadstore` → `check_pages_for_access` at
  `python/zamlet/lamlet/unordered.py:451-461`) detects the first faulting element,
  trims `n_elements` so writes stop precisely at `[start, fault_elem)`, and returns
  the fault info — but no instruction class reads it. Programs continue with
  partially-written destination registers and no signal that anything went wrong.
- **Scalar** (`Sb/Sh/Sw/Sd/Lb/Lbu/Lh/Lhu/Lw/Lwu/Ld` in
  `python/zamlet/instructions/memory.py`): all funnel through `s.set_memory` /
  `s.get_memory` (`python/zamlet/oamlet/oamlet.py:1170, 1282`). These call
  `is_vpu(self.tlb)` → `tlb.get_page_info` (`addresses.py:360-364`), which raises
  `ValueError` on an unmapped page (Python crash, not a trap), and which never
  checks `readable`/`writable`, so permission faults silently succeed.

The existing trap CSRs (`mtvec`, `mepc`, `mcause`, `mtval`, `mstatus`) are *named*
in `system.py:CSR_NAMES` but unbacked beyond the generic dict in
`scalar.py:194-203` (returns zero bytes for unset). `Mret` and `Sret` in
`system.py:130-162` are stubs that just `s.pc += 4`.

This plan builds the minimum trap-delivery primitive end-to-end: a `deliver_trap`
method on Oamlet, a real `Mret`, wired into all vector load/store classes and all
scalar load/store paths. Resume from `vstart` is plumbed in but only fully works
once the existing `vstart` TODO lands (most vector ops hardcode `start_index=0`).

The follow-up plan (vle*ff) builds directly on `deliver_trap`: ff is "the load
that doesn't trap when `element_index > 0` — it trims `vl` instead."

## Approach

Build the trap delivery primitive once, wire all faulting paths through it.
Vector ops already detect faults — they just need to route the result. Scalar
ops need a fault check added at the `set_memory`/`get_memory` boundary, then
the same routing.

For test infrastructure, install a real RISC-V trap handler in scalar memory
and point `mtvec` at it; this exercises the trap-delivery → `mret` cycle
end-to-end rather than catching a Python exception.

### Step 1 — Trap CSR initialization

In `Oamlet.__init__` (or `Scalar.__init__`), initialize trap CSRs to defined
values (zero is fine for all of them — `mtvec=0` will be the sentinel for "no
handler installed"). No structural change to the CSR dict; just guarantee
lookups have a value.

### Step 2 — `deliver_trap` primitive

Add `Oamlet.deliver_trap(cause: int, mtval: int, faulting_pc: int)`:

- Read `mtvec`. Assert `mtvec != 0` with a clear message (`"page fault at
  pc=0xX, addr=0xY: no trap handler installed (mtvec=0). Tests must install
  a handler before triggering faults."`).
- Save: `mepc = faulting_pc`, `mcause = cause`, `mtval = mtval`.
- Save `mstatus.MIE → MPIE`, clear `MIE`. Set `MPP` to current privilege
  (machine mode = 3, since we don't model privilege transitions yet).
- Set `s.pc = mtvec` (direct mode only; vectored mode ignored for now).
- Do NOT return a value — caller uses fact that `s.pc` was redirected.

Cause codes per RISC-V privileged spec (define as constants in `system.py` or a
new module):
- 12 `INSTRUCTION_PAGE_FAULT` (out of scope; instruction fetch faults aren't on
  the table here).
- 13 `LOAD_PAGE_FAULT`
- 15 `STORE_PAGE_FAULT`
- 5 `LOAD_ACCESS_FAULT` (used for `READ_FAULT` from `TLBFaultType`)
- 7 `STORE_ACCESS_FAULT` (used for `WRITE_FAULT`)

Map `TLBFaultType` → cause code in a small helper.

### Step 3 — Real `Mret`

Replace `Mret.update_state` (`system.py:130-145`):

- Read `mepc`, set `s.pc = mepc` (no `+= 4`).
- Restore `mstatus.MPIE → MIE`. Set `MPIE = 1`. (Spec also restores `MPP`; defer
  privilege modeling.)
- Leave `vstart` alone — the resumed instruction reads it on entry.

`Sret` stays as-is; supervisor mode isn't modeled.

### Step 4 — Wire vector load/store classes

In each of the 10 classes
(`VleV` v.py:163, `VseV` :241, `VlrV` :199, `VsrV` :278, `VlseV` :318, `VsseV`
:359, `VlsegV` :400 — currently broken, will route via `vsegload` later but the
deliver_trap pattern is the same, `VssegV` :451 — same, `VIndexedLoad` :2011,
`VIndexedStore` :2079):

```python
result = await s.vload(...)  # or vstore
if not result.success:
    s.vstart = result.element_index
    fault_addr = ...  # need to compute from start_addr + element_index*ew
    s.deliver_trap(cause=_cause_for(result.fault_type, is_store=...),
                   mtval=fault_addr, faulting_pc=s.pc)
    s.monitor.finalize_children(span_id)
    return  # do NOT s.pc += 4
s.monitor.finalize_children(span_id)
s.pc += 4
```

Implementation detail: `VectorOpResult` (`addresses.py:198-207`) currently has
`fault_type` and `element_index` but not `fault_addr`. Either:
(a) Compute `fault_addr` in the instruction class from `addr + element_index * stride`.
(b) Add `fault_addr: int | None = None` to `VectorOpResult` and populate it
    in `check_pages_for_access` (`unordered.py:59-79`).

Prefer (b) — strided/indexed don't have a simple `addr + i*ew` formula and
the fault-detection site already has the exact faulting address. Add the
field, populate at the one site that returns a faulting result.

For indexed ordered loads: the cross-jamlet aggregation in
`resolve_fault_sync` (`unordered.py:648-665`) already returns the
minimum-element-index fault — fault_addr should also propagate through there.

### Step 5 — Wire scalar load/store paths

`s.set_memory` and `s.get_memory` (`oamlet.py:1170-1211, 1282`) need to check
access before the page-table lookup that currently raises:

- Before `is_vpu(self.tlb)` resolves, call `tlb.check_access(byt_address,
  is_write=...)`. If non-NONE, call `s.deliver_trap(...)` with appropriate cause
  and the byte address as `mtval`, then *return* (the caller — a scalar
  instruction class — must see the fault).

But `set_memory` / `get_memory` currently return `None` / a future of bytes.
They have no fault channel. Two options:

- **(a) Raise a `VectorTrap`-style exception from `deliver_trap` itself** that
  propagates up through `set_memory`/`get_memory` to the instruction class,
  which catches it and treats trap as "PC was redirected, don't increment."
  Ugly but minimal touch on `set_memory`/`get_memory` signatures.
- **(b) Return a result type from `set_memory`/`get_memory`.** Cleaner but
  touches every scalar load/store class to inspect the result.

Recommend **(a)**: define `class TrapDelivered(Exception)` raised inside
`deliver_trap` *after* setting all CSRs and `s.pc`. Each instruction class's
`update_state` wraps its memory access in try/except, catches `TrapDelivered`,
returns without `s.pc += 4`. Vector classes follow the same pattern uniformly.
This eliminates the per-class "remember not to increment pc" plumbing in step 4
too.

So: revise step 2 to raise `TrapDelivered` after setting state. Revise step 4
to use try/except. Revise step 5 to do the same.

Replace the `ValueError` at `addresses.py:362-364` with a `deliver_trap` call —
or better, leave it raising `ValueError` but ensure scalar instructions check
access *before* they get to `get_page_info`. The remaining `ValueError` then
becomes a real bug indicator (an internal model state that shouldn't happen
once explicit checks are in).

### Step 6 — Test infrastructure

In `python/zamlet/tests/test_utils.py`:

- `install_trap_handler(s, handler_addr_in_scalar_memory) -> int` — assemble
  a minimal handler (read mcause/mtval/mepc into known scratch regs, then
  `mret`), write it to scalar memory, set `mtvec = handler_addr`, return the
  scratch reg numbers / addresses where the trap state was recorded.
- A higher-level helper that wraps an instruction sequence, runs it, and
  returns the recorded trap state (or None if no trap fired).

Handler choice: ~6-8 RISC-V instructions. Reads mcause via `csrr`, stores to a
known memory slot. Same for mtval and mepc. Then `mret`. Without
vstart-resumption-aware ops the `mret` will return to the faulting instruction
which will re-fault — for the trap-detection tests, the test should *first*
fix the page (e.g. reset the page-table mapping in the test harness) before
running the resume cycle, or simply assert the trap fired and exit.

### Step 7 — Tests

New test file `python/zamlet/tests/test_trap_delivery.py`:

- **No-handler vector**: `mtvec=0`, run a `vle32` against an unmapped page,
  expect AssertionError from `deliver_trap`.
- **Vector unit-stride load fault**: install handler, run `vle32` spanning
  unmapped page, verify `mcause=13`, `mtval=` first faulting address,
  `mepc=` instruction PC, `vstart=` faulting element index. Verify destination
  vector register has elements `[0, vstart)` written and elements
  `[vstart, vl)` undisturbed.
- **Vector unit-stride store fault**: same, expect `mcause=15`.
- **Vector strided/indexed load+store fault**: same pattern with `VlseV`,
  `VsseV`, `VIndexedLoad/Store` (ordered + unordered).
- **Vector permission fault**: mark page non-readable / non-writable, expect
  `mcause=5/7`.
- **Scalar load/store fault**: `Lw` / `Sw` against unmapped page → `mcause=13/15`,
  `mtval=` faulting address, `mepc=` instruction PC. Same for permission faults.
- **Mret cycle**: install handler that fixes the page (via test harness back
  door, since we don't model handlers that can mmap pages from C), then `mret`s.
  Verify the resumed instruction completes. (This is the test that fails until
  vstart-on-entry support lands; mark `xfail` with a TODO ref.)

## Files modified

- `python/zamlet/oamlet/oamlet.py` — add `deliver_trap`, init trap CSRs.
- `python/zamlet/oamlet/scalar.py` — possibly init trap CSRs here instead.
- `python/zamlet/instructions/system.py` — fix `Mret`, add cause-code constants
  and `TrapDelivered` exception (or new module for these).
- `python/zamlet/instructions/vector.py` — wire 10 classes through try/except.
- `python/zamlet/instructions/memory.py` — wire scalar load/store classes
  through try/except (11 classes).
- `python/zamlet/oamlet/oamlet.py` — add `tlb.check_access` calls in
  `set_memory`/`get_memory`.
- `python/zamlet/addresses.py` — add `fault_addr` to `VectorOpResult`.
- `python/zamlet/lamlet/unordered.py` — populate `fault_addr` in
  `check_pages_for_access`; propagate through `resolve_fault_sync`.
- `python/zamlet/lamlet/ordered.py` — same for the ordered-indexed fault paths.
- `python/zamlet/tests/test_utils.py` — `install_trap_handler` helper.
- `python/zamlet/tests/test_trap_delivery.py` — new.

## Reused

- `addresses.TLBFaultType` (`addresses.py`) — fault categorization.
- `tlb.check_access` (`addresses.py:366-376`) — for adding scalar fault checks.
- `addresses.VectorOpResult` (`addresses.py:198-207`) — extended with
  `fault_addr`.
- `lamlet.unordered.check_pages_for_access` (`unordered.py:59-79`) — already
  the canonical vector fault-detection site.
- `lamlet.unordered.resolve_fault_sync` (`unordered.py:648-665`) — cross-jamlet
  fault aggregation for ordered indexed.

## Out of scope (deliberate)

- **Vstart-on-entry honoring across all vector ops.** Already a separate TODO
  entry. Without it, mret will re-fault instead of resuming. Plan plumbs vstart
  on the trap side; the resume side is a separate item.
- **Vle\*ff.** Follow-up plan; trivially small once `deliver_trap` exists.
- **Vlseg\*ff and the rest of segment work.** Separate plans already discussed.
- **Privilege levels.** `MPP` always treated as machine mode. No supervisor.
- **Vectored mode mtvec.** Direct mode only.
- **Instruction fetch faults.** No machinery for instruction-fetch trapping.
- **Vector trap CSR access via csrr/csrw on vstart/vl/vtype.** These attributes
  live outside `Scalar.csr`; csrr would return zero. Pre-existing bug,
  separate.
- **`Sret` and supervisor trap delivery.** Stub stays.
- **Misaligned-access trapping.** No alignment checks.

## Verification

Run the new test file:

```
bazel test //python/zamlet/tests:test_trap_delivery --test_output=streamed
```

Run the existing fault tests to ensure they still pass (they bypass the
instruction class layer and call `s.vload/vstore` directly, so they should be
unaffected):

```
bazel test //python/zamlet/tests:test_indexed_load --test_output=streamed
bazel test //python/zamlet/tests:test_indexed_store --test_output=streamed
bazel test //python/zamlet/tests:test_strided_load --test_output=streamed
bazel test //python/zamlet/tests:test_strided_store --test_output=streamed
bazel test //python/zamlet/tests:test_ordered_indexed_load --test_output=streamed
bazel test //python/zamlet/tests:test_ordered_indexed_store --test_output=streamed
```

Spot-check a few non-fault vector and scalar tests to confirm the
try/except wrapper hasn't regressed the success path.

## Open questions left for implementation

1. Should the `TrapDelivered` exception carry no payload (state already on
   Oamlet) or carry a struct mirroring the trap? Lean payload-less; CSRs are
   the source of truth.
2. Where to declare cause-code constants? `system.py` has the CSR table; a
   new `trap.py` module is cleaner if there'll be more (interrupt causes,
   delegation bits etc.) — defer until needed.
3. For scalar `set_memory`/`get_memory` checking access byte-by-byte: probably
   wasteful. Hoist the check to the start of the operation and check just the
   range covered.
