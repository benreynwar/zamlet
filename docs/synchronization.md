# Synchronization

## Overview

The VPU distributes work across a grid of kamlets. Many operations need all kamlets
to reach a common point before proceeding — for example, knowing that every kamlet
has finished writing its portion of a cache line, or finding the oldest active
instruction ident across the whole grid.

The synchronization network is a dedicated bus (separate from the main router
network) that connects each kamlet to its 8 neighbors. When a kamlet has locally
completed an event, it tells its neighbors, who propagate the information until
every kamlet knows the event is globally complete. The network also supports MIN
aggregation — each kamlet contributes a value and every kamlet learns the global
minimum.

Each concurrent sync operation is identified by a `sync_ident`. Multiple syncs can
be in flight simultaneously with different idents.

See `synchronization.py` for the protocol implementation.

## 1. Sync Ident Allocation Schemes

Three non-overlapping ident ranges, all defined in `oamlet/oamlet.py:158-168`:

| Range | System | Count |
|-------|--------|-------|
| `0 .. max_response_tags-1` | Regular instructions | 512 (default) |
| `max_response_tags .. max_response_tags+n_iq-1` | Ident queries | 8 (default) |
| `max_response_tags+n_iq .. max_response_tags+n_iq+n_ordered_buffers-1` | Ordered barriers | 2 (default) |

With defaults: regular = 0..511, ident query = 512..519, barriers = 520..521.

### 1.1 Ident Query

The lamlet needs to know how many instruction idents are safe to allocate without
colliding with idents still in use. It broadcasts an IdentQuery to all kamlets.
Each kamlet reports the distance to its oldest active ident, and the sync network
finds the global minimum.

Ident query slots use fixed idents starting at `max_response_tags` (512, 513, ...
519 with defaults). These are allocated once at init (`oamlet/oamlet.py:160-161`)
and reused as slots cycle.
### 1.2 Regular Instructions

Regular instructions that need sync use their own `instr_ident` (0..511) as the
sync ident — there is no separate sync ident pool. The sync ident namespace and
the instruction ident namespace are the same 512 values.

An instruction may need sync for two purposes, each requiring a distinct sync
ident:

**Fault sync** uses `instr_ident`. When a gather/scatter or indexed operation
encounters a fault (e.g. page fault), each kamlet reports the faulting element
index. The sync network finds the global minimum so all kamlets agree on which
element faulted first. Used by gather/scatter
(`transactions/load_gather_base.py:126`, `store_scatter_base.py:134`),
unordered indexed ops (`lamlet/unordered.py:667`), and vrgather
(`lamlet/vregister.py:59`).

**Completion sync** uses `(instr_ident + 1) % max_response_tags` — the next
ident in the circular space, since `instr_ident` is already taken by fault
sync. A kamlet that finishes early must not release shared resources (cache
lines, RF locks) while other kamlets are still using them. The completion sync
ensures all kamlets have finished before any kamlet's witem is finalized. Used
by gather/scatter (`transactions/load_gather_base.py:127`,
`store_scatter_base.py:135`) and unordered indexed ops
(`lamlet/unordered.py:669`).

Instructions that need both syncs allocate 2 consecutive idents via
`get_instr_ident(lamlet, 2)` (`lamlet/unordered.py:325`), reserving the +1
ident so it won't be assigned to another instruction.
### 1.3 Ordered Barriers

Ordered load/store operations process elements in a fixed order across kamlets.
The lamlet uses barrier instructions to synchronize between batches — each
kamlet must finish its current batch before the next one starts.

Barrier slots use fixed idents starting at `max_response_tags + n_iq` (520, 521
with defaults). Allocated once at init (`oamlet/oamlet.py:166-168`) and reused
as buffer slots cycle. They are in a dedicated range above the instruction
idents to avoid deadlock.

## 2. Sync Ident Lifecycle

### 2.1 Synchronizer state machine

Each synchronizer (one per kamlet plus one for the lamlet at position (0,-1))
maintains a `SyncState` per active sync_ident in its `_sync_states` dict
(`synchronization.py:110`).

State transitions:
1. **Created**: `start_sync()` (line 336) initializes a `SyncState` with
   `local_seen=False`, `completed=False`. Regions with no neighbors are
   pre-marked as synced.
2. **Local event**: `local_event()` (line 363) sets `local_seen=True` and
   `local_value`. A synchronizer will not send any packets until its local
   event has been reported.
3. **Propagation**: Sync packets are exchanged with neighbors. Each received
   packet marks regions (quadrants, columns, rows) as synced and updates min
   values.
4. **Completed**: `_update_completed()` (line 466) sets `completed=True` when
   `local_seen` is true, all regions are synced, and all sends are done.
5. **Cleared**: `clear_sync()` (line 445) deletes the state from
   `_sync_states`.
### 2.2 Ordering constraints

- `start_sync` is called automatically by `local_event` if the ident doesn't
  exist yet (line 368-369). It can also be triggered by receiving a sync
  packet for an unknown ident (`_process_received_packet`, line 548).
