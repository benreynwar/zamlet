# WitemMonitor Design

## Overview

WitemMonitor is a combined module containing:
- **Entry Table**: Storage for protocol witem entries with src/dst state per tag
- **15-Stage Pipeline**: Selects entries, does kamlet lookup, TLB translation, tag iteration, fetches data, sends packets
- **Completion Detector**: Watches for all-COMPLETE entries, signals kamlet

**Note**: WitemMonitor only handles protocol witems (J2J, Word, Stride). Simple witems
(LoadSimple, StoreSimple, WriteImmBytes, ReadByte) go through LocalExec. RX-initiated
witems (ReadMemWord, WriteMemWord) go through RxCh1's RxPendingTable.

## Related Documents

- [LoadJ2JWords Trace](trace-load-j2j-words.md) - Detailed trace with packet building
- [StoreStride Trace](trace-store-stride.md) - Strided store trace

## Interface

```
WitemMonitor:

  // From Kamlet (witem lifecycle)
  <- witemCreate       : Valid + instr_ident + witem_type + cache_slot + cache_is_avail
  <- witemCacheAvail   : Valid + instr_ident   // cache became ready
  <- witemRemove       : Valid + instr_ident
  -> witemComplete     : Valid + instr_ident

  // Note: Entries created before cache ready (cache_is_avail=false) so the other side
  // can receive REQs immediately. witemCacheAvail unblocks processing when cache ready.
  // - Load: SRC needs cache (read SRAM), DST doesn't (write RF)
  // - Store: DST needs cache (write SRAM), SRC doesn't (read RF)
  // Creating early reduces DROPs/retries at cost of entries sitting idle.

  // From Kamlet (entry details for pipeline S2-S3)
  -> kamletEntryReq    : Valid + instr_ident
  <- kamletEntryResp   : Valid + witem_type + cache_slot + reg_addr + mem_addr +
                         mask_reg + mask_enabled + ...

  // From RxCh0 (protocol state updates from responses)
  <- updateSrcState    : Valid + instr_ident + tag + new_state

  // From RxCh1 (DST state updates)
  <- updateDstState    : Valid + instr_ident + tag + new_state

  // To/From SramArbiter
  -> sramReq           : Decoupled (addr + isWrite + writeData)
  <- sramResp          : Decoupled (readData)

  // To/From RfSlice
  -> rfReq             : Decoupled (addr + isWrite + writeData)
  <- rfResp            : Decoupled (readData)

  // To/From Kamlet (TLB translation for strided/indexed)
  -> tlbReq            : Valid + vaddr
  <- tlbResp           : Valid + paddr + error

  // To Ch1Arbiter (send packets)
  -> packetOut         : Decoupled (header + payload)
```

## Entry Table

Each jamlet has its own entry table with its own protocol states (word_bytes entries per entry).
This differs from the Python model where protocol states are combined at the kamlet level.

```
WitemEntry:
    valid           : Bool
    instr_ident     : UInt
    cache_is_avail  : Bool
    protocol_states : Vec(word_bytes, ProtocolStateEntry)

ProtocolStateEntry:
    src_state : SendState
    dst_state : ReceiveState

SendState:
    INITIAL              = 0
    NEED_TO_SEND         = 1
    WAITING_IN_CASE_FAULT = 2
    WAITING_FOR_RESPONSE = 3
    COMPLETE             = 4

ReceiveState:
    WAITING_FOR_REQUEST  = 0
    NEED_TO_ASK_FOR_RESEND = 1
    COMPLETE             = 2
```

For src-only witem types, `dst_state` is initialized to COMPLETE.

## Completion Detector

Monitors all entries for completion.

**Entry complete**: All tags have `src_state == COMPLETE AND dst_state == COMPLETE`

Some witem types only have src-side work (e.g., LoadStride). For these, `dst_state` is
initialized to COMPLETE at entry creation.

**Flow:**
1. Watch all entries
2. When entry has all tags complete, signal `witemComplete` to kamlet
3. Kamlet sends `witemRemove`
4. Delete entry from table

## State Transitions

