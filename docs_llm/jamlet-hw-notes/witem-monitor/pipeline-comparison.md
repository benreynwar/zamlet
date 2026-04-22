# WitemMonitor Pipeline Comparison

Side-by-side comparison of pipeline stages for different witem types.

## Pipeline Buffering Parameters

Each stage transition has two independent buffer parameters:
- `sX_sY_forward_buf`: Register for data/valid flowing from stage X to stage Y
- `sX_sY_backward_buf`: Register for ready signal flowing from stage Y to stage X

This allows fine-grained control over pipeline depth vs timing. All 14 transitions (S1→S2
through S14→S15) are independently configurable.

## Table 1: J2J and Word Operations (No TLB)

```
Stage   LoadJ2JWords    StoreJ2JWords   LoadWordSrc     StoreWordSrc
-----   ------------    -------------   -----------     ------------
S1      Select entry    Select entry    Select entry    Select entry
S2      Send kamletReq  Send kamletReq  Send kamletReq  Send kamletReq
S3      Recv kamletResp Recv kamletResp Recv kamletResp Recv kamletResp
S4      Pass through    Pass through    Check if active Check if active
S5      Pass through    Pass through    Pass through    Pass through
S6      Pass through    Pass through    Pass through    Pass through
S7      Pass through    Pass through    Pass through    Pass through
S8      Pass through    Pass through    Pass through    Pass through
S9      Pass through    Pass through    Pass through    Pass through
S10     Pass through    Pass through    Pass through    Pass through
S11     Tag iteration   Tag iteration   Pass through    Pass through
        (bounds)        (bounds)
S12     Tag iteration   Tag iteration   Pass through    Pass through
        (emit)          (emit)
S13     Issue SRAM read Issue RF read   Issue SRAM read Issue RF read
        + build header  + build header  + build header  + build header
S14     SRAM wait       RF wait         SRAM wait       RF wait
S15     SRAM response   RF response     SRAM response   RF response
        + send packet   + send packet   + send packet   + send packet
```

Notes:
- LoadWordSrc/StoreWordSrc: Only ONE jamlet participates (SRC jamlet specified in instr).
- J2J: All jamlets participate, each iterates over word_bytes tags in S11-S12.

## Table 2: Strided/Indexed Operations (Uses TLB)

```
Stage   StoreStride     LoadStride      StoreIdxUnord   LoadIdxUnord    LoadIdxElement
-----   -----------     ----------      -------------   ------------    --------------
S1      Select entry    Select entry    Select entry    Select entry    Select entry
S2      Send kamletReq  Send kamletReq  Send kamletReq  Send kamletReq  Send kamletReq
S3      Recv kamletResp Recv kamletResp Recv kamletResp Recv kamletResp Recv kamletResp
S4      Element comp    Element comp    Element comp    Element comp    Element comp
        + mask RF read  + mask RF read  + index RF read + index RF read + index RF read
                                        + mask RF read  + mask RF read  + mask RF read
S5      RF read wait    RF read wait    RF read wait    RF read wait    RF read wait
S6      Mask RF resp    Mask RF resp    Mask+Idx resp   Mask+Idx resp   Mask+Idx resp
S7      Mask check      Mask check      Mask check      Mask check      Mask check
        + compute addr  + compute addr  + compute addr  + compute addr  + compute addr
S8      Issue TLB       Issue TLB       Issue TLB       Issue TLB       Issue TLB
S9      TLB wait        TLB wait        TLB wait        TLB wait        TLB wait
S10     TLB resp        TLB resp        TLB resp        TLB resp        TLB resp
S11     Tag iteration   Tag iteration   Tag iteration   Tag iteration   Tag iteration
        (bounds)        (bounds)        (bounds)        (bounds)        (bounds)
S12     Tag iteration   Tag iteration   Tag iteration   Tag iteration   Tag iteration
        (emit)          (emit)          (emit)          (emit)          (emit)
S13     Issue data RF   Build header    Issue data RF   Build header    Build header
        + build header                  + build header
S14     Data RF wait    Pass through    Data RF wait    Pass through    Pass through
S15     Data RF resp    Send packet     Data RF resp    Send packet     Send packet
        + send packet                   + send packet
```

Notes:
- All strided/indexed ops: ONE element per jamlet (n_elements limited to j_in_l).
- LoadIdxElement: For ordered loads. After S15, sends LOAD_INDEXED_ELEMENT_RESP to lamlet.
- Stores (StoreStride, StoreIdxUnord): Need data RF read in S13, response in S15.
- Loads (LoadStride, LoadIdxUnord, LoadIdxElement): Send READ_MEM_WORD_REQ, no data to send.
- Page crossing: If element crosses page boundary, S8 issues second TLB request on next cycle.

## Trace Documents

