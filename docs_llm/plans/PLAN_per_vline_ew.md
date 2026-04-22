# Plan: Per-Vline Element Width Tracking

## Context

The zamlet VPU model currently tracks element width (ew) per page in the TLB. This causes
problems: different operations may use different ews on the same memory, and vector register
spills need to work regardless of ew. We're moving ew tracking from per-page to per-vline
(one word from each jamlet). The ew metadata will be stored in the cache table
alongside vline data and in memlet DRAM. This enables transparent vector register spilling
without special instructions or compiler ew awareness.
The ew metadata will also be stored in memory that the lamlet has access to.

## Design Summary

- Each vline in the cache table and memlet gets an ew tag (default 64 for uninitialized)
- On aligned unit-stride store to entire vline: vline ew tag is set from the instruction's ew
- On aligned unit-stride store to partial vline: vline is remapped to instruction ew, and then store happens.
- On unaligned store, or strided or indexed.  The vline is not remapped.  old vline is kept.

- On load, the memory vline ew is not changed.

- Page-level ew is removed from TLB/LocalAddress/PageInfo
     Hmmm. Maybe the TLB is a good place to handle the per-line ew that the lamlet looks up.
     Need to think about this.

## Steps

### Step 1: Introduce VLineInfo and restructure PageInfo

Add a `VLineInfo` class with its own `GlobalAddress` and `LocalAddress` (which carries
`Ordering`). Restructure `PageInfo`:
- Remove `global_address` and `local_address` fields
- Add `memory_type`, `global_addr` (bytes), `physical_addr` (bytes), `is_vpu` property
- For VPU pages, PageInfo constructs a list of `VLineInfo` objects internally
  (one per vline in the page). Vlines start with `ordering=None`.
- `allocate_memory` no longer takes an ordering parameter

Add TLB helper methods:
- `get_vline_info(address)` — look up VLineInfo by GlobalAddress
- `set_vline_ordering(address, ordering)` — update a vline's ordering

Update `GlobalAddress.to_vpu_addr()` to get ordering and physical address from VLineInfo
instead of `page_info.local_address`. The address translation becomes:
vline_info = tlb.get_vline_info(self), then use vline_info.local_address for both
the physical address and the ordering.

Update all call sites that read `page_info.local_address` or `page_info.global_address`:
- `.is_vpu` → `page_info.is_vpu` (10 sites across addresses.py, oamlet.py,
  lamlet/unordered.py, lamlet/ordered.py, transactions/)
- `.memory_type` → `page_info.memory_type` (3 sites)
- `.addr` → `page_info.physical_addr` (5 sites)
- `.ordering` → `tlb.get_vline_info(addr).local_address.ordering` (7 sites)
- `global_address.addr` → `page_info.global_addr` (2 sites)

Remove ordering parameter from all `allocate_memory` callers:
- `run_oamlet.py` pool allocations
- `get_scratch_page` in `oamlet.py`
- Test files

See `/home/ben/.claude/plans/snazzy-exploring-piglet.md` for full call site table.

**Files**: `python/zamlet/addresses.py`, `python/zamlet/oamlet/oamlet.py`,
`python/zamlet/oamlet/run_oamlet.py`, `python/zamlet/lamlet/unordered.py`,
`python/zamlet/lamlet/ordered.py`, `python/zamlet/transactions/load_gather_base.py`,
`python/zamlet/transactions/store_scatter_base.py`,
`python/zamlet/transactions/load_indexed_element.py`, test files

### Step 2: Set vline ordering on loads and stores

After Step 1, vlines start with `ordering=None`. The ordering must be set before the
address chain can translate addresses (ordering is needed for element reordering).

On loads and stores, the lamlet knows the instruction's ew. Before dispatching, call
`tlb.set_vline_ordering(addr, ordering)` for each affected vline. This sets the ordering
on first access and updates it on subsequent accesses.

For loads: normally the vline ordering is not changed. The exception is weakly
ordered vlines (set by scalar stores) — a vector load promotes these to strongly
ordered using the load's ew. The notsimple load path handles cross-ew loads via
jamlet data movement.

For stores: if the vline already has a different ordering, the data must be remapped
first (see Step 3). If ordering is None or matches, just set it.

Scalar store instructions (sb/sh/sw/sd and compressed variants) set a weak ordering
on uninitialized vlines based on the store width. This weak ordering can be overridden
by a subsequent vector load or store. VLineInfo has a `weakly_ordered` flag to track
this.

**Files**: `python/zamlet/lamlet/unordered.py` (in vloadstore),
`python/zamlet/oamlet/oamlet.py`

### Step 3: Handle vline ew remap

Summary of all load/store cases and what happens with vline ordering:

**Unit-stride aligned store:**
- ew=None: Set ordering to instruction ew. Do store.
- ew match: Do store.
- ew mismatch, full vline: Set ordering to new ew. Do store (overwrites all data).
- ew mismatch, partial vline: Remap vline data to new ew first (load vline into temp
  reg at old ew, store back at new ew). Set ordering. Then do the actual store.