**S11-S12 (src_state):**
- `INITIAL -> WAITING_FOR_RESPONSE` (when tag emitted from S12 to S13)
- `INITIAL -> COMPLETE` (batch-complete for tags that don't need messages)

**RxCh0 (via updateSrcState):**
- `WAITING_FOR_RESPONSE -> COMPLETE` (when response received)

**RxCh1 (via updateDstState):**
- `WAITING_FOR_REQUEST -> COMPLETE` (when DST-side work done)
- `WAITING_FOR_REQUEST -> NEED_TO_ASK_FOR_RESEND` (if needs retry)

## 15-Stage Pipeline

Each stage transition has configurable forward/backward buffering via parameters like
`s1_s2_forward_buf` and `s1_s2_backward_buf`.

| Stage | Description |
|-------|-------------|
| S1 | Select next ready entry |
| S2 | Request kamlet entry details |
| S3 | Kamlet response arrives |
| S4 | Element computation + RF read issue (mask/index) |
| S5 | RF read wait |
| S6 | RF response |
| S7 | Address computation + mask check |
| S8 | TLB issue |
| S9 | TLB wait |
| S10 | TLB response |
| S11 | Tag iteration - bounds |
| S12 | Tag iteration - emit |
| S13 | Data read issue + build header |
| S14 | Data read wait |
| S15 | Data response + send packet |

See [pipeline-comparison.md](pipeline-comparison.md) for detailed stage descriptions and
per-witem-type actions.

### Tag Iteration (S11-S12)

S11 computes tag bounds using `computeMemTagBounds()` (for send side) or `computeRegTagBounds()`
(for receive side). Each call returns:
- `tagActive`: whether this tag needs a message
- `nBytes`: how many bytes this mapping covers (used to skip to next tag)
- `startVline`, `endVline`: vline range for this tag

S12 iterates over vlines calling `computeMemTagTarget(tag, vline)` and emits to S13.

For multi-tag iterations, S11-S12 maintain iteration state and stall upstream while processing.

### Mask Read (issued in S4, response in S6)

**For SRC=register operations (stores, stride ops) with mask_enabled:**
- S4 issues RF read request for mask word(s) covering this entry's element
- S6 receives mask data, used in S7 for mask check

**For SRC=memory (unaligned loads) OR unmasked operations:**
- No RF read issued
- Pass through to S6

## Tag Mapping Functions

Tag iteration uses `computeMemTagBounds()` and `computeRegTagBounds()` (for send and receive
sides respectively). Vline iteration uses `computeMemTagTarget()` and `computeRegTagTarget()`.

See [LoadJ2JWords Trace](trace-load-j2j-words.md) for detailed function definitions and examples.

**Backpressure**: S15 uses valid/ready handshaking. If arbiter not ready, pipeline stalls backward.

## Mask Handling

Vector operations can be masked, where only elements with mask bit = 1 are processed.
The mask register is distributed across jamlets like any other vector register.

### Mask Organization

- Mask is indexed by **register element index** (same as destination for loads, source for stores)
- Each jamlet's RF slice contains mask bits for its local elements
- Mask bits are packed: each word holds `word_bytes * 8` mask bits

### Where Mask Checking Happens

The key distinction is whether SRC is on the memory side or register side:

**Unaligned loads (LoadJ2JWords, LoadWord) - SRC=memory:**
- SRC reads from cache, sends to DST which writes to RF
- Mask bits are in DST jamlet's RF (not SRC)
- SRC jamlet cannot check mask without extra communication
- **Design decision**: SRC sends data regardless of mask
- DST checks mask in RxCh1 before writing to RF
- If masked, DST still sends RESP (protocol completes, no RF write)

**Stores and Stride ops (StoreJ2JWords, StoreWord, LoadStride, StoreStride) - SRC=register:**
- SRC is on the register side (reads from or writes to local RF)
- Mask bits are in SRC jamlet's RF (local)
- SRC reads mask and skips sending for masked elements
- Masked tags are batch-completed in S11-S12 without sending

### Pipeline Mask Flow

**kamletEntryResp** must include:
- `mask_reg`: which register holds the mask (or indication of no mask)
- `mask_enabled`: whether this operation is masked

**S4 Element Comp**: Issue mask RF read (if SRC=register + masked)
**S5-S6**: RF read wait and response
**S7 Addr Comp**: Check mask bit and compute address

**SRC=memory (unaligned loads)**: No mask check in WitemMonitor - handled by RxCh1 at DST

### Mask Bit Extraction

For a tag covering element at `element_index`:
```
mask_word_index = element_index / (word_bytes * 8)
mask_bit_position = element_index % (word_bytes * 8)
mask_bit = (mask_word >> mask_bit_position) & 1
```

For multi-vline transfers, each vline may have different mask bits - check per vline.

## Work by Witem Type

| Type | SRAM | RF | Packet |
|------|------|----|--------|
| LoadJ2JWords (SRC) | Read | - | Yes (REQ to DST) |
| StoreJ2JWords (SRC) | - | Read | Yes (REQ to DST) |
| LoadWordSrc | Read | - | Yes (REQ to DST) |
| StoreWordSrc | - | Read | Yes (REQ to DST) |
| LoadStride | - | - | Yes (READ_MEM_WORD_REQ) |
| StoreStride | - | Read | Yes (WRITE_MEM_WORD_REQ) |

**Not handled by WitemMonitor:**
- Simple witems (LoadSimple, StoreSimple, WriteImmBytes, ReadByte) -> LocalExec
- ALU operations -> LocalExec
- ReadMemWord, WriteMemWord -> RxCh1's RxPendingTable
- DST-side protocol (LoadWordDst, StoreWordDst) -> RxCh1

## Synchronization

Some witem types (strided and indexed operations) require lamlet-wide synchronization for two
purposes:

1. **Fault sync**: Coordinate minimum faulting element across all kamlets for precise exceptions
2. **Completion sync**: Ensure all kamlets complete before signaling done to scalar core

### Which Witem Types Need Sync?

| Witem Type | Fault Sync | Completion Sync | Reason |
|------------|------------|-----------------|--------|
| LoadStride | Yes | Yes | May access non-idempotent memory |
| StoreStride | Yes | Yes | May access non-idempotent memory |
| LoadIdxUnord | Yes | Yes | May access non-idempotent memory |
| StoreIdxUnord | Yes | Yes | May access non-idempotent memory |
| LoadIdxElement | Yes | Yes | Must report element-ordered results |
| LoadJ2JWords | No | No | Only accesses VPU cache (idempotent) |
| StoreJ2JWords | No | No | Only accesses VPU cache (idempotent) |
| LoadWordSrc | No | No | Only accesses VPU cache |
| StoreWordSrc | No | No | Only accesses VPU cache |

### Architecture: Kamlet WitemTable + Per-Jamlet WitemMonitor

The architecture splits witem state between kamlet and jamlet levels:

```
Kamlet
├── Synchronizer (8 directions to neighbor kamlets)
├── KamletWitemTable
│   ├── Instruction parameters (from kinstr)
│   ├── Sync state (fault_sync, completion_sync)
│   ├── Aggregated jamlet status (j_in_k bits for fault_ready, complete_ready)
│   └── global_min_fault (after fault sync)
└── Jamlet[j_in_k]
    └── WitemMonitor
        ├── Per-jamlet protocol states (word_bytes tags per entry)
        ├── local_min_fault (this jamlet's minimum)
        └── 15-stage pipeline
```

**KamletWitemTable** holds:
- Instruction parameters (base addr, stride, element width, mask reg, etc.)
- Sync coordination state
- Responds to `kamletEntryReq` from jamlet WitemMonitors

**WitemMonitor** (per-jamlet) holds:
- Protocol states for this jamlet's tags (`word_bytes` entries)
- Local min fault element (for this jamlet)
- Runs the 15-stage pipeline

### KamletWitemTable Sync State

Each entry in the kamlet table has sync-related fields:

```
KamletWitemEntry (sync fields):
    needs_sync              : Bool      // true for strided/indexed types
    fault_sync_state        : SyncPhase // NOT_STARTED, WAITING, COMPLETE
    completion_sync_state   : SyncPhase
    jamlet_fault_ready      : Vec(j_in_k, Bool)   // which jamlets finished first pass
    jamlet_complete_ready   : Vec(j_in_k, Bool)   // which jamlets have all COMPLETE
    local_min_fault         : UInt      // min across all jamlets in this kamlet
    global_min_fault        : UInt      // from Synchronizer after fault sync
```

### Sync Interface

**WitemMonitor → KamletWitemTable:**

```
// Existing interface (from design.md)
-> kamletEntryReq    : Valid + instr_ident
<- kamletEntryResp   : Valid + witem_type + cache_slot + reg_addr + ...

// New sync signals
-> faultReady        : Valid + instr_ident + min_fault_element
-> completeReady     : Valid + instr_ident
```

**KamletWitemTable → WitemMonitor (broadcast):**

```
-> faultSyncComplete      : Valid + instr_ident + global_min_fault
-> completionSyncComplete : Valid + instr_ident
```

**KamletWitemTable → Synchronizer:**

```
-> syncLocalEvent    : Valid + sync_ident + value
<- syncComplete      : Valid + sync_ident + min_value
```

### Sync State Machine

**SyncPhase enum:**
```
NOT_STARTED = 0   // Haven't started this sync phase
WAITING     = 1   // Sent to Synchronizer, waiting for global result
COMPLETE    = 2   // Sync complete, result available
```

**Fault Sync (in KamletWitemTable):**

1. Each jamlet's WitemMonitor signals `faultReady(instr_ident, min_fault)` when all its tags
   leave INITIAL state
2. KamletWitemTable sets `jamlet_fault_ready[j_in_k_index] = true`, updates `local_min_fault`
3. When all `jamlet_fault_ready` bits set:
   - Send `syncLocalEvent(sync_ident=instr_ident, value=local_min_fault)` to Synchronizer
   - Set `fault_sync_state = WAITING`
4. When Synchronizer signals `syncComplete(sync_ident, min_value)`:
   - Store `global_min_fault = min_value`
   - Set `fault_sync_state = COMPLETE`
   - Broadcast `faultSyncComplete(instr_ident, global_min_fault)` to all WitemMonitors

**Completion Sync (in KamletWitemTable):**

1. Each jamlet's WitemMonitor signals `completeReady(instr_ident)` when all its tags are COMPLETE
2. KamletWitemTable sets `jamlet_complete_ready[j_in_k_index] = true`
3. When all `jamlet_complete_ready` bits set:
   - Send `syncLocalEvent(sync_ident=(instr_ident+1)%max_tags)` to Synchronizer (no value)
   - Set `completion_sync_state = WAITING`
4. When Synchronizer signals `syncComplete`:
   - Set `completion_sync_state = COMPLETE`
   - Broadcast `completionSyncComplete(instr_ident)` to all WitemMonitors

### WitemMonitor Sync Handling

Each WitemMonitor entry has local sync state:

```
WitemMonitorEntry (sync fields):
    ready_for_s1        : Bool      // eligible for S1 selection
    priority            : UInt      // for oldest-first selection (lower = older)
    local_min_fault     : UInt      // min fault element for this jamlet
    fault_signaled      : Bool      // already sent faultReady to kamlet
    complete_signaled   : Bool      // already sent completeReady to kamlet
```

**On receiving `faultSyncComplete`:**
1. Look up entry by `instr_ident`
2. For each tag in WAITING_IN_CASE_FAULT:
   - Compute element_index for this tag
   - If element_index >= global_min_fault → set COMPLETE
   - Else → set NEED_TO_SEND
3. If any tags now in NEED_TO_SEND: set `ready_for_s1 = true` (re-enable for second pass)

**On receiving `completionSyncComplete`:**
1. Look up entry by `instr_ident`
2. Signal `witemComplete` to kamlet (entry can be removed)

### Two-Phase Sync and Tag Processing

**Phase 1: First Pipeline Pass (S1-S12)**

For strided/indexed entries, the first pass through the pipeline:
1. S4-S10: Compute element, check mask, TLB lookup
2. S10: If TLB returns fault AND memory is non-idempotent → record min_fault, set tag WAITING_IN_CASE_FAULT
3. S10: If no fault OR idempotent memory → set tag NEED_TO_SEND
4. S11-S12: Tags in NEED_TO_SEND emit to S13; tags in WAITING_IN_CASE_FAULT skip
5. After S12 completes all tags: Check if all tags left INITIAL → trigger fault_sync_state = READY

**Phase 2: Fault Sync Complete**

When WitemCoordinator broadcasts `faultSyncComplete`:
1. Store `global_min_fault` in entry
2. For each tag in WAITING_IN_CASE_FAULT:
   - If element_index >= global_min_fault → set COMPLETE (don't write past fault)
   - Else → set NEED_TO_SEND (safe to proceed)
3. Entry becomes eligible for S1 selection again (for second pass)

**Phase 3: Second Pipeline Pass (S11-S12 only)**

For tags that transitioned WAITING_IN_CASE_FAULT → NEED_TO_SEND:
1. S1 selects entry again (has tags in NEED_TO_SEND)
2. S11-S12 emit those tags to S13
3. Tags complete normally via response handling

**Phase 4: Completion Sync**

When all tags reach COMPLETE:
1. Signal `completeReady` to coordinator
2. Wait for `completionSyncComplete`
3. Entry can now signal `witemComplete` to kamlet

### Sync Identifier Allocation

Each sync needs a unique identifier across the synchronizer network:
- Fault sync uses `instr_ident`
- Completion sync uses `(instr_ident + 1) % max_response_tags`

This works because:
- `instr_ident` is unique per active instruction
- Two consecutive idents are always available (sync completes before ident reuse)

### Implementation Notes

1. **KamletWitemTable sizing**: Same number of entries as per-jamlet WitemMonitor tables.
   Each entry tracks one instr_ident's sync state across all jamlets.

2. **Broadcast filtering**: The `faultSyncComplete` and `completionSyncComplete` signals are
   broadcast to all jamlets. Each WitemMonitor checks if `instr_ident` matches any of its entries.

3. **Entry selection**: S1 selects the entry with lowest `priority` among those where
   `valid && ready_for_s1`. The `ready_for_s1` bit is managed as follows:
   - Set on entry creation (if `cache_is_avail`)
   - Set on `witemCacheAvail`
   - Cleared after S12 completes iteration (waiting for responses or sync)
   - Set when `faultSyncComplete` received (re-enables for second pass)
   - Cleared after second pass S12 completes
   - Remains cleared while waiting for `completionSyncComplete`

   The `priority` field is set on entry creation and compacted on removal
   (see pipeline-comparison.md for details).

4. **Sync ident allocation**: Fault sync uses `instr_ident`, completion sync uses
   `(instr_ident + 1) % max_response_tags`. This ensures unique idents since instructions
   don't reuse idents until fully complete.

## Implementation Plan

### File Organization

```
src/main/scala/zamlet/jamlet/
|-- WitemMonitor.scala      # Top-level module, pipeline, IO
|-- WitemEntry.scala        # Entry table types and storage
+-- TagMappingCalc.scala    # computeMemTagBounds, computeMemTagTarget, etc.
```

### Bundles (WitemEntry.scala)

```scala
object SendState extends ChiselEnum {
  val Initial, NeedToSend, WaitingInCaseFault, WaitingForResponse, Complete = Value
}

object ReceiveState extends ChiselEnum {
  val WaitingForRequest, NeedToAskForResend, Complete = Value
}

class ProtocolStateEntry extends Bundle {
  val srcState = SendState()
  val dstState = ReceiveState()
}

class WitemEntry(params: JamletParams) extends Bundle {
  val valid = Bool()
  val instrIdent = params.ident()
  val cacheIsAvail = Bool()
  val protocolStates = Vec(params.wordBytes, new ProtocolStateEntry)
}
```

### WitemMonitor Submodules/Components

**1. Entry Table**
- `entries: Vec[WitemEntry]` - register array
- `allocate()` - find free slot, write new entry on witemCreate
- `lookup(instrIdent)` - find entry by ident (for updates)
- `selectReady()` - priority encoder for oldest ready entry (cache_is_avail && any INITIAL)
- `updateSrcState()` / `updateDstState()` - state machine updates
- `remove()` - clear valid on witemRemove

**2. TagMappingCalc (TagMappingCalc.scala)**
Combinational logic to compute tag bounds and targets. See trace document for detailed
function definitions.

**computeMemTagBounds(mem_tag, ...)** -> (tagActive, nBytes, startVline, endVline, mem_v_offset)
For send-side iteration. Returns whether tag is active across any vline, bytes to skip,
vline range, and memory vline offset for SRAM address calculation.

**computeMemTagTarget(mem_tag, vline, ...)** -> (active, targetVw)
For vline iteration. Returns whether this tag+vline is active and target jamlet.

**computeRegTagBounds(reg_tag, ...)** -> (tagActive, nBytes, startVline, endVline)
For receive-side iteration. Same pattern as computeMemTagBounds.

**computeRegTagTarget(reg_tag, vline, ...)** -> (active, sourceVw)
For vline iteration on receive side.

**Helper functions:**
- `jCoordsToVwIndex(x, y, wordOrder)` - jamlet coords to word index
- `vwIndexToJCoords(vwIndex, wordOrder)` - word index to jamlet coords

**3. Pipeline Registers**

Key data flowing through the pipeline (see pipeline-comparison.md for full details):

- S3→S4: kamletResp (witem_type, cache_slot, orderings, mask_reg, etc.)
- S4→S6: element_index, element_active, mask RF request issued
- S6→S7: mask_word, index_word (RF responses)
- S7→S8: g_addr, crosses_page, element_active (with mask check)
- S8→S10: TLB request issued, TLB response received
- S10→S11: page_paddr, page_is_vpu, page_target_coords, page_mem_ew
- S11→S12: (tag, tagActive, nBytes, startVline, endVline, v_offset)
- S12→S13: (src_tag, dst_tag, target_coords, n_bytes, paddr)
- S13→S15: header, data read issued, data response, send packet

**4. S11-S12 Tag Iterator State Machine**

```scala
class TagIterState extends Bundle {
  val active = Bool()
  val instrIdent = UInt(...)
  val currentTag = UInt(log2Ceil(wordBytes).W)
  val currentVline = UInt(...)
  val phase = TagIterPhase()  // SEND_TAGS, RECV_TAGS, DONE
}
```

S11-S12 logic:
1. S11: Start with currentTag=0, phase=SEND_TAGS
2. S11: Call computeMemTagBounds(currentTag)
3. S11: If tagActive: pass (tag, startVline, endVline, nVlines) to S12
4. S11: Batch-complete tags [currentTag+1, currentTag+nBytes-1]
5. S11: Advance currentTag += nBytes
6. S12: Iterate vlines from startVline to endVline, emit to S13
7. When currentTag >= wordBytes and phase=SEND_TAGS, switch to phase=RECV_TAGS, reset currentTag=0
8. Repeat with computeRegTagBounds for receive side
9. When done with both phases, signal ready for next entry

**5. Completion Detector**

Combinational logic:
```scala
val entryComplete = entries.map { e =>
  e.valid && e.protocolStates.map(ps =>
    ps.srcState === SendState.Complete && ps.dstState === ReceiveState.Complete
  ).reduce(_ && _)
}
val completeIndex = PriorityEncoder(entryComplete)
val anyComplete = entryComplete.reduce(_ || _)

io.witemComplete.valid := anyComplete
io.witemComplete.bits := entries(completeIndex).instrIdent
```

### Key Implementation Notes

1. **S11 iterates tags, S12 iterates vlines**: S11 processes one active tag per cycle (advancing
   by nBytes). For each active tag, S12 iterates over [startVline, endVline].

2. **Backpressure**: S15 ready signal propagates backward. If arbiter not ready, pipeline stalls.

3. **Entry table updates from multiple sources**:
   - S11 batch-completes src_state/dst_state for skipped tags
   - S12 sets src_state = WAITING_FOR_RESPONSE for active tags
   - RxCh0 updates src_state (WAITING_FOR_RESPONSE->COMPLETE)
   - RxCh1 updates dst_state
   - These should never conflict (different entries or different tags).

4. **Mask RF port**: S4 issues mask RF read, response arrives in S6. This is a separate read
   port from the data read in S13 (for stores reading source data).

5. **Configurable pipeline depth**: Each stage transition has `sX_sY_forward_buf` and
   `sX_sY_backward_buf` parameters. When both are false, stages are combinatorially connected.
