# WaitingItem Types Analysis

## Overview

WaitingItems track async operations that can't complete immediately. This document analyzes
each type to understand what state the jamlet hardware needs to store.

---

## Category 1: Simple (No Protocol States)

These complete atomically when cache is ready - no per-tag state machine.

### WaitingLoadSimple
- **Purpose:** Aligned load from cache to RF (fast path)
- **Cache:** Reads from SRAM
- **Protocol:** None - kamlet iterates all jamlets when ready
- **Jamlet state:** None (kamlet-driven)

### WaitingStoreSimple
- **Purpose:** Aligned store from RF to cache (fast path)
- **Cache:** Writes to SRAM
- **Protocol:** None - kamlet iterates all jamlets when ready
- **Jamlet state:** None (kamlet-driven)

### WaitingWriteImmBytes
- **Purpose:** Write immediate bytes to cache
- **Cache:** Writes to SRAM
- **Protocol:** None
- **Jamlet state:** None (kamlet-driven)

### WaitingReadByte
- **Purpose:** Read single byte from cache, send to scalar processor
- **Cache:** Reads from SRAM
- **Protocol:** None
- **Jamlet state:** None (kamlet-driven)

---

## Category 2: J2J Words (All-to-All, Per-Byte Tags)

Each jamlet is both SRC and DST for different byte tags within a word.

### WaitingLoadJ2JWords
- **Purpose:** Unaligned load requiring J2J transfer
- **Data flow:** Cache (SRC) → RF (DST)
- **Tags:** `n_tags = word_bytes * j_in_k` (e.g., 32 for word_bytes=8, j_in_k=4)
- **Per-jamlet tags:** `word_bytes` (indexed by `j_in_k_index * word_bytes + tag`)
- **Protocol per tag:**
  - `src_state`: NEED_TO_SEND → WAITING_FOR_RESPONSE → COMPLETE
  - `dst_state`: WAITING_FOR_REQUEST → COMPLETE
- **Cache:** SRC needs cache_is_avail (reading SRAM), DST doesn't use cache (writes RF)
- **Messages:** REQ, RESP, DROP

### WaitingStoreJ2JWords
- **Purpose:** Unaligned store requiring J2J transfer
- **Data flow:** RF (SRC) → Cache (DST)
- **Tags:** Same as LoadJ2JWords
- **Protocol per tag:**
  - `src_state`: NEED_TO_SEND → WAITING_FOR_RESPONSE → COMPLETE
  - `dst_state`: WAITING_FOR_REQUEST → NEED_TO_ASK_FOR_RESEND → COMPLETE
- **Cache:** DST needs cache_is_avail (writing SRAM), SRC doesn't use cache (reads RF)
- **Messages:** REQ, RESP, DROP, RETRY

---

## Category 3: Word (Point-to-Point, Two Witems)

Cross-kamlet partial word transfer. TWO separate witem types with different instr_idents!

### WaitingLoadWordSrc (instr_ident = N)
- **Purpose:** Source side of partial word load
- **Data flow:** Cache (this jamlet) → RF (other kamlet)
- **Tags:** `j_in_k` slots, but only ONE is active (point-to-point)
- **Protocol:** `SendState` only (NEED_TO_SEND → WAITING → COMPLETE)
- **Cache:** Needs cache_is_avail (reading SRAM)
- **Messages:** Sends REQ

### WaitingLoadWordDst (instr_ident = N+1)
- **Purpose:** Destination side of partial word load
- **Data flow:** Receives from other kamlet → writes to RF
- **Tags:** `j_in_k` slots, but only ONE is active
- **Protocol:** `ReceiveState` only (WAITING_FOR_REQUEST → COMPLETE)
- **Cache:** Does NOT use cache (writes to RF)
- **Messages:** Sends RESP, DROP, or RETRY

### WaitingStoreWordSrc (instr_ident = N)
- **Purpose:** Source side of partial word store
- **Data flow:** RF (this jamlet) → Cache (other kamlet)
- **Tags:** `j_in_k` slots, ONE active
- **Protocol:** `SendState` only
- **Cache:** Does NOT use cache (reads from RF)

### WaitingStoreWordDst (instr_ident = N+1)
- **Purpose:** Destination side of partial word store
- **Data flow:** Receives from other kamlet → writes to SRAM
- **Tags:** `j_in_k` slots, ONE active
- **Protocol:** `ReceiveState` only
- **Cache:** Needs cache_is_avail (writing SRAM)

---

## Category 4: ReadMemWord / WriteMemWord (Request-Response)

Created dynamically when a REQ arrives and cache isn't ready.

### WaitingReadMemWord
- **Purpose:** Handle READ_MEM_WORD_REQ when cache not ready
- **Created by:** RX handler when receiving REQ
- **Protocol:** Single state (waiting for cache)
- **Cache:** Needs cache_is_avail (reading SRAM)
- **On ready:** Sends RESP with data

