# RxCh1 Design

## Overview

Receive handler for channel 1 (requests that need responses). These messages receive data
and must send responses back.

RxCh1 also handles RX-initiated operations (ReadMemWord, WriteMemWord) using a local
**RxPendingTable** instead of the main WitemTable. This keeps the WitemTable focused on
protocol witems while RxCh1 owns the full lifecycle of RX-initiated operations.

## Messages Handled

| Message | SRAM | RF | State Update | Send Response |
|---------|------|----|--------------| --------------|
| LOAD_J2J_WORDS_REQ | - | Write | dst→COMPLETE | RESP |
| STORE_J2J_WORDS_REQ | Write | - | dst→COMPLETE | RESP |
| LOAD_WORD_REQ | - | Write | dst→COMPLETE | RESP |
| STORE_WORD_REQ | Write | - | dst→COMPLETE | RESP |
| READ_MEM_WORD_REQ | Read | - | RxPendingTable | RESP (with data) |
| WRITE_MEM_WORD_REQ | Write | - | RxPendingTable | RESP |

Plus DROP/RETRY responses when can't handle immediately (no witem, cache not ready, etc.)

## Interface

```
RxCh1:

  // From Router1
  ← packetIn          : Decoupled (packet words)

  // To/From SramArbiter
  → sramReq           : Decoupled (addr + isWrite + writeData)
  ← sramResp          : Decoupled (readData)

  // To RfSlice
  → rfWrite           : Valid + addr + writeData

  // To WitemTable (update protocol states for J2J, Word)
  → updateDstState    : Valid + instr_ident + tag + new_state

  // To/From Kamlet (cache slot allocation for RX-initiated ops)
  → cacheSlotReq      : Valid + k_maddr + is_write + instr_ident + tag + source_x + source_y
  ← cacheSlotResp     : Valid + success + slot + cache_is_avail
                        // success=false if: parent not found, no slot, slot conflict
                        // RxCh1 sends DROP if success=false

  // From Kamlet (cache slot became ready)
  ← cacheSlotReady    : Valid + slot

  // To Ch0Arbiter (send responses - always on channel 0)
  → packetOut         : Decoupled (packet)
```

## RxPendingTable

Small table for RX-initiated operations waiting for cache. Separate from main WitemTable.

```
RxPendingEntry:
  valid       : Bool
  ident       : UInt           // instr_ident from REQ
  tag         : UInt           // tag from REQ (needed for response)
  source_x    : UInt           // who to respond to
  source_y    : UInt
  cache_slot  : UInt           // allocated slot
  is_write    : Bool           // WriteMemWord vs ReadMemWord
  state       : RxPendingState // NEED_RETRY | WAITING_FOR_RESEND (WriteMemWord only)
```

**Lookup**: By `(ident, tag, source_x, source_y)` when receiving resent REQ.

**Size**: Small (e.g., 4 entries). These are flow-controlled by DROP if full.

### RxPendingTable Flow

### Kamlet cacheSlotReq Handling

When kamlet receives cacheSlotReq, it:
1. Check if source is lamlet → skip parent check
2. Otherwise compute `parent_ident = (ident - tag - 1) % max_response_tags`
3. Lookup parent witem → reject if not found
4. Get `writeset_ident` from parent (for conflict checking)
5. Try to allocate cache slot → reject if can't
6. Check slot conflicts with writeset_ident → reject if conflict
7. Return success + slot + cache_is_avail

### ReadMemWord Flow

**If cache ready (immediate)**:
1. RX receives REQ, requests slot via cacheSlotReq
2. Gets cacheSlotResp with success=true, cache_is_avail=true
3. Read SRAM, send RESP with data

**If cache not ready**:
1. RX receives REQ, requests slot via cacheSlotReq
2. Gets cacheSlotResp with success=true, cache_is_avail=false
3. Creates RxPendingEntry (is_write=false)
4. When cacheSlotReady arrives for this slot:
   - Read SRAM
   - Send RESP with data
   - Remove entry

**If rejected**:
1. RX receives REQ, requests slot via cacheSlotReq
2. Gets cacheSlotResp with success=false
3. Send DROP

### WriteMemWord Flow

**If cache ready (immediate)**:
1. RX receives REQ with data, requests slot via cacheSlotReq
2. Gets cacheSlotResp with success=true, cache_is_avail=true
3. Write to SRAM, send RESP