- [LoadJ2JWords Trace](trace-load-j2j-words.md)
- [StoreStride Trace](trace-store-stride.md)
- [StoreWordSrc Trace](trace-store-word-src.md)
- [LoadIndexedUnordered Trace](trace-load-indexed-unordered.md)

---

# Pipeline Stage Details

## Entry Creation

**Module I/O:**
- Receives: `witemCreate.valid`, `witemCreate.instr_ident`, `witemCreate.witem_type`,
  `witemCreate.cache_slot`, `witemCreate.cache_is_avail`

**Entry table access:**
- Allocate: find free entry slot
- Writes: `valid = true`, `instr_ident`, `witem_type`, `cache_slot`, `cache_is_avail`,
  `ready_for_s1 = cache_is_avail`, `priority = next_priority++`
- Writes: all tag states = INITIAL
- Writes: `fault_signaled = false`, `complete_signaled = false`, `local_min_fault = MAX`

**Notes:**
- Entry created before cache ready (`cache_is_avail=false`) so DST can receive REQs immediately
- `witemCacheAvail` later sets `cache_is_avail = true` and `ready_for_s1 = true`
- `priority` is a monotonically increasing counter used for oldest-first selection

## Entry Removal

**Module I/O:**
- Receives: `witemRemove.valid`, `witemRemove.instr_ident`

**Entry table access:**
- Writes: `valid = false` for matching entry
- Writes: decrement `priority` for all entries with `priority > removed_entry.priority`
- Writes: decrement `next_priority`

**Notes:**
- Sent by Kamlet after receiving `witemComplete`
- Frees the entry slot for reuse
- Priority compaction keeps values bounded and avoids overflow

## S1: Entry Selection

Selects a witem entry from the entry table that needs processing.

**Selection:** Pick the entry with lowest `priority` among those where `valid && ready_for_s1`.

**Module I/O:** None

**Entry table access:**
- Reads: `valid`, `ready_for_s1`, `priority`, `instr_ident`, `witem_type` for all entries

**`ready_for_s1` management** (updated by other stages/events):
- Set: on entry creation (if `cache_is_avail`)
- Set: on `witemCacheAvail`
- Cleared: when S12 finishes iteration for this entry
- Set: when `faultSyncComplete` received and entry has tags needing second pass
- Cleared: when second pass S12 finishes

**Selection:** Oldest-first among eligible entries (lowest `priority` value wins).

### S1 → S2 Pipeline Register

```
s1_s2_reg:
    valid           : Bool      // entry was selected
    entry_index     : UInt      // index in entry table
    instr_ident     : UInt      // instruction identifier
    witem_type      : WitemType // which type of witem
```

## S2: Kamlet Request

Sends a request to the kamlet to fetch instruction parameters for this entry.

**Module I/O:**
- Sends: `kamletEntryReq.valid`, `kamletEntryReq.instr_ident`

**Entry table access:** None

**All witem types:** Send `kamletEntryReq` with `instr_ident`.

```
kamletEntryReq.valid = s1_s2_reg.valid
kamletEntryReq.bits.instr_ident = s1_s2_reg.instr_ident
```

### S2 → S3 Pipeline Register

```
s2_s3_reg:
    valid           : Bool
    entry_index     : UInt
    instr_ident     : UInt
    witem_type      : WitemType
```

## S3: Kamlet Response

Receives KamletWaitingItem from kamlet. Later stages decode fields as needed.

**Module I/O:**
- Receives: `kamletEntryResp.valid`, `kamletEntryResp.kwitem`

**Entry table access:** None

**All witem types:** Receive `kamletEntryResp` containing the KamletWaitingItem.

```
KamletWaitingItem:
    kinstruction    : UInt(64)  // instruction word, decoded by later stages
    cache_slot      : UInt      // which cache slot (for J2J ops)
    rf_word_order   : WordOrder // RF-side word order (for element computation)
```

### S3 → S4 Pipeline Register

```
s3_s4_reg:
    valid           : Bool
    entry_index     : UInt
    instr_ident     : UInt
    witem_type      : WitemType
    kwitem          : KamletWaitingItem
```

## S4: Element Computation + RF Read Issue

| Witem Type | S4 Action |
|------------|-----------|
| LoadJ2JWords | Pass through |
| StoreJ2JWords | Pass through |
| LoadWordSrc | Check if this jamlet is active (compare j_in_k_index) |
| StoreWordSrc | Check if this jamlet is active (compare j_in_k_index) |
| StoreStride | Compute element index, issue mask RF read |
| LoadStride | Compute element index, issue mask RF read |
| StoreIdxUnord | Compute element index, issue index RF read + mask RF read |
| LoadIdxUnord | Compute element index, issue index RF read + mask RF read |
| LoadIdxElement | Compute element index, issue index RF read + mask RF read |