### WaitingWriteMemWord
- **Purpose:** Handle WRITE_MEM_WORD_REQ when cache not ready
- **Created by:** RX handler when receiving REQ
- **Protocol:** `ReceiveState` (NEED_TO_ASK_FOR_RESEND → WAITING_FOR_REQUEST → COMPLETE)
- **Cache:** Needs cache_is_avail (writing SRAM)
- **On ready:** Sends RETRY, then waits for re-sent REQ

---

## Category 5: Gather/Scatter (All Jamlets, Sync Required)

Used for strided and indexed loads/stores. Each element can go to/from arbitrary memory.

### WaitingLoadStride / WaitingLoadIndexedUnordered
- **Base class:** WaitingLoadGatherBase
- **Purpose:** Load elements from scattered memory locations
- **Tags:** `n_tags = j_in_k * word_bytes`
- **Protocol:** `transaction_states[]` with states:
  - INITIAL, NEED_TO_SEND, WAITING_FOR_RESPONSE, COMPLETE, WAITING_IN_CASE_FAULT
- **Sync:** Two-phase (fault sync, then completion sync)
- **Cache:** None locally (sends READ_MEM_WORD_REQ to other jamlets/lamlet)
- **Flags:** `reads_all_memory = True`

### WaitingStoreStride / WaitingStoreIndexedUnordered
- **Base class:** WaitingStoreScatterBase
- **Purpose:** Store elements to scattered memory locations
- **Tags:** Same as load
- **Protocol:** Same as load
- **Sync:** Same as load
- **Cache:** None locally (sends WRITE_MEM_WORD_REQ to other jamlets/lamlet)
- **Flags:** `writes_all_memory = True`

---

## Category 6: Special

### WaitingIdentQuery
- **Purpose:** Query oldest active instr_ident across all kamlets
- **Protocol:** Sync-based (uses synchronization network)
- **Cache:** None
- **Kamlet (0,0):** Sends response to lamlet when sync completes

### WaitingLoadIndexedElement
- **Purpose:** Ordered indexed load - single element
- **Tags:** `word_bytes` (covers bytes within the element)
- **Protocol:** `transaction_states[]` (INITIAL → NEED_TO_SEND → WAITING → COMPLETE)
- **Cache:** None locally (sends READ_MEM_WORD_REQ)
- **On complete:** Sends LOAD_INDEXED_ELEMENT_RESP to lamlet

---

## Summary Table

| Type | Tags | Cache Needed | Who Creates | monitor_jamlet | monitor_kamlet |
|------|------|--------------|-------------|----------------|----------------|
| LoadSimple | N/A | Read | Kamlet | No | No |
| StoreSimple | N/A | Write | Kamlet | No | No |
| WriteImmBytes | N/A | Write | Kamlet | No | No |
| ReadByte | N/A | Read | Kamlet | No | No |
| LoadJ2JWords | word_bytes*j_in_k | SRC: Read | Kamlet | Yes | No |
| StoreJ2JWords | word_bytes*j_in_k | DST: Write | Kamlet | Yes | No |
| LoadWordSrc | j_in_k (1 active) | Read | Kamlet | Yes | No |
| LoadWordDst | j_in_k (1 active) | No | Kamlet | Yes | No |
| StoreWordSrc | j_in_k (1 active) | No | Kamlet | Yes | No |
| StoreWordDst | j_in_k (1 active) | Write | Kamlet | Yes | No |
| ReadMemWord | 1 | Read | RX handler | No | No |
| WriteMemWord | 1 | Write | RX handler | No | Yes |
| LoadStride | j_in_k*word_bytes | No (sends REQ) | Kamlet | Yes | Yes |
| StoreStride | j_in_k*word_bytes | No (sends REQ) | Kamlet | Yes | Yes |
| IdentQuery | N/A | No | Kamlet | No | Yes |
| LoadIndexedElement | word_bytes | No (sends REQ) | Kamlet | Yes | No |

---

## Hardware Design Implications

### What is stored per-witem vs per-tag?

**Per-witem (stored once):**
- instr_ident
- witem_type
- cache_slot (if type uses cache)
- cache_is_avail (if type uses cache)

**Per-tag (array):**
- src_state (for J2J, Word, Gather/Scatter types)
- dst_state (for J2J, Word types)
- transaction_state (for Gather/Scatter types)

### cache_slot and cache_is_avail

These are **per-witem, not per-tag**. A witem operates on at most one cache line.

But the relationship differs by type:
- LoadJ2JWords: SRC jamlets use cache_slot, DST jamlets ignore it
- StoreJ2JWords: DST jamlets use cache_slot, SRC jamlets ignore it
- LoadWordSrc: Uses cache_slot
- LoadWordDst: Doesn't have cache_slot (different instr_ident)

### Dynamically Created Witems

ReadMemWord and WriteMemWord are created by RX handlers when a REQ arrives.
These are NOT created by kamlet instruction processing - they're created reactively.
This means the jamlet hardware must be able to create witem entries autonomously.

### Synchronization Network

Gather/Scatter operations use a separate sync network (not the router mesh).
This is outside the jamlet - it's a kamlet-level feature.
