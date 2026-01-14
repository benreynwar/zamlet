# Minimal Load/Store Implementation Plan

## Goal

Execute a unit-stride vector load/store end-to-end:
1. Lamlet receives vle/vse from Shuttle (or test harness)
2. Lamlet generates kinstr packet, sends to mesh
3. Kamlet receives packet, dispatches to jamlets
4. Jamlets execute memory↔RF transfer
5. Memory interface provides/receives data

## Current Status

**Phase 0: COMPLETE** - Kamlet mesh + sync
**Phase 1: COMPLETE** - IdentQuery handling

```bash
bazel test //python/zamlet/kamlet_test:test_kamlet_default --test_output=streamed
# PASSES - Both SyncTrigger and IdentQuery tests work
```

**LamletTop DSE**: 84,745 instances, 11,057 um^2, meets timing at 1GHz with 97ps slack

## Phase Overview

| Phase | Name | What it adds |
|-------|------|--------------|
| 0 | Kamlet Mesh + Sync | InstrQueue, InstrExecutor, Synchronizer, mesh routing |
| 1 | IdentQuery | Ident tracking, backpressure |
| 2 | Scalar Memory Load/Store | RfSlice, ScalarLoadQueue, VpuToScalarMem, LoadImm |
| 3 | VPU Memory Load/Store | Sram, CacheTable, LocalExec |
| 4 | Memory Interface | Memlet, cache line fill/writeback |
| 5 | Cache Fill Path | Miss handling, eviction |

---

## Phase 0: Kamlet Mesh + Sync (COMPLETE)

Minimal path to test instruction receive and sync network.

### 0.1 InstrQueue
Receives instruction packets forwarded from jamlets, strips header, queues kinstr.

### 0.2 InstrExecutor (Minimal)
Decode SyncTrigger instruction, trigger Synchronizer.

### 0.3 Jamlet Packet Forwarding
Forward instruction packets from mesh to kamlet.

### 0.4 Kamlet Top Module
Wire InstrQueue + InstrExecutor + Synchronizer.

### 0.5 Test
Inject SyncTrigger packet, verify sync output.

---

## Phase 1: IdentQuery Handling (COMPLETE)

### 1.1 IdentQuery in InstrExecutor
Decode IdentQuery, trigger Synchronizer with oldest active ident.

### 1.2 Ident Tracking in Kamlet
Track oldest active ident for IdentQuery response.

### 1.3 Test
Lamlet sends IdentQuery, verify sync result returns correct ident.

---

## Phase 2: Scalar Memory Load/Store (NEXT)

Load/store through scalar memory via TileLink. No SRAM cache needed - data goes directly
between scalar memory and RF.

### 2.1 RfSlice
Register file slice in each jamlet. Required for any load/store.

```
RfSlice
├── read: addr → data
├── write: addr + data + mask
Size: rfSliceWords * wordBytes = 48 * 8 = 384 bytes per jamlet
```

### 2.2 ScalarLoadQueue (in Lamlet)
Issues TileLink reads to scalar memory, generates LoadImm kinstrs with embedded data.

```
ScalarLoadQueue
├── IN:  req (from IssueUnit)
│        ├── paddr, size, vd, start_index, n_elements, ew, instr_ident
├── OUT: tl_a.*                        # TileLink read request
├── IN:  tl_d.*                        # TileLink read response
├── OUT: kinstr (LoadImm)              # To DispatchQueue
├── OUT: load_complete                 # To RegisterScoreboard
└── OUT: busy
```

Flow:
1. IssueUnit sends request for scalar memory load
2. ScalarLoadQueue issues TileLink Get
3. Response arrives with data
4. Generate LoadImm kinstrs with embedded data
5. Dispatch to mesh, signal load_complete

### 2.3 LoadImm Kinstr Handling (in Jamlet)
Jamlets decode LoadImm and write embedded data directly to RF.

For Phase 2 (ew=64 only), each LoadImm writes one complete 8-byte word:

```
LoadImm kinstr (2 words):
  Word 0: instruction
    ├── opcode      # KInstrOpcode.LoadImm
    ├── jInKIndex   # Which jamlet in this kamlet
    └── rfAddr      # Destination word in RfSlice
  Word 1: data      # 64-bit data to write
```

No SRAM access - data is embedded in the instruction packet.

### 2.4 VpuToScalarMem (in Lamlet)
Handles WriteMemWord messages from kamlets, converts to TileLink writes.

```
VpuToScalarMem
├── IN:  mesh_packet (WriteMemWord)    # From Ch1Receiver
├── OUT: tl_a.*                        # TileLink write request
├── IN:  tl_d.*                        # TileLink write ack
├── OUT: resp_packet                   # Response back to mesh
└── OUT: write_complete                # To RegisterScoreboard
```

Scalar store flow (word-by-word):
1. Store kinstr goes to kamlet
2. Kamlet dispatches to jamlets, jamlets read RF
3. Kamlet sends WriteMemWord to lamlet (one per 8-byte word)
4. VpuToScalarMem converts each to TileLink Put
5. Signal write_complete for each word

### 2.5 Store Kinstr Handling (in Kamlet/Jamlet)
For scalar memory stores:
- Kamlet dispatches Store to jamlets
- Jamlets read RF, send data back to kamlet
- Kamlet generates WriteMemWord messages to lamlet