**Module I/O:**
- Sends (strided/indexed): `rfReq[0]` for mask read, `rfReq[1]` for index read (indexed only)

**Entry table access:** None

**J2J pass-through:** J2J ops don't need element computation here because they iterate over all
`word_bytes` tags in S11-S12. All jamlets participate and determine their own mappings during
tag iteration.

**Element computation (strided/indexed):**
```
// this_vw derived from jamlet coordinates and rf_word_order from KamletWaitingItem
this_vw = coords_to_vw(this_j_x, this_j_y, kwitem.rf_word_order)

// Which element does this jamlet hold? (n_elements <= j_in_l, so one element per jamlet)
ve = this_vw                                        // vword index within vline
elements_per_vline = vline_bits / element_width     // element_width from kinstruction
v = start_index / elements_per_vline                // which vline
if ve < (start_index % elements_per_vline):
    v = v + 1
element_index = v * elements_per_vline + ve
element_active = (element_index >= start_index) && (element_index < start_index + n_elements)
```

**RF reads issued:**

Mask RF read (if mask_reg valid, for all strided/indexed ops):
```
// Mask is 1 bit per element, packed into words
mask_elements_per_word = word_bits                  // 64 bits per word
mask_v = element_index / mask_elements_per_word
mask_rf_addr = mask_reg + mask_v
// Issue read: rfReq[0].addr = mask_rf_addr
```

Index RF read (for indexed ops only):
```
// Index register holds byte offsets, one per element
index_elements_per_vline = vline_bits / index_ew    // index_ew from kinstruction
index_v = element_index / index_elements_per_vline
index_rf_addr = index_reg + index_v
// Issue read: rfReq[1].addr = index_rf_addr
```

### S4 → S5 Pipeline Register

```
s4_s5_reg:
    valid           : Bool
    entry_index     : UInt
    instr_ident     : UInt
    witem_type      : WitemType
    kwitem          : KamletWaitingItem
    element_index   : UInt      // which element this jamlet processes (strided/indexed)
    element_active  : Bool      // false if out of range or inactive jamlet
    rf_v            : UInt      // vline offset for data RF read (src for stores, dst for loads)
    mask_bit_pos    : UInt      // bit position within mask word (element_index % 64)
    index_byte_pos  : UInt      // byte position within index word (for indexed ops)
```

## S5: RF Read Wait

Wait cycle for RF read latency. Pass-through stage when `s4_s5_forward_buf` is disabled.

**Module I/O:** None

**Entry table access:** None

### S5 → S6 Pipeline Register

```
s5_s6_reg:
    // Same fields as s4_s5_reg
```

## S6: RF Response

| Witem Type | S6 Action |
|------------|-----------|
| LoadJ2JWords | Pass through |
| StoreJ2JWords | Pass through |
| LoadWordSrc | Pass through |
| StoreWordSrc | Pass through |
| StoreStride | Receive mask RF response |
| LoadStride | Receive mask RF response |
| StoreIdxUnord | Receive mask + index RF response |
| LoadIdxUnord | Receive mask + index RF response |
| LoadIdxElement | Receive mask + index RF response |

**Module I/O:**
- Receives (strided/indexed): `rfResp[0]` (mask word), `rfResp[1]` (index word, indexed only)

**Entry table access:** None

Register the RF read data for use in S7.

### S6 → S7 Pipeline Register

```
s6_s7_reg:
    valid           : Bool
    entry_index     : UInt
    instr_ident     : UInt
    witem_type      : WitemType
    kwitem          : KamletWaitingItem
    element_index   : UInt
    element_active  : Bool
    rf_v            : UInt
    mask_bit_pos    : UInt
    index_byte_pos  : UInt
    mask_word       : UInt(64)  // RF response (strided/indexed)
    index_word      : UInt(64)  // RF response (indexed only)
```

## S7: Address Computation + Mask Check

| Witem Type | S7 Action |
|------------|-----------|
| LoadJ2JWords | Pass through |
| StoreJ2JWords | Pass through |
| LoadWordSrc | Pass through |
| StoreWordSrc | Pass through |
| StoreStride | Check mask, compute g_addr |
| LoadStride | Check mask, compute g_addr |
| StoreIdxUnord | Check mask, compute g_addr |
| LoadIdxUnord | Check mask, compute g_addr |
| LoadIdxElement | Check mask, compute g_addr |

**Module I/O:** None

**Entry table access:** None

**Mask check (strided/indexed):**
```
mask_bit = (mask_word >> mask_bit_pos) & 1
masked_out = mask_enabled && (mask_bit == 0)
element_active = element_active && !masked_out
```

**Address computation (strided):**
```
g_addr = base_addr + element_index * stride_bytes
```

