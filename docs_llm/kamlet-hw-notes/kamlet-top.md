# Kamlet Top-Level Module

## Overview

Kamlet is a cluster of jamlets (lanes) that share an instruction queue, cache tracking, and
register file coordination. A lamlet contains multiple kamlets arranged in a mesh.

## Block Diagram

```
                              ┌─────────────────────────────────────────────────┐
                              │                   Kamlet                         │
                              │                                                  │
   ══════════════════════════ │ ══════ Mesh Ports (via Jamlets) ════════════════ │
                              │                                                  │
   packetIn ════════════════► │  instruction packets from mesh                   │
   packetOut ◄════════════════│  packets to mesh                                 │
                              │                                                  │
   ══════════════════════════ │ ══════ Sync Network ════════════════════════════ │
                              │                                                  │
   syncIn[8] ════════════════►│  from 8 neighbors (N,S,E,W,NE,NW,SE,SW)         │
   syncOut[8] ◄═══════════════│  to 8 neighbors                                  │
                              │                                                  │
   ══════════════════════════ │ ══════ Jamlet Interfaces ═══════════════════════ │
                              │                                                  │
   (see Jamlet Interface section below)                                          │
                              │                                                  │
                              └─────────────────────────────────────────────────┘

Legend: ═══► Decoupled (ready/valid + data)
        ───► Valid only (no backpressure)
```

## External Interfaces

### MeshPort (via Jamlet Routers)
Packet communication with other kamlets and lamlet. Instruction packets arrive here.

### SyncPort
8-direction synchronization network (9-bit bus: [8]=last_byte, [7:0]=data).
Used for cross-kamlet coordination (MIN/OR aggregation).

## Submodules

### 1. InstrQueue

Receives instruction packets from mesh, strips header, queues kinstr.

```
Inputs:
  packetIn: Decoupled[Packet]        # from mesh (header + kinstr payload)

Outputs:
  deq: Decoupled[KInstr]             # to InstrExecutor (header stripped)

Parameters:
  depth: Int                          # queue depth
```

### 2. InstrExecutor

Pops kinstr from queue, checks RF availability and cache status, checks for memory conflicts,
dispatches witems/instructions to jamlets.

```
Inputs:
  kinstrIn: Decoupled[KInstr]         # from InstrQueue

  cacheAvail: Bool                    # from CacheTable - cache ready for this addr?
  cacheSlot: UInt                     # from CacheTable - which slot

  noMemConflict: Bool                 # from WitemController - no conflict with pending witems

  rfRelease: Valid[RfReleaseInfo]     # from WitemController - which regs to unlock
    - readRegs: Vec[RegIdx]
    - writeRegs: Vec[RegIdx]

Outputs:
  cacheQuery: Valid[KMAddr]           # to CacheTable - check this address

  memConflictQuery: Valid[KMAddr]     # to WitemController - check for conflicts

  dispatch: Valid[WitemDispatch]      # to all jamlets (broadcast)
    - instrType
    - instrIdent
    - cacheSlot
    - cacheIsAvail
    - (witem-specific fields)

  rfAcquire: Valid[RfAcquireInfo]     # internal RF tracking
    - readRegs: Vec[RegIdx]
    - writeRegs: Vec[RegIdx]

State:
  - RF lock table (which regs are in use for read/write)

Flow:
  1. Pop kinstr
  2. Check RF availability (internal state)
  3. Query CacheTable for cache status
  4. Query WitemController for memory conflicts
  5. When all clear: acquire RF locks, dispatch to jamlets
```

Dispatched instructions go to jamlets. Based on `instrType` and `cacheIsAvail`:
- **Immediate**: ALU ops, load/store with cache ready - execute directly
- **WitemTable**: Protocol ops, cache not ready - stored in jamlet's WitemTable

### 3. CacheTable

Manages cache slot states, address-to-slot mapping, cache line requests, and slot arbitration
for RX-initiated witems.