### 2.6 RegisterScoreboard (in Lamlet)
Tracks register hazards for scalar memory operations.

```
RegisterScoreboard
├── IN:  load_start(vd)                # Block reads+writes to vd
├── IN:  store_start(vs, n_words)      # Block writes to vs
├── IN:  load_complete(vd)             # Unblock vd
├── IN:  store_word_complete(vs)       # Decrement vs counter
├── OUT: read_blocked[32]
└── OUT: write_blocked[32]
```

### 2.7 TileLink Test Interface
Cocotb acts as scalar memory, responds to TileLink requests.

### 2.8 Tests

**Test 2.1: LoadImm to RF**
- Inject LoadImm kinstr directly to kamlet
- Verify jamlet writes data to RF

**Test 2.2: Scalar Memory Load (ScalarLoadQueue)**
- Cocotb provides TileLink response
- Verify LoadImm generated and RF updated

**Test 2.3: Scalar Memory Store (VpuToScalarMem)**
- Pre-populate RF
- Send Store kinstr for scalar memory address
- Verify TileLink Put issued with correct data

**Test 2.4: End-to-End Scalar Load**
- Lamlet receives vle with scalar memory address
- Full path through ScalarLoadQueue → LoadImm → RF

**Test 2.5: End-to-End Scalar Store**
- Pre-populate RF
- Lamlet receives vse with scalar memory address
- Full path through Store → WriteMemWord → TileLink

---

## Phase 3: VPU Memory Load/Store

Load/store through VPU memory (SRAM cache).

### 3.1 Sram
Local cache memory in each jamlet.

```
Sram
├── read: addr → data (1 cycle latency)
├── write: addr + data + mask
Size: sramDepth * wordBytes = 256 * 8 = 2KB per jamlet
```

### 3.2 CacheTable (Simplified)
Track cache slot states. First draft: assume always-hit.

```
CacheTable
├── IN:  cacheQuery (address)
├── OUT: cacheAvail
└── OUT: cacheSlot
```

### 3.3 LocalExec
Executes LoadSimple/StoreSimple (SRAM↔RF transfer).

```
LocalExec
├── IN:  dispatch (from kamlet)
├── Sram read/write ports
├── RfSlice read/write ports
└── OUT: complete (to kamlet)
```

### 3.4 InstrExecutor (Expand)
Add CacheTable query, dispatch to jamlets.

### 3.5 Tests

**Test 3.1: LoadSimple**
- Pre-populate SRAM
- Dispatch LoadSimple, verify RF updated

**Test 3.2: StoreSimple**
- Pre-populate RF
- Dispatch StoreSimple, verify SRAM updated

**Test 3.3: End-to-End VPU Load**
- vle with VPU memory address (cache pre-populated)

**Test 3.4: End-to-End VPU Store**
- vse with VPU memory address

---

## Phase 4: Memory Interface

### 4.1 Memlet
Interface between jamlets and external VPU memory.

```
Memlet
├── External: readReq, readResp, writeReq, writeAck
└── Internal: packets to/from jamlet routers
```

---

## Phase 5: Cache Fill Path

Handle cache misses:
1. CacheTable detects miss
2. Send READ_LINE to memlet
3. Memlet fetches from external memory
4. Distribute to jamlets, write SRAM
5. Mark slot SHARED, proceed with dispatch

---

## Implementation Order (Phase 2)

1. **RfSlice** - Basic RF storage in jamlet
2. **LoadImm kinstr** - Add to KInstr, handle in jamlet
3. **ScalarLoadQueue** - TileLink read, LoadImm generation
4. **TileLink test interface** - Cocotb as scalar memory
5. **Test 2.1-2.2** - LoadImm and scalar load tests
6. **WriteMemWord handling** - Kamlet sends to lamlet
7. **VpuToScalarMem** - Convert to TileLink Put
8. **RegisterScoreboard** - Hazard tracking
9. **Test 2.3-2.5** - Scalar store and end-to-end tests

## File Structure (Phase 2 additions)

```
src/main/scala/zamlet/
  lamlet/
    ScalarLoadQueue.scala      # NEW
    VpuToScalarMem.scala       # NEW
    RegisterScoreboard.scala   # NEW

  jamlet/
    RfSlice.scala              # NEW

  kamlet/
    InstrExecutor.scala        # UPDATE: LoadImm, Store dispatch

python/zamlet/
  kamlet_test/
    test_scalar_mem.py         # NEW: Phase 2 tests
```

## Simplifications for Phase 2

| Full Design | Phase 2 |
|-------------|---------|
| Multiple in-flight loads | Single load at a time |
| Full RegisterScoreboard | Simple blocking |
| Gather for stores | Word-by-word via VpuToScalarMem |
| Both memory types | Scalar memory only |
| All element widths (8-64) | ew=64 only (1 element = 1 word) |

## Open Questions

1. **LoadImm encoding**: How many bytes can we embed? Probably 8 (one word).

2. **WriteMemWord flow**: Does kamlet aggregate jamlet data before sending, or does
   each jamlet send individually? (Kamlet aggregates makes more sense.)

3. **TileLink source IDs**: How to allocate between ScalarLoadQueue and VpuToScalarMem?
   (Arbiter handles this, different source ranges.)