**Address computation (indexed):**
```
index_value = extract_bytes(index_word, index_byte_pos, index_ew / 8)
g_addr = base_addr + index_value
```

**Page crossing check:**
```
element_bytes = element_width / 8
element_end_addr = g_addr + element_bytes - 1
crosses_page = (g_addr / page_bytes) != (element_end_addr / page_bytes)
page_boundary = (g_addr / page_bytes + 1) * page_bytes
```

### S7 → S8 Pipeline Register

```
s7_s8_reg:
    valid           : Bool
    entry_index     : UInt
    instr_ident     : UInt
    witem_type      : WitemType
    kwitem          : KamletWaitingItem
    element_index   : UInt
    element_active  : Bool      // updated with mask check
    rf_v            : UInt
    g_addr          : UInt      // computed global address
    crosses_page    : Bool
    page_boundary   : UInt      // address of page boundary (if crosses_page)
```

## S8: TLB Issue

| Witem Type | S8 Action |
|------------|-----------|
| LoadJ2JWords | Pass through |
| StoreJ2JWords | Pass through |
| LoadWordSrc | Pass through |
| StoreWordSrc | Pass through |
| StoreStride | Issue TLB request |
| LoadStride | Issue TLB request |
| StoreIdxUnord | Issue TLB request |
| LoadIdxUnord | Issue TLB request |
| LoadIdxElement | Issue TLB request |

**Module I/O:**
- Sends (strided/indexed): `tlbReq.valid`, `tlbReq.vaddr`, `tlbReq.isWrite`

**Entry table access:** None

**TLB issue (strided/indexed):**
```
tlbReq.valid = element_active
tlbReq.vaddr = g_addr
tlbReq.isWrite = is_store_op
```

**Page crossing:** If `crosses_page`, S8 issues another TLB request for `page_boundary` on the
next cycle (stalls S7 and below).

### S8 → S9 Pipeline Register

```
s8_s9_reg:
    valid           : Bool
    entry_index     : UInt
    instr_ident     : UInt
    witem_type      : WitemType
    kwitem          : KamletWaitingItem
    element_index   : UInt
    element_active  : Bool
    rf_v            : UInt
    g_addr          : UInt
    crosses_page    : Bool
    page_boundary   : UInt
```

## S9: TLB Wait

Wait cycle for TLB lookup latency. Pass-through stage when `s8_s9_forward_buf` is disabled.

**Module I/O:** None

**Entry table access:** None

### S9 → S10 Pipeline Register

```
s9_s10_reg:
    // Same fields as s8_s9_reg
```

## S10: TLB Response

| Witem Type | S10 Action |
|------------|-----------|
| LoadJ2JWords | Pass through |
| StoreJ2JWords | Pass through |
| LoadWordSrc | Pass through |
| StoreWordSrc | Pass through |
| StoreStride | Register TLB response |
| LoadStride | Register TLB response |
| StoreIdxUnord | Register TLB response |
| LoadIdxUnord | Register TLB response |
| LoadIdxElement | Register TLB response |

**Module I/O:**
- Receives (strided/indexed): `tlbResp.valid`, `tlbResp.paddr`, `tlbResp.is_vpu`,
  `tlbResp.mem_ew`, `tlbResp.mem_word_order`, `tlbResp.fault`

For VPU memory, target jamlet is computed from `paddr` and `mem_word_order`.

**Entry table access:**
- Writes (strided/indexed, if fault): `local_min_fault` (update if element_index < current)

### S10 → S11 Pipeline Register

```
s10_s11_reg:
    valid           : Bool
    entry_index     : UInt
    instr_ident     : UInt
    witem_type      : WitemType
    kwitem          : KamletWaitingItem
    element_index   : UInt
    element_active  : Bool
    rf_v            : UInt
    g_addr          : UInt
    crosses_page    : Bool
    page_boundary   : UInt
    // TLB response:
    page_paddr      : UInt
    page_is_vpu     : Bool
    page_target_coords : (UInt, UInt)
    page_mem_ew     : UInt
    page_fault      : Bool
```

## S11: Tag Iteration - Bounds

| Witem Type | S11 Action |
|------------|-----------|
| LoadJ2JWords | Compute tag bounds (computeMemTagBounds) |
| StoreJ2JWords | Compute tag bounds (computeRegTagBounds) |
| LoadWordSrc | Pass through |
| StoreWordSrc | Pass through |
| StoreStride | Compute tag bounds (computeTagInfo) |
| LoadStride | Compute tag bounds (computeTagInfo) |
| StoreIdxUnord | Compute tag bounds (computeTagInfo) |
| LoadIdxUnord | Compute tag bounds (computeTagInfo) |
| LoadIdxElement | Compute tag bounds (computeTagInfo) |

**Module I/O:** None

**Entry table access:**
- Writes: tag states for inactive/skipped tags (INITIAL → COMPLETE for batch-complete)

