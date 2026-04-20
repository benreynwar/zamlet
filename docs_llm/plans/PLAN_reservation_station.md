# Plan: Kamlet Reservation Station

## Context

The kamlet currently processes instructions strictly in-order: it pops one instruction
from its queue, renames registers, waits for register availability, executes, then
moves to the next instruction. If instruction N is waiting for registers (e.g., a
scatter store waiting for gather results), instruction N+1 cannot even be renamed.

This causes head-of-line blocking. In the bitreverse_reorder64 kernel, the scatter
store from iteration i blocks the index loads of iteration i+1.

## Design overview

Split kamlet instruction processing into three stages:
1. **Admit** (in-order): pop from queue. For station-path instructions,
   this is register renaming (arch->phys). For bypass instructions
   (SetIndexBound, SyncTrigger), this is the full work inline.
2. **Reservation station**: buffer of admitted station-path entries
   waiting for readiness.
3. **Execute** (out-of-order): pick oldest ready entry, execute it.

`admit()` returns a bool: True means "I set self.renamed, put me in
the station", False means "I did my work inline, discard me".

## Renamed dataclass

A flat dataclass on `kinstructions.py`. Each KInstr has
`renamed: Renamed | None` set during admit (for station-path
instructions). `Renamed` holds only state that isn't already on the
kinstruction — arch→phys translations and snapshots of kamlet state
at admit time (e.g. index_bound_bits). Fields already on the
kinstruction (like `k_maddr`) are read directly from the instruction.

**Readiness fields** (used by `is_ready`):
- `order: int` — monotonic counter assigned during rename, used for memory
  ordering comparisons
- `read_pregs: list[int]` — up to ~17 pregs (8 src + 8 src2 + 1 mask)
- `write_pregs: list[int]` — up to ~8 pregs (8 dst)
- `writes_all_memory: bool`
- `reads_all_memory: bool`
- `cache_is_read: bool`
- `cache_is_write: bool`
- `writeset_ident: int | None`
- `needs_witem: bool`

**Phys reg mappings** (used by execute, lists indexed by vline offset from
base arch reg, None for vlines not accessed):
- `src_pregs: list[int | None] | None` — first source (data for stores,
  src1 for arith, data for gather)
- `dst_pregs: list[int | None] | None` — destination
- `src2_pregs: list[int | None] | None` — second source (index vector for
  indexed ops, src2 for arith)
- `mask_preg: int | None`
- `index_bound_bits: int`

With lmul max=8, worst case is ~25 pregs per entry (8+8+8+1). The station
is shallow so wide entries are acceptable — more important to have depth
to look past blocked instructions.

## Reservation station

A single reservation station holds all renamed instructions. Each entry
tracks per-preg ready bits that are updated when the scoreboard signals
preg availability, so dispatch readiness is a simple AND of bits plus
memory ordering checks — no per-cycle scoreboard queries.

In the python model, we can just check the scoreboard directly each cycle
rather than maintaining ready bits.

### Instructions that bypass the reservation station

- `SetIndexBound`: no register access, execute immediately during rename
- `SyncTrigger`: no register access, execute immediately

`FreeRegister` goes through the deferred-free mechanism (see below), not the
reservation station.

## Deferred phys reg freeing

With in-order execution, rotating the rename table during `w(arch)` can
return the old phys to the free queue immediately, because the old writer
has already completed by the time the rotation happens.

With out-of-order execution, the old writer may still be in the
reservation station when rename rotates. Returning the old phys to the
free queue immediately is unsafe — another rename could allocate it and
clobber the in-flight writer's destination.

Fix: when `allocate_write(arch)` rotates an old phys out, put it in a
**pending free list** rather than the real free queue. A preg in pending
free is moved to the real free queue when the scoreboard signals it has
no active locks (no reads, no writes in flight).

Same mechanism for `FreeRegister`: the preg goes to pending free, and is
released to the real free queue once the scoreboard clears it.

`allocate_write` pulls fresh pregs from the real free queue only. It
never sees pending free.

## is_ready

A single generic function. Checks:

1. **RF available**: all read_pregs can_read, all write_pregs can_write
2. **Memory ordering** (scan station for entries with lower `order`):
   - `writes_all_memory` entry: blocked by older entry with different
     `writeset_ident` that has `cache_is_read`, `cache_is_write`,
     `reads_all_memory`, or `writes_all_memory`
   - `reads_all_memory` entry: blocked by older entry with different
     `writeset_ident` that has `cache_is_write` or `writes_all_memory`
   - `cache_is_write` entry: blocked by older entry with different
     `writeset_ident` that has `writes_all_memory` or `reads_all_memory`
   - `cache_is_read` entry: blocked by older entry with different
     `writeset_ident` that has `writes_all_memory`
3. **Witem capacity**: if `needs_witem`, the witem buffer has space
4. **Cache slot**: if `cache_is_read` or `cache_is_write`, slot is
   available and ready (no conflicting slot users)

These checks replace the blocking waits in `cache_table.add_witem`. The
execute phase calls `add_witem_immediately` (synchronous, asserts readiness).

## Changes to _run_instructions

Currently one coroutine. Split into two:

**`_admit_instructions`**: each cycle, if instruction queue is non-empty
and reservation station is not full, pop instruction and `await
instr.admit(kamlet)`. If admit returns True, assign `renamed.order` and
append to the station. If False, the instruction did its work inline
(bypass ops) or delegated to `update_kamlet` (legacy migration path).

**`_dispatch_from_reservation_station`**: each cycle, scan station
oldest-first (by `order`), pick the first entry where `is_ready` returns
True, remove it, call `instr.execute(kamlet)`. One dispatch per cycle.

## Changes to instruction classes

Each instruction class gets:
- `admit(kamlet) -> bool`: the pop-time handler. For station-path
  instructions: does arch->phys translation, sets `self.renamed` with
  preg lists, memory flags, and writeset_ident; returns True. For
  bypass instructions: does the full work inline; returns False.
- `execute(kamlet)` (station-path only, synchronous): everything after
  is_ready confirms preconditions — `rf_info.start()`, witem creation
  or computation, `add_witem_immediately()` or `finalize_kinstr_exec()`.
  Reads phys regs from `self.renamed`. Must complete without awaiting;
  is_ready is responsible for ensuring every resource is available.

The base `KInstr.admit` default delegates to the legacy `update_kamlet`
and returns False, so non-migrated instructions keep working during the
step-by-step conversion. `update_kamlet` is removed per instruction as
that instruction is migrated.

### Preg list conventions

Preg lists on `Renamed` are indexed by vline offset from the base arch
register. Entries for vlines not accessed are `None`. The execute phase
converts to dicts `{vline: preg}` (filtering out None) when passing to
witem constructors that expect dict-keyed-by-vline.

## Implementation order

1. Finalize `Renamed` dataclass on `kinstructions.py`
2. Add `is_ready()` function to kamlet.py
3. Add reservation station buffer and the two coroutines to kamlet.py
   (admit + dispatch)
4. Implement deferred-free mechanism in rename_table.py
5. Convert `StoreIndexedUnordered` and `LoadIndexedUnordered` to
   admit/execute (the bottleneck for bitreverse_reorder64)
6. Run bitreverse_reorder64 to verify iteration overlap
7. Convert remaining instruction types
8. Run full test suite

## Key files

- `python/zamlet/kamlet/kinstructions.py` — Renamed dataclass, KInstr base
- `python/zamlet/kamlet/kamlet.py` — reservation station, is_ready,
  _admit_instructions, _dispatch_from_reservation_station
- `python/zamlet/transactions/store_indexed_unordered.py`
- `python/zamlet/transactions/load_indexed_unordered.py`
- `python/zamlet/transactions/store_stride.py`
- `python/zamlet/transactions/load_stride.py`
- `python/zamlet/transactions/reg_gather.py`
- All other transaction and kinstructions files for step 6

## Verification

- bitreverse_reorder64 n=64 k2x2_j2x2: iterations should overlap on kamlet
- Full kernel test suite: no regressions