```
Inputs:
  cacheQuery: Valid[KMAddr]           # from InstrExecutor - check availability

  cacheSlotReq: Valid[CacheSlotReq]   # from jamlets (RX-initiated witems)
    - kMAddr
    - isWrite
    - instrIdent
    - sourceX, sourceY

  cacheResponse: Vec[j_in_k, Valid[Ident]]   # from each jamlet - response received

  cacheStateUpdate: Vec[j_in_k, Valid[Slot]] # from jamlets - slot modified

Outputs:
  cacheAvail: Bool                    # to InstrExecutor
  cacheSlot: UInt                     # to InstrExecutor

  cacheSlotResp: Valid[CacheSlotResp] # to jamlets
    - instrIdent
    - sourceX, sourceY
    - slot
    - cacheIsAvail

  sendCacheLine: Valid[SendCacheLineCmd]  # to jamlets (broadcast)
    - slot
    - ident
    - isWriteRead

  cacheReady: Valid[Ident]            # to WitemController - cache line now ready

State:
  - Slot states array (INVALID, SHARED, MODIFIED, READING, WRITING, etc.)
  - Address-to-slot mapping (tags)
  - Pending request tracking
```

### 4. WitemController

Tracks active witems, checks for memory conflicts, aggregates completion signals from jamlets,
signals RF release when witems complete.

```
Inputs:
  dispatch: Valid[WitemDispatch]      # from InstrExecutor - new witem created

  memConflictQuery: Valid[KMAddr]     # from InstrExecutor - check conflicts

  witemComplete: Vec[j_in_k, Valid[Ident]]  # from each jamlet - this jamlet finished

  cacheReady: Valid[Ident]            # from CacheTable - cache now available

Outputs:
  noMemConflict: Bool                 # to InstrExecutor

  rfRelease: Valid[RfReleaseInfo]     # to InstrExecutor - unlock regs
    - readRegs: Vec[RegIdx]
    - writeRegs: Vec[RegIdx]

  witemCacheAvail: Valid[Ident]       # to jamlets (broadcast) - cache ready for this witem

  witemRemove: Valid[Ident]           # to jamlets (broadcast) - delete witem entry

State:
  - Active witem table (ident -> address, regs, completion count)
  - Per-witem: which jamlets have completed

Flow:
  1. On dispatch: add entry to table (only for non-immediate witems)
  2. On witemComplete: increment completion count for that ident
  3. When all j_in_k complete: signal rfRelease, witemRemove
  4. On cacheReady: forward to jamlets via witemCacheAvail
```

Note: Immediate executions (ALU ops, cache-ready load/store) complete in the same cycle,
so they don't need conflict tracking.

### 5. Synchronizer

Cross-kamlet synchronization with MIN/OR aggregation.

```
Inputs:
  syncIn: Vec[8, Valid[SyncPacket]]   # from 8 neighbors
    - syncIdent
    - value (1-4 bytes)
    - lastByte

  localValue: Valid[SyncRequest]      # from WitemController - this kamlet's value
    - syncIdent
    - value
    - aggregationType (MIN / OR)

Outputs:
  syncOut: Vec[8, Valid[SyncPacket]]  # to 8 neighbors

  syncResult: Valid[SyncResult]       # to WitemController - aggregation complete
    - syncIdent
    - value

State:
  - Pending sync operations
  - Partial aggregation results
```

Used by:
- LoadStride/StoreStride: Wait for all tags to complete
- IdentQuery: Find minimum oldest active ident across kamlets

## Jamlet Interface

Each kamlet contains `j_in_k` jamlets. The interface to each jamlet (defined in jamlet_top.md):

**From Kamlet to Jamlet:**
- `dispatch` - instruction/witem dispatch (broadcast to all)
- `witemCacheAvail` - cache became ready (broadcast)
- `witemRemove` - delete witem entry (broadcast)
- `cacheSlotResp` - response to slot request
- `sendCacheLine` - command to send SRAM data (broadcast)

**From Jamlet to Kamlet:**
- `witemComplete` - all tags finished for this witem
- `cacheSlotReq` - RX-initiated witem needs a slot
- `cacheStateUpdate` - slot modified
- `cacheResponse` - cache line response received