This stage computes tag bounds and determines which tags are active. For multi-tag iterations,
it maintains iteration state and stalls upstream while processing.

**Outputs to S12:** (tagActive, nBytes, startVline, endVline, ...) for each tag being processed.

### S11 → S12 Pipeline Register

```
s11_s12_reg:
    valid           : Bool
    entry_index     : UInt
    instr_ident     : UInt
    witem_type      : WitemType
    kwitem          : KamletWaitingItem
    rf_v            : UInt
    // Tag bounds output:
    current_tag     : UInt          // byte position being processed
    tag_active      : Bool
    n_bytes         : UInt          // bytes covered by this tag
    start_vline     : UInt          // first vline for this tag (J2J)
    end_vline       : UInt          // last vline for this tag (J2J)
    v_offset        : UInt          // vline offset for SRAM (J2J)
    // Strided/indexed:
    g_addr          : UInt
    page_info       : PageInfo      // from TLB response
```

## S12: Tag Iteration - Emit

| Witem Type | S12 Action |
|------------|-----------|
| LoadJ2JWords | Compute target (computeMemTagTarget), emit to S13 |
| StoreJ2JWords | Compute target (computeRegTagTarget), emit to S13 |
| LoadWordSrc | Pass through |
| StoreWordSrc | Pass through |
| StoreStride | Emit tag info to S13 |
| LoadStride | Emit tag info to S13 |
| StoreIdxUnord | Emit tag info to S13 |
| LoadIdxUnord | Emit tag info to S13 |
| LoadIdxElement | Emit tag info to S13 |

**Module I/O:**
- Sends (strided/indexed, when iteration completes): `faultReady.valid`, `faultReady.instr_ident`,
  `faultReady.min_fault_element` to KamletWitemTable

**Entry table access:**
- Writes: tag states for emitted tags (INITIAL → NEED_TO_SEND or WAITING_IN_CASE_FAULT)
- Writes (when iteration completes): `ready_for_s1 = false`, `fault_signaled = true`

For J2J ops, this stage iterates over vlines within the tag range (startVline..endVline),
calling computeMemTagTarget/computeRegTagTarget for each. Emits one item per cycle to S13.

For strided/indexed, emits tag info directly to S13.

**Sync trigger:** When S12 finishes iterating all tags for an entry, it sends `faultReady` to
the KamletWitemTable (for sync witem types) and clears `ready_for_s1`.

### S12 → S13 Pipeline Register

```
s12_s13_reg:
    valid           : Bool
    entry_index     : UInt
    instr_ident     : UInt
    witem_type      : WitemType
    kwitem          : KamletWaitingItem
    rf_v            : UInt          // vline for data read
    // Per-tag info (emitted once per active tag):
    src_tag         : UInt          // byte position in local word
    dst_tag         : UInt          // byte position in target word
    n_bytes         : UInt          // bytes covered by this tag
    target_coords   : (UInt, UInt)  // target jamlet
    target_byte     : UInt          // byte offset in target word (strided/indexed)
    is_vpu          : Bool          // VPU memory vs scalar
    paddr           : UInt          // translated address (strided/indexed)
    v_offset        : UInt          // vline offset for SRAM (J2J)
```

## S13: Data Read Issue + Build Header

| Witem Type | S13 Action |
|------------|------------|
| LoadJ2JWords | Issue SRAM read, build header |
| StoreJ2JWords | Issue RF read, build header |
| LoadWordSrc | Issue SRAM read, build header |
| StoreWordSrc | Issue RF read, build header |
| StoreStride | Issue RF read, build header |
| LoadStride | Build header (no data to send) |
| StoreIdxUnord | Issue RF read, build header |
| LoadIdxUnord | Build header (no data to send) |
| LoadIdxElement | Build header (no data to send) |

**Module I/O:**
- Sends (loads from cache): `sramReq.valid`, `sramReq.addr`
- Sends (stores, data RF read): `rfReq.valid`, `rfReq.addr`

**Entry table access:** None

**SRAM read (LoadJ2JWords, LoadWordSrc):**
```
sram_addr = cache_slot * vlines_per_cache_line + (base_index + rf_v + v_offset)
sramReq.valid = true
sramReq.addr = sram_addr
sramReq.isWrite = false
```

**RF read (StoreJ2JWords, StoreWordSrc, StoreStride, StoreIdxUnord):**
```
rf_addr = src_reg + rf_v
rfReq.valid = true
rfReq.addr = rf_addr
rfReq.isWrite = false
```

**Build header:** Assemble message header with target coordinates, message type, ident, tag, etc.

### S13 → S14 Pipeline Register

