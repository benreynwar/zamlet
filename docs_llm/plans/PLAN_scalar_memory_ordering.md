# Plan: Scalar Memory Ordering

## Problem

Scalar memory reads and writes have no ordering guarantees. A `vstore` to scalar memory
dispatches `StoreScalar` kinstrs that travel through the instruction pipeline before
eventually calling `scalar.set_memory`. A subsequent `vload` or `get_memory` reads scalar
memory directly, potentially seeing stale data because the store hasn't arrived yet.

## Approach

Enforce ordering in `ScalarState.get_memory` and `ScalarState.set_memory` by making them
async and having them wait for conflicting operations to complete before proceeding.

Operations with the same `writeset_ident` are guaranteed to touch different bytes, so they
don't conflict and don't need to wait for each other.

## Two kinds of operations

**Known** — the lamlet knows at dispatch time that these touch scalar memory:
- Loads: `vloadstore_scalar` (load path), `vload_scalar_partial`
- Stores: `vloadstore_scalar` (store path via `StoreScalar`), `vstore_scalar_partial`

**Might-touch** — strided/indexed operations that could hit any page type. Tracked by
`sync_ident` from the synchronizer. Conservatively assumed to touch scalar memory.

## State (on ScalarState)

- `pending_known_reads: dict[int, int]` — writeset_ident → count
- `pending_known_writes: dict[int, int]` — writeset_ident → count
- `might_touch_reads: dict[int, int]` — sync_ident → writeset_ident
- `might_touch_writes: dict[int, int]` — sync_ident → writeset_ident
- Reference to `synchronizer` (to check `is_complete`)

## Might-touch cleanup

Completed might-touch entries are removed eagerly in `ScalarState.update()`, which runs
every cycle. Each cycle, check `synchronizer.is_complete(sync_ident)` for all entries in
`might_touch_reads` and `might_touch_writes`, and remove completed ones.

## Ordering rules

**Before a read** (in `get_memory`):
- Wait for known writes with different writeset_ident to reach 0
- Wait for might-touch writes with different writeset_ident to be sync-complete

**Before a write** (in `set_memory`):
- Wait for known reads with different writeset_ident to reach 0
- Wait for known writes with different writeset_ident to reach 0
- Wait for might-touch reads with different writeset_ident to be sync-complete
- Wait for might-touch writes with different writeset_ident to be sync-complete

## API

```python
# Increment pending counts (called at dispatch time)
scalar.register_known_read(writeset_ident)
scalar.register_known_write(writeset_ident)

# Register might-touch operations (called at dispatch time)
scalar.register_might_touch_read(sync_ident, writeset_ident)
scalar.register_might_touch_write(sync_ident, writeset_ident)

# Async read/write (waits for conflicts, decrements if known=True)
await scalar.get_memory(address, size, writeset_ident=None, known=False)
await scalar.set_memory(address, data, writeset_ident=None, known=False)
```

## Changes by file

### `oamlet/scalar.py`
- Add state fields listed above
- Add `__init__` parameter for synchronizer reference
- Add `register_known_read`, `register_known_write`
- Add `register_might_touch_read`, `register_might_touch_write`
- Make `get_memory` async, add wait logic + decrement when `known=True`
- Make `set_memory` async, add wait logic + decrement when `known=True`

### `message.py`
- Add `writeset_ident: int = 0` to `WriteMemWordHeader`
- Add `writeset_ident: int = 0` to `ReadMemWordHeader`
- Add comment on both about bit packing concerns (see docs/TODO.md)

### `kamlet/kamlet.py`
- `handle_store_scalar_instr`: set `header.writeset_ident` from `instr.writeset_ident`

### `lamlet/unordered.py`
- `vloadstore_scalar` load path: call `register_known_read` before `get_memory`
- `vloadstore_scalar` store path: call `register_known_write` at dispatch
- `vload_scalar_partial`: call `register_known_read` before `get_memory`
- `vstore_scalar_partial`: call `register_known_write` at dispatch
- `handle_read_mem_word_req`: `await` on `get_memory`
- `handle_write_mem_word_req`: pass `writeset_ident` and `known=True` to `set_memory`
- All `get_memory`/`set_memory` calls: add `await`, pass `writeset_ident` and `known`

### `lamlet/ordered.py`
- Scalar read (line 286): `await` on `get_memory`
- Scalar write (line 359): `await` on `set_memory`

### `oamlet/oamlet.py`
- `get_memory` for scalar path (line 1030): `await scalar.get_memory`
- `set_memory` (line 960): `await scalar.set_memory`
- Pass synchronizer to `ScalarState.__init__`

### `lamlet/unordered.py` (might-touch registration)
- `_vloadstore_indexed_unordered`: after dispatching, call
  `register_might_touch_read` or `register_might_touch_write` with
  `(completion_sync_ident, writeset_ident)`

## Steps

1. Add `writeset_ident` to `WriteMemWordHeader` and `ReadMemWordHeader`
2. Update `ScalarState` with new state, methods, async get/set_memory
3. Thread writeset_ident through `handle_store_scalar_instr` into the header
4. Update all `get_memory`/`set_memory` call sites to be async with correct params
5. Add `register_known_read`/`writes` calls at dispatch points
6. Add `register_might_touch_read`/`write` calls in indexed dispatch
7. Test with `test_unaligned.py`
8. Run kernel tests
