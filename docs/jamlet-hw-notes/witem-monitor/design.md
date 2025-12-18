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