```
s13_s14_reg:
    valid           : Bool
    entry_index     : UInt
    instr_ident     : UInt
    witem_type      : WitemType
    src_tag         : UInt
    dst_tag         : UInt
    n_bytes         : UInt
    target_coords   : (UInt, UInt)
    target_byte     : UInt
    is_vpu          : Bool
    paddr           : UInt
    header          : PacketHeader  // assembled header
```

## S14: Data Read Wait

Wait cycle for SRAM/RF read latency. Pass-through stage when `s13_s14_forward_buf` is disabled.

**Module I/O:** None

**Entry table access:** None

### S14 → S15 Pipeline Register

```
s14_s15_reg:
    // Same fields as s13_s14_reg
```

## S15: Data Response + Send Packet

| Witem Type | S15 Action |
|------------|------------|
| LoadJ2JWords | SRAM response, send packet |
| StoreJ2JWords | RF response, send packet |
| LoadWordSrc | SRAM response, send packet |
| StoreWordSrc | RF response, send packet |
| StoreStride | RF response, send packet |
| LoadStride | Send packet (no data) |
| StoreIdxUnord | RF response, send packet |
| LoadIdxUnord | Send packet (no data) |
| LoadIdxElement | Send packet (no data) |

**Module I/O:**
- Receives (loads from cache): `sramResp.valid`, `sramResp.data`
- Receives (stores): `rfResp.valid`, `rfResp.data`
- Sends: `packetOut.valid`, `packetOut.header`, `packetOut.data`

**Entry table access:**
- Writes (after packet sent): tag state (NEED_TO_SEND → WAITING_FOR_RESPONSE)

**Send packet:**

Packets are sent one word per cycle.

J2J packets (2 cycles):
```
cycle 1: send header
cycle 2: send data_word
```

Strided/indexed store packets (3 cycles):
```
cycle 1: send header
cycle 2: send addr
cycle 3: send data_word
```

Strided/indexed load packets (2 cycles):
```
cycle 1: send header
cycle 2: send addr
```

**Update tag state:** After last word is accepted, set tag to WAITING_FOR_RESPONSE.

---

## Non-Pipeline I/O Events

These events happen outside the pipeline stages but still involve module I/O and entry table updates.

### Cache Available (from Kamlet)

**Module I/O:**
- Receives: `witemCacheAvail.valid`, `witemCacheAvail.instr_ident`

**Entry table access:**
- Writes: `cache_is_avail = true`, `ready_for_s1 = true` for matching entry

**Notes:**
- Signals that cache slot is now ready for this witem
- Enables entry for S1 selection

### Response Handling (from RxCh0)

**Module I/O:**
- Receives: `updateSrcState.valid`, `updateSrcState.instr_ident`, `updateSrcState.tag`,
  `updateSrcState.new_state`

**Entry table access:**
- Writes: tag state (WAITING_FOR_RESPONSE → COMPLETE or NEED_TO_SEND on DROP)
- Reads: check if all tags now COMPLETE

**Sync trigger:** After updating tag state, if all tags are COMPLETE and `!complete_signaled`:
- Sends: `completeReady.valid`, `completeReady.instr_ident` to KamletWitemTable
- Writes: `complete_signaled = true`

### Fault Sync Complete (from KamletWitemTable)

**Module I/O:**
- Receives: `faultSyncComplete.valid`, `faultSyncComplete.instr_ident`,
  `faultSyncComplete.global_min_fault`

**Entry table access:**
- Writes: for each tag in WAITING_IN_CASE_FAULT:
  - If element_index >= global_min_fault → COMPLETE
  - Else → NEED_TO_SEND
- Writes: `ready_for_s1 = true` (if any tags now NEED_TO_SEND)

### Completion Sync Complete (from KamletWitemTable)

**Module I/O:**
- Receives: `completionSyncComplete.valid`, `completionSyncComplete.instr_ident`
- Sends: `witemComplete.valid`, `witemComplete.instr_ident` to Kamlet

**Entry table access:**
- Entry can now be removed (after witemComplete accepted)

---

### J2J Tag Iteration

J2J operations transfer data between cache (SRAM) and register file across jamlets.
Each jamlet iterates over its local tags and sends data to target jamlets.