**If cache not ready**:
1. RX receives REQ with data, requests slot via cacheSlotReq
2. Gets cacheSlotResp with success=true, cache_is_avail=false
3. Creates RxPendingEntry (is_write=true, state=NEED_RETRY)
4. When cacheSlotReady arrives for this slot:
   - Send RETRY (no data stored - requester will resend)
   - state = WAITING_FOR_RESEND
5. RX receives resent REQ with data
   - Lookup entry by (ident, tag, source_x, source_y)
   - Write to SRAM
   - Send RESP
   - Remove entry

**If rejected**:
1. RX receives REQ, requests slot via cacheSlotReq
2. Gets cacheSlotResp with success=false
3. Send DROP

## Pipeline

Same 6-stage pipeline as RxCh0:

```
S1 (Decode) → S2 (Issue) → S3 (Lookup 1) → S4 (Lookup 2) → S5 (Compute) → S6 (Execute)
```

**Stage 1: Receive + Decode**
- Accept word from router
- Decode type, extract fields

**Stage 2: Issue Lookup**
- Issue kamlet request

**Stage 3: Lookup 1**
- Kamlet lookup in progress (cycle 1 of 2)

**Stage 4: Lookup 2**
- Kamlet lookup completes, response arrives

**Stage 5: Compute**
- Compute RF addr, mask, SRAM addr from kamlet response + tag
- Determine if can handle (witem exists, cache ready) or need DROP

**Stage 6: Execute**
- SRAM read/write, RF write, state update
- Build and send response packet (RESP or DROP)

## Examples

### LOAD_J2J_WORDS_REQ (header + data words → RF, send RESP)

```
Cycle 1: S1=hdr   S2=-     S3=-     S4=-     S5=-     S6=-
Cycle 2: S1=d0    S2=hdr   S3=-     S4=-     S5=-     S6=-     (issue req)
Cycle 3: S1=d1    S2=d0    S3=hdr   S4=-     S5=-     S6=-
Cycle 4: S1=next  S2=d1    S3=d0    S4=hdr   S5=-     S6=-     (kamlet resp)
Cycle 5: S1=...   S2=next  S3=d1    S4=d0    S5=hdr   S6=-     (compute, check witem)
Cycle 6: S1=...   S2=...   S3=next  S4=d1    S5=d0    S6=hdr   (send RESP or DROP)
Cycle 7: S1=...   S2=...   S3=...   S4=next  S5=d1    S6=d0    (RF write)
Cycle 8: S1=...   S2=...   S3=...   S4=...   S5=next  S6=d1    (RF write)
```

### READ_MEM_WORD_REQ (header + addr → read SRAM, send RESP with data)

```
Cycle 1: S1=hdr   S2=-     S3=-     S4=-     S5=-     S6=-
Cycle 2: S1=addr  S2=hdr   S3=-     S4=-     S5=-     S6=-     (issue req)
Cycle 3: S1=next  S2=addr  S3=hdr   S4=-     S5=-     S6=-
Cycle 4: S1=...   S2=next  S3=addr  S4=hdr   S5=-     S6=-     (kamlet resp)
Cycle 5: S1=...   S2=...   S3=next  S4=addr  S5=hdr   S6=-     (compute SRAM addr)
Cycle 6: S1=...   S2=...   S3=...   S4=next  S5=addr  S6=hdr   (check cache ready)
Cycle 7: S1=...   S2=...   S3=...   S4=...   S5=next  S6=addr  (SRAM read, send RESP)
```

If cache not ready at S6, send DROP or create WaitingReadMemWord witem.

### STORE_J2J_WORDS_REQ (header + data → SRAM write, send RESP)

```
Cycle 1: S1=hdr   S2=-     S3=-     S4=-     S5=-     S6=-
Cycle 2: S1=d0    S2=hdr   S3=-     S4=-     S5=-     S6=-
...
Cycle 6: S1=...   S2=...   S3=...   S4=...   S5=...   S6=hdr   (check witem/cache)
Cycle 7: S1=...   S2=...   S3=...   S4=...   S5=...   S6=d0    (SRAM write, send RESP)
```

If cache not ready, update dst_state to NEED_TO_ASK_FOR_RESEND (WitemMonitor will send RETRY later).