- `local_event` must be called before a synchronizer will propagate. Without
  it, the synchronizer knows about the sync but won't send packets.
- `clear_sync` should only be called after completion. Callers:
  `WaitingIdentQuery.finalize()` (`transactions/ident_query.py:129`) on each
  kamlet, and `receive_ident_query_response()` (`lamlet/ident_query.py:181`)
  on the lamlet.
### 2.3 Reuse conditions

A sync ident can be reused after `clear_sync` deletes its state.

`local_event` (line 366-367) also handles the case where a completed state
hasn't been cleared yet — it deletes the old state before starting fresh.
TODO: understand when this actually happens in practice.

## 3. Monitor Sync Span Tracking

The monitor (`monitor.py`) is a tracing system that records operations as
spans for debugging and performance analysis. It tracks sync operations with
its own parallel state, independent of the synchronizer state machine. A
global SYNC span is created as the parent, with a SYNC_LOCAL child span for
each kamlet's participation.

### 3.1 Lookup tables

The monitor tracks sync operations with two dicts (`monitor.py:190-192`):

**`_sync_by_key`**: `(sync_ident, name) → span_id`. Points to the global SYNC
span (the parent of all SYNC_LOCAL children). Added in
`record_sync_created()` (line 1072). Deleted in
`record_sync_local_complete()` (lines 1178-1180) when the last SYNC_LOCAL
child completes, causing the parent SYNC span to complete.

**`_sync_local_by_key`**: `(sync_ident, kx, ky, name) → span_id`. Points to
individual SYNC_LOCAL spans. `kx` and `ky` are kamlet indices (not routing
coords). Added in `record_sync_local_created()` (line 1091). Never deleted —
entries accumulate for the lifetime of the simulation. When the same key is
reused, the old entry is overwritten.

`name` is vestigial. It was originally used to distinguish fault sync and
completion sync when both used the same `sync_ident`. Now that they use
different idents (`instr_ident` vs `instr_ident + 1`), `name` is always
`None`. TODO: remove the `name` parameter.
### 3.2 Span creation paths

There are two ways sync spans are created:

**`create_sync_spans()`** (`monitor.py:1113`): Creates the global SYNC span
and all SYNC_LOCAL children at once — one per kamlet plus the lamlet
synchronizer at (0,-1). Used only by ident query (`lamlet/ident_query.py:123`).
Has an early-return: if `(sync_ident, name)` is already in `_sync_by_key`, it
does nothing (line 1122).

**`create_sync_local_span()`** (`monitor.py:1094`): Creates a single
SYNC_LOCAL span for one `(kx, ky)`, auto-creating the parent SYNC span if it
doesn't exist yet. Used by gather/scatter, unordered, ordered, and vregister.
Each kamlet creates its own span as it starts participating. Auto-finalizes
the parent when all expected children have been added (line 1108-1111).

TODO: consider unifying these two approaches. The reason for having both is
unclear and it adds complexity.
### 3.3 Span completion and cleanup

**`record_sync_local_event()`** (`monitor.py:1152`): Finds the oldest
incomplete SYNC_LOCAL for `(sync_ident, kx, ky)` via `_find_oldest_sync_local`
and adds a "local_event" event to it. Asserts if no incomplete span is found.

**`record_sync_local_complete()`** (`monitor.py:1163`): Finds the oldest
incomplete SYNC_LOCAL, sets its `min_value`, and completes it. If this causes
the parent SYNC span to complete (all children done), deletes the
`_sync_by_key` entry (lines 1178-1180).

**`_find_oldest_sync_local()`** (`monitor.py:1132`): Scans all entries in
`_sync_local_by_key` matching `(sync_ident, kx, ky, *)`. Returns the key
with the oldest `created_cycle` that has the requested completion status
(complete or incomplete).
### 3.4 Force-completion (IdentQuery)

When the lamlet receives an ident query response
(`lamlet/ident_query.py:242-247`), it force-completes all incomplete children
of the kinstr span (with `skip_children_check=True`), then completes the
kinstr itself. The SYNC span is a child of the kinstr, so it gets
force-completed even if its SYNC_LOCAL children are still incomplete.

Why can children be incomplete? The sync network guarantees every kamlet has
seen its local event, but not that every synchronizer has finished
propagation. Kamlet (0,0) can complete and send the response before a distant
kamlet has received all sync packets from its neighbors. So the lamlet may
force-complete the SYNC span while some SYNC_LOCAL spans haven't had
`record_sync_local_complete` called yet.

This force-completion does NOT clean up `_sync_by_key`. That cleanup only
happens in `record_sync_local_complete` (the normal completion path). So after
force-completion, `_sync_by_key` retains a stale entry pointing to the
now-completed SYNC span.

## 4. Debugging

### 4.1 Identifying the allocator from an ident value
### 4.2 "No incomplete sync local span" failures