**LoadJ2JWords (SRAM → RF):** Iterate over memory tags (bytes in this jamlet's cache word).
For each active tag, read from SRAM and send to the target jamlet's RF.

**StoreJ2JWords (RF → SRAM):** Iterate over register tags (bytes in this jamlet's RF word).
For each active tag, read from RF and send to the target jamlet's SRAM.

#### LoadJ2JWords: computeMemTagBounds(mem_tag)

Given a memory tag (byte position in cache word), determine if active and compute mapping.

```
function computeMemTagBounds(
    mem_tag,
    mem_ew, reg_ew, j_in_l, mem_vw,
    base_bit_addr, start_index, n_elements, elements_per_vline
) -> (tagActive, nBytes, startRegVline, endRegVline, mem_v_offset):

    mem_wb = mem_tag * 8
    mem_eb = mem_wb % mem_ew
    mem_ve = (mem_wb / mem_ew) * j_in_l + mem_vw
    mem_bit_addr_in_vline = mem_ve * mem_ew + mem_eb

    reg_bit_addr = mem_bit_addr_in_vline - base_bit_addr
    reg_eb = reg_bit_addr % reg_ew
    reg_vw = (reg_bit_addr / reg_ew) % j_in_l

    nBytes = min(mem_ew - mem_eb, reg_ew - reg_eb) / 8

    reg_ve = (reg_bit_addr / reg_ew / j_in_l) * j_in_l + reg_vw
    startRegVline = start_index / elements_per_vline
    endRegVline = (start_index + n_elements - 1) / elements_per_vline

    first_element = reg_ve + startRegVline * elements_per_vline
    last_element = reg_ve + endRegVline * elements_per_vline
    tagActive = (first_element < start_index + n_elements) && (last_element >= start_index)

    mem_v_offset = (mem_bit_addr_in_vline < base_bit_addr) ? 1 : 0

    return (tagActive, nBytes, startRegVline, endRegVline, mem_v_offset)
```

#### LoadJ2JWords: computeMemTagTarget(mem_tag, reg_v)

Given a memory tag and register vline, get the target jamlet and reg_tag for header.

```
function computeMemTagTarget(
    mem_tag, reg_v,
    mem_ew, reg_ew, j_in_l, mem_vw, base_bit_addr,
    start_index, n_elements, elements_per_vline
) -> (active, targetVw, reg_tag):

    mem_wb = mem_tag * 8
    mem_eb = mem_wb % mem_ew
    mem_ve = (mem_wb / mem_ew) * j_in_l + mem_vw
    mem_bit_addr_in_vline = mem_ve * mem_ew + mem_eb

    reg_bit_addr = mem_bit_addr_in_vline - base_bit_addr
    reg_vw = (reg_bit_addr / reg_ew) % j_in_l

    reg_ve = (reg_bit_addr / reg_ew / j_in_l) * j_in_l + reg_vw
    element_index = reg_ve + reg_v * elements_per_vline
    active = (start_index <= element_index) && (element_index < start_index + n_elements)

    // Compute reg_tag for header (byte position in DST's word)
    reg_eb = reg_bit_addr % reg_ew
    reg_we = reg_bit_addr / reg_ew / j_in_l
    reg_wb = reg_we * reg_ew + reg_eb
    reg_tag = reg_wb / 8

    targetVw = reg_vw
    return (active, targetVw, reg_tag)
```

#### StoreJ2JWords: computeRegTagBounds(reg_tag)

Given a register tag (byte position in RF word), determine if active and compute mapping.

```
function computeRegTagBounds(
    reg_tag,
    mem_ew, reg_ew, j_in_l, reg_vw,
    base_bit_addr, start_index, n_elements, elements_per_vline
) -> (tagActive, nBytes, startVline, endVline):

    reg_wb = reg_tag * 8
    reg_eb = reg_wb % reg_ew
    reg_ve = (reg_wb / reg_ew) * j_in_l + reg_vw
    reg_bit_addr_in_vline = reg_ve * reg_ew + reg_eb

    mem_bit_addr_in_vline = reg_bit_addr_in_vline + base_bit_addr
    mem_eb = mem_bit_addr_in_vline % mem_ew

    nBytes = min(mem_ew - mem_eb, reg_ew - reg_eb) / 8

    startVline = start_index / elements_per_vline
    endVline = (start_index + n_elements - 1) / elements_per_vline

    first_element = reg_ve + startVline * elements_per_vline
    last_element = reg_ve + endVline * elements_per_vline
    tagActive = (first_element < start_index + n_elements) && (last_element >= start_index)

    return (tagActive, nBytes, startVline, endVline)
```

#### StoreJ2JWords: computeRegTagTarget(reg_tag, vline)

Given a register tag and vline, get the target jamlet (which has the cache) and mem_tag for header.

```
function computeRegTagTarget(
    reg_tag, vline,
    mem_ew, reg_ew, j_in_l, reg_vw, base_bit_addr,
    start_index, n_elements, elements_per_vline
) -> (active, targetVw, mem_tag):

    reg_wb = reg_tag * 8
    reg_eb = reg_wb % reg_ew
    reg_ve = (reg_wb / reg_ew) * j_in_l + reg_vw
    reg_bit_addr_in_vline = reg_ve * reg_ew + reg_eb

    mem_bit_addr_in_vline = reg_bit_addr_in_vline + base_bit_addr
    mem_vw = (mem_bit_addr_in_vline / mem_ew) % j_in_l

    element_index = reg_ve + vline * elements_per_vline
    active = (start_index <= element_index) && (element_index < start_index + n_elements)

    // Compute mem_tag for header (byte position in DST's word)
    mem_eb = mem_bit_addr_in_vline % mem_ew
    mem_we = mem_bit_addr_in_vline / mem_ew / j_in_l
    mem_wb = mem_we * mem_ew + mem_eb
    mem_tag = mem_wb / 8

    targetVw = mem_vw
    return (active, targetVw, mem_tag)
```

#### J2J iteration loop

```
// Compute this jamlet's vword index based on word order from kinstruction
if LoadJ2JWords:
    mem_vw = coords_to_vw(this_j_x, this_j_y, mem_word_order)
else:  // StoreJ2JWords
    reg_vw = coords_to_vw(this_j_x, this_j_y, reg_word_order)

// LoadJ2JWords: iterate memory tags
// StoreJ2JWords: iterate register tags
tag = 0
while tag < word_bytes:
    if LoadJ2JWords:
        (tagActive, nBytes, startVline, endVline, v_offset) = computeMemTagBounds(tag, ...)
    else:  // StoreJ2JWords
        (tagActive, nBytes, startVline, endVline) = computeRegTagBounds(tag, ...)

    if tagActive:
        for v in startVline..endVline:
            if LoadJ2JWords:
                (active, targetVw, reg_tag) = computeMemTagTarget(tag, v, ...)
                src_tag = tag      // mem_tag (this jamlet's SRAM byte)
                dst_tag = reg_tag  // reg_tag (target jamlet's RF byte)
            else:  // StoreJ2JWords
                (active, targetVw, mem_tag) = computeRegTagTarget(tag, v, ...)
                src_tag = tag      // reg_tag (this jamlet's RF byte)
                dst_tag = mem_tag  // mem_tag (target jamlet's SRAM byte)

            if active:
                target_coords = vw_to_coords(targetVw, word_order)
                emit to S13: (src_tag, dst_tag, v, target_coords, nBytes, ...)

    tag += nBytes  // advance by nBytes, batch-complete covered tags
```

### Strided/Indexed Tag Iteration

Strided and indexed operations have one element per jamlet (n_elements <= j_in_l).
Tag iteration happens within that single element, using `page_mem_ew` from TLB response
to determine memory element boundaries.

**Key insight:** We now have `page_mem_ew` from TLB, which tells us the memory-side element
width. A tag generates a request at any boundary:
- RF element boundary (`rf_eb == 0`)
- Memory element boundary (`mem_eb == 0`)
- Page boundary (`page_byte_offset == 0`)

#### computeTagInfo(tag)

```
function computeTagInfo(
    tag, rf_ew, mem_ew, g_addr, page_bytes
) -> (tag_active, n_bytes, target_byte_in_word):

    rf_wb = tag * 8
    rf_eb = rf_wb % rf_ew

    tag_addr = g_addr + tag
    page_byte_offset = tag_addr % page_bytes

    mem_eb = (tag_addr * 8) % mem_ew
    target_byte_in_word = tag_addr % word_bytes

    tag_active = (rf_eb == 0) || (mem_eb == 0) || (page_byte_offset == 0)

    remaining_rf = (rf_ew - rf_eb) / 8
    remaining_mem = (mem_ew - mem_eb) / 8
    remaining_page = page_bytes - page_byte_offset
    remaining_word = word_bytes - target_byte_in_word

    n_bytes = min(remaining_rf, remaining_mem, remaining_page, remaining_word)

    return (tag_active, n_bytes, target_byte_in_word)
```

#### Strided/Indexed iteration loop

```
element_bytes = rf_ew / 8
element_start_tag = ... // byte offset of element within word
element_end_tag = element_start_tag + element_bytes

// Batch-complete tags before element
for tag in 0..<element_start_tag:
    set tag COMPLETE

// Iterate over element's tags
tag = element_start_tag
while tag < element_end_tag:
    tag_offset_in_element = tag - element_start_tag
    tag_addr = g_addr + tag_offset_in_element

    // Determine which page this tag is on
    if crosses_page && tag_addr >= page_boundary:
        page_info = page2
    else:
        page_info = page1

    if page_info.fault:
        set tag WAITING_IN_CASE_FAULT
        tag += 1
        continue

    (tag_active, n_bytes, target_byte) = computeTagInfo(
        tag, rf_ew, page_info.mem_ew, g_addr, page_bytes)

    if tag_active:
        emit to S13: (tag, n_bytes, target_byte, page_info.target_coords, page_info.paddr)
    else:
        set tag COMPLETE

    tag += n_bytes

// Batch-complete tags after element
for tag in element_end_tag..<word_bytes:
    set tag COMPLETE
```