**Unit-stride aligned load:**
- ew=None: Error — reading uninitialized memory.
- ew match: Load normally.
- ew mismatch, not weakly ordered: No problem. J2J handles cross-ew reads.
- ew mismatch, weakly ordered: Remap vline to load's ew first (load into temp reg at
  old ew, store back at new ew, update ordering). Then load normally.

**Unaligned, strided, indexed (load or store):**
- All handled via J2J. No remap. No ordering changes.

Implementation:
- `_set_vline_orderings_unit_stride` stays as a simple non-async ordering setter.
  It only handles cases where no remap is needed (ew=None, ew match, full vline
  overwrite). It skips vlines that need remap.
- `vstore` calls a new async method `_remap_vlines_for_store` before
  `_set_vline_orderings_unit_stride`. This handles partial vlines with ew mismatch:
  load vline into temp reg at old ew, store back at new ew, update ordering.
- `vload` calls a new async method `_remap_vlines_for_load` before dispatching.
  This handles weakly-ordered vlines with ew mismatch: load into temp reg at old ew,
  store back at new ew, update ordering.
- Remove `check_element_width` (replaced by the above).

**Files**: `python/zamlet/oamlet/oamlet.py`

### Step 4: Merge VPU memory pools

With per-vline ew, separate pools per ew are no longer needed. Merge the five 256KB pools
(0x90000000-0x90140000) into a single pool. Update `vpu_alloc.c` to use a single base
address, and update kernel tests and test utilities that reference specific pool addresses.

**Files**:
- `python/zamlet/oamlet/run_oamlet.py` — single pool allocation
- `python/zamlet/kernel_tests/common/vpu_alloc.c` — single allocator
- Kernel test C files that reference pool addresses
- `python/zamlet/tests/test_utils.py`, `test_conditional_kamlet.py` — test pool addresses

### ~~Step 5: Add ew to cache table and memlet~~ (Skipped)

Not needed. The model gets ew from VLineInfo in the TLB. In RTL, the lamlet's ew table
serves the same purpose. No need to duplicate ew into cache lines or memlet DRAM.

### Step 7: Update VPU stack for spills (later, after LLVM changes)

With per-vline ew, the VPU stack needs only one stack pointer (`s11`). Spill stores set
the vline ew. Spill loads read the vline ew and the notsimple load path remaps if needed.
No special instructions or compiler ew tracking required.

This step is model-side only:
- `crt.S`: initialize `s11` to VPU spill region base
- `run_kernel_test.py` / test harness: allocate VPU spill memory region
- Model already handles this transparently with per-vline ew

**Files**: `python/zamlet/kernel_tests/common/crt.S`,
`python/zamlet/kernel_tests/run_kernel_test.py`

## Verification

1. Run all existing kernel tests — they should pass unchanged:
   ```bash
   bazel test //python/zamlet/kernel_tests/... --test_output=streamed \
     --test_env=LOG_LEVEL=WARNING
   ```

2. Write a test that stores a register at ew=32, then loads it back at ew=64 (or vice
   versa) to verify vline ew tracking and the notsimple load remap works.

3. Write a test that spills and restores a vector register through VPU stack memory.

## Future RTL Changes

The following RTL changes would be needed to support per-vline ew in hardware:

1. **Cache table SRAM**: Add ew tag bits per cache slot (3 bits for ew in {8,16,32,64}).
     We need 3 bits for each vline in the cache slot.

2. **Memlet / DRAM interface**: Include ew metadata in cache line write/read transactions.
   DRAM stores ew as sideband data per vline.
     The ews should go in the address message.
     The ews should be sent back in a separate message when doing a read.
       probably a read_address_resp or something like that.

4. **Store path**: For non-aligned or strided or indexed we do a normal store and don't change
   the destination ew.
   For aligned unit-stride we set the destination ew to the instruction ew.

3. **Store path**: When kamlet receives a store instruction, compare the instruction ew
   against the cache slot's ew tag. A store instruction should say whether ew is expeted
   to match, be None, different, or unknown.  If the seen ew doesn't match expection then that
   is an error wire (unrecoverable error).
   If it's an 'unknown' then this is because we're doing a strided or indexed store and the
   lamlet couldn't check what the ew was. In this case if it doesn't match (or is None)
   we need to send a Fault back to the lamlet to handle. For now just raise an error wire
   and treat it as unrecoverable. We'll fix it properly later.

4. **Load path**: When kamlet loads from cache, I don't think anything changes here.  The kamlet
   reads from the TLB table like normal, gets the ew and loads the data. 

5. **Synchronization**: For indexed stores, kamlets independently detect ew mismatches and
   fault to the lamlet. The lamlet coordinates the remap across all kamlets.

6. **Lamlet ew table**: Small SRAM or register file storing per-vline ew. Consulted before
   dispatching non-indexed operations. Updated on stores.
