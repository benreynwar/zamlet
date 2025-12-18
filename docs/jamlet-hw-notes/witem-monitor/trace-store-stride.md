# Trace: StoreStride

Strided store where RF data is sent to jamlets that have the target cache addresses.
Each element i is stored to address (base + i * stride_bytes). Uses WRITE_MEM_WORD_REQ
messages to write to target jamlets' cache.

**Note:** No DST side in WitemMonitor - the receiving jamlet handles writes via RxCh1's
WaitingWriteMemWord. Only SRC-side protocol tracking in WitemMonitor.

**Key constraint:** n_elements is limited to j_in_l, so each jamlet processes exactly ONE
element. This simplifies the pipeline significantly - we do TLB lookup(s) for the element
first, then iterate tags with full alignment knowledge.

## Example Configuration

```
Lamlet geometry:
  k_cols = 2, k_rows = 2  (4 kamlets)
  j_cols = 2, j_rows = 2  (4 jamlets per kamlet)
  j_in_l = 16             (total jamlets in lamlet)

Memory parameters:
  word_bytes = 8          (64-bit words)
  vline_bytes = 128       (16 words per vline)
  page_bytes = 4096

Word ordering: STANDARD
  vw_index = j_y * j_cols_total + j_x
  j_cols_total = j_cols * k_cols = 4

This jamlet: (2, 1)
  j_x = 2, j_y = 1
  src_vw = 1 * 4 + 2 = 6
```

## Instruction Parameters (from kamletEntryResp)

```
instr_ident = 42
src = 0                   (base register number)
g_addr = 0x1000           (base address for element 0)
stride_bytes = 256        (byte stride between elements)

Source ordering (src_ordering):
  src_ew = 32             (32-bit elements in register)
  src_word_order = STANDARD

Transfer range:
  start_index = 0
  n_elements = 16         (limited to j_in_l)

mask_reg = None           (no masking in this example)
```

## Entry Creation

All tags initialized:
```
for tag in 0..7:
  transaction_states[tag] = INITIAL
```

**Note:** StoreStride only has SRC-side state (transaction_states). There is no dst_state
because the receiving jamlet handles writes via RxCh1, not WitemMonitor.

**Note:** In the hardware implementation, each jamlet has its own array of transaction states
(word_bytes entries). This differs from the Python model where states are combined at the
kamlet level with `j_in_k * word_bytes` entries indexed by `j_in_k_index * word_bytes + tag`.

## S1-S3: Entry Selection and Kamlet Lookup

**S1**: Entry selected (has INITIAL tags)
**S2**: Send kamletEntryReq with instr_ident=42
**S3**: Receive kamletEntryResp with instruction parameters above

## Pipeline Register Summary

Values passed between pipeline stages:

```
S3 -> S4:
    instr_ident         : UInt     // instruction identifier
    src                 : UInt     // base register number
    g_addr              : UInt     // base global address
    stride_bytes        : UInt     // byte stride between elements
    src_ew              : UInt     // source element width (bits)
    start_index         : UInt     // first element index in transfer
    n_elements          : UInt     // number of elements to transfer
    mask_reg            : UInt     // mask register (or invalid)
    mask_enabled        : Bool     // whether masking is enabled

S4 -> S5:
    instr_ident         : UInt
    src                 : UInt
    src_ew              : UInt
    src_v               : UInt     // register vline offset from src
    src_e               : UInt     // actual element index being processed
    element_active      : Bool     // true if element is in range
    (mask RF read issued if mask_enabled)

S6 -> S7:
    instr_ident         : UInt
    src                 : UInt
    src_ew              : UInt
    src_v               : UInt
    src_e               : UInt
    element_active      : Bool     // updated with mask check
    mask_word           : UInt     // RF response (if mask_enabled)

S7 -> S8:
    instr_ident         : UInt
    src                 : UInt
    src_ew              : UInt
    src_v               : UInt
    src_e               : UInt
    dst_g_addr          : UInt     // computed destination address for element start
    element_end_addr    : UInt     // address of last byte of element
    crosses_page        : Bool     // true if element spans two pages
    page_boundary       : UInt     // page boundary address (if crosses_page)
    masked_out          : Bool     // true if this element is masked
    element_active      : Bool     // updated with mask check

S10 -> S11:
    instr_ident         : UInt
    src                 : UInt
    src_ew              : UInt
    src_v               : UInt
    src_e               : UInt
    dst_g_addr          : UInt
    element_active      : Bool
    crosses_page        : Bool
    page_boundary       : UInt
    // TLB responses:
    page1_is_vpu        : Bool
    page1_mem_ew        : UInt     // destination element width (if VPU memory)
    page1_target_x      : UInt
    page1_target_y      : UInt
    page1_fault         : Bool
    page2_info          : ...      // second page info (if crosses_page)

S12 -> S13 (per active tag, S11-S12 iterate):
    instr_ident         : UInt
    mem_tag             : UInt     // byte position in this jamlet's RF word (0-7)
    src_v               : UInt
    target_x            : UInt     // DST jamlet X
    target_y            : UInt     // DST jamlet Y
    dst_byte_in_word    : UInt     // byte offset in target word
    n_bytes             : UInt     // number of bytes to write
    is_vpu              : Bool     // VPU memory vs scalar memory
    addr                : UInt     // translated address
    (RF read issued for src data)

S13 -> S14:
    instr_ident         : UInt
    mem_tag             : UInt
    target_x            : UInt
    target_y            : UInt
    dst_byte_in_word    : UInt
    n_bytes             : UInt
    addr                : KMAddr/ScalarAddr

S14 -> S15:
    instr_ident         : UInt
    mem_tag             : UInt
    target_x            : UInt
    target_y            : UInt
    dst_byte_in_word    : UInt
    n_bytes             : UInt
    addr                : KMAddr/ScalarAddr
    src_word            : UInt     // 64-bit word read from RF
```

## S4: Element Computation + Mask RF Read Issue

S4 computes element info for this jamlet. Since n_elements <= j_in_l, each jamlet has
exactly one element to process. If mask_enabled, S4 also issues a mask RF read.

### Function: computeElementInfo()

```
function computeElementInfo(
    src_ew, j_in_l, src_vw, start_index, n_elements
) -> (element_active, src_e, src_v):

    // Which element within word does this jamlet hold?
    src_we = 0  // first element in word (since n_elements <= j_in_l)
    src_ve = src_we * j_in_l + src_vw

    elements_in_vline = vline_bytes * 8 / src_ew

    // Determine which vline this element is in
    if src_ve < start_index % elements_in_vline:
        src_v = start_index / elements_in_vline + 1
    else:
        src_v = start_index / elements_in_vline

    src_e = src_v * elements_in_vline + src_ve

    // Check if element is in range
    element_active = (src_e >= start_index) && (src_e < start_index + n_elements)

    return (element_active, src_e, src_v)
```

### Example: computeElementInfo()

```
src_we = 0
src_ve = 0 * 16 + 6 = 6

elements_in_vline = 128 * 8 / 32 = 32
src_v = 0 / 32 = 0  (since 6 >= 0 % 32)
src_e = 0 * 32 + 6 = 6

element_active = (6 >= 0) && (6 < 16) = true

-> (element_active=true, src_e=6, src_v=0)
```

**If element not active:** Skip to completion - batch-complete all tags.

## S5: Mask RF Read Wait

Wait cycle for RF read latency. Pass-through stage when `s4_s5_forward_buf` is disabled.

## S6: Mask RF Response

S6 receives the mask RF response (if mask_enabled) and registers the mask word for use in S7.

## S7: Mask Check + Compute Address

S7 checks the mask bit and computes the destination address.

### Mask check (if mask_enabled)

```
mask_bit = (mask_word >> mask_bit_pos) & 1
masked_out = mask_enabled && (mask_bit == 0)
element_active = element_active && !masked_out
```

### Compute destination address and check page crossing

```
element_bytes = src_ew / 8 = 4
dst_g_addr = g_addr + src_e * stride_bytes
           = 0x1000 + 6 * 256 = 0x1600

element_end_addr = dst_g_addr + element_bytes - 1
                 = 0x1600 + 3 = 0x1603

page_of_start = dst_g_addr / page_bytes = 0x1600 / 4096 = 0
page_of_end = element_end_addr / page_bytes = 0x1603 / 4096 = 0

crosses_page = (page_of_start != page_of_end) = false
```

## S8: TLB Issue

```
tlbReq.valid = element_active && !masked_out
tlbReq.vaddr = dst_g_addr
tlbReq.isWrite = true
```

**If element not active:** Skip to completion - batch-complete all tags.

## S9: TLB Wait

Wait cycle for TLB lookup latency. Pass-through stage when `s8_s9_forward_buf` is disabled.

## S10: TLB Response

S10 receives the first TLB response. If the element crosses a page boundary, S8 issues
a second TLB request on the next cycle (stalls S7 and below).

```
// First TLB response
tlbResp.paddr = ...
tlbResp.fault = NONE
tlbResp.is_vpu = true
tlbResp.k_index = 1
tlbResp.j_in_k_index = 2
tlbResp.mem_ew = 32          // destination memory's element width (for VPU)

// Store first page info
page1_is_vpu = tlbResp.is_vpu
page1_mem_ew = tlbResp.mem_ew
page1_target_x, page1_target_y = k_indices_to_j_coords(k_index=1, j_in_k_index=2)
page1_fault = (tlbResp.fault != NONE)
```

**Fault handling:** If TLB returns fault, record min_fault_element, set page1_fault=true.

## S11-S12: Tag Iteration (Multi-cycle, stalls pipeline)

S11 computes tag bounds, and S12 emits active tags to S13. These stages iterate through
tags, using the TLB response(s) to compute nBytes and determine which tags generate
requests. These stages stall the pipeline while iterating.

**Key insight:** Now that we have mem_ew (destination element width) from TLB, we can
compute the correct nBytes for each tag and determine which tags are active.

### Tag activity condition

A tag generates a request if ANY of:
- `src_eb == 0` (source element boundary)
- `mem_eb == 0` (destination element boundary)
- `page_byte_offset == 0` (page boundary)

### Function: computeTagInfo(tag, page_info)

```
function computeTagInfo(
    tag, src_ew, mem_ew, dst_g_addr, page_bytes
) -> (tag_active, n_bytes, dst_byte_in_word, mem_eb):

    src_wb = tag * 8                          // bit offset in source word
    src_eb = src_wb % src_ew                  // byte within source element

    tag_dst_addr = dst_g_addr + (src_wb / 8)  // destination address for this tag
    page_byte_offset = tag_dst_addr % page_bytes

    mem_eb = (tag_dst_addr * 8) % mem_ew      // bit offset in destination element
    dst_byte_in_word = tag_dst_addr % word_bytes

    // Tag is active if at any boundary
    tag_active = (src_eb == 0) || (mem_eb == 0) || (page_byte_offset == 0)

    // Compute n_bytes: minimum of remaining src element, remaining dst element,
    // remaining page, remaining word
    remaining_src = (src_ew - src_eb) / 8
    remaining_dst = (mem_ew - mem_eb) / 8
    remaining_page = page_bytes - page_byte_offset
    remaining_word = word_bytes - dst_byte_in_word

    n_bytes = min(remaining_src, remaining_dst, remaining_page, remaining_word)

    return (tag_active, n_bytes, dst_byte_in_word, mem_eb)
```

### Tag iteration loop

```
tag = 0
while tag < word_bytes:
    // Determine which page this tag is on
    tag_dst_addr = dst_g_addr + tag
    if crosses_page && tag_dst_addr >= page_boundary:
        // Use second page info (wait for second TLB if not ready)
        page_info = page2_info
    else:
        page_info = page1_info

    if page_info.fault:
        // Mark remaining tags as needing fault handling
        transaction_states[tag] = WAITING_IN_CASE_FAULT
        tag += 1
        continue

    (tag_active, n_bytes, dst_byte_in_word, mem_eb) = computeTagInfo(
        tag, src_ew, page_info.mem_ew, dst_g_addr, page_bytes)

    if tag_active:
        // Pass to S13
        emit to S13: (mem_tag=tag, n_bytes, dst_byte_in_word, target_x, target_y, ...)
        transaction_states[tag] = WAITING_FOR_RESPONSE  // will be set after S15 send
    else:
        // Batch-complete this tag
        transaction_states[tag] = COMPLETE

    // Skip to next potential tag (advance by n_bytes for efficiency)
    tag += n_bytes
```

### Example: Tag iteration (no page crossing)

With src_ew=32, mem_ew=32, dst_g_addr=0x1600:

**Tag 0:**
```
src_wb = 0, src_eb = 0
tag_dst_addr = 0x1600, page_byte_offset = 0x600 (non-zero)
mem_eb = 0
dst_byte_in_word = 0

tag_active = (0 == 0) || (0 == 0) || (0x600 == 0) = true

remaining_src = 4, remaining_dst = 4, remaining_page = 0xA00, remaining_word = 8
n_bytes = min(4, 4, 0xA00, 8) = 4

-> Emit to S7: tag=0, n_bytes=4, dst_byte_in_word=0
-> Advance tag by 4: tag = 4
```

**Tag 4:**
```
src_wb = 32, src_eb = 0  (second element in word, but src_e=22 is out of range!)
```

Wait - tag 4 corresponds to the second element in the word (src_we=1), which maps to
src_e=22, which is out of range. But we already determined in S4 that only one element
is active per jamlet. So tags 4-7 should have been handled earlier.

Actually, let's reconsider. With src_ew=32:
- Tags 0-3 are all bytes of element 0 (src_e=6, which is active)
- Tags 4-7 are all bytes of element 1 (src_e=22, which is out of range)

So S6 only iterates over tags 0-3 (the active element's bytes). Tags 4-7 are
batch-completed because they belong to an out-of-range element.

**Revised tag iteration:**
```
element_start_tag = 0                    // first tag of active element
element_end_tag = src_ew / 8 = 4         // one past last tag of element

// Batch-complete tags before element
for tag in 0..<element_start_tag:
    transaction_states[tag] = COMPLETE

// Iterate only over element's tags
tag = element_start_tag
while tag < element_end_tag:
    ... (computeTagInfo and emit to S7)
    tag += n_bytes

// Batch-complete tags after element
for tag in element_end_tag..<word_bytes:
    transaction_states[tag] = COMPLETE
```

**Tag 0:**
```
tag_active = true (src_eb=0)
n_bytes = 4
-> Emit to S13: tag=0, n_bytes=4
-> Advance: tag = 4
-> tag >= element_end_tag, exit loop
```

**State after S11-S12:**

| Tag | transaction_state |
|-----|-------------------|
| 0   | (passed to S13)   |
| 1-3 | COMPLETE (skipped by n_bytes) |
| 4-7 | COMPLETE (out of range element) |

Only tag 0 generates a request. Tags 1-3 are covered by tag 0's n_bytes=4.

### Example: Page crossing case

Suppose dst_g_addr=0x0FFE (element starts 2 bytes before page boundary at 0x1000):

```
element_bytes = 4
element_end_addr = 0x0FFE + 3 = 0x1001
page_boundary = 0x1000

crosses_page = true
```

**S8:** Issues second TLB for address 0x1000 (after first TLB completes in S10).

**S11-S12 tag iteration:**

**Tag 0 (addr 0x0FFE, page 0):**
```
src_eb = 0, mem_eb = depends on page0's mem_ew
page_byte_offset = 0x0FFE % 4096 = 0x0FFE (non-zero)

remaining_page = 4096 - 0x0FFE = 2  // only 2 bytes left in page!

n_bytes = min(4, ..., 2, ...) = 2

-> Emit to S13: tag=0, n_bytes=2
-> Advance: tag = 2
```

**Tag 2 (addr 0x1000, page 1):**
```
page_byte_offset = 0  // at page boundary!

tag_active = true (page_byte_offset == 0)

// Use page1's TLB info
n_bytes = 2  // remaining bytes of element

-> Emit to S13: tag=2, n_bytes=2
-> Advance: tag = 4
```

Two requests generated: one for each page portion of the element.

## S13: Data RF Read Issue + Build Header

S13 receives tag info from S12 and issues RF read for source data.

```
// Issue RF read
rfReq.valid = true
rfReq.addr = src + src_v = 0 + 0 = 0
rfReq.isWrite = false
```

## S14: Data RF Read Wait

Wait cycle for RF read latency. Pass-through stage when `s13_s14_forward_buf` is disabled.

## S15: Data RF Response + Build Packet + Send

S15 receives RF data and assembles the WriteMemWordHeader.

```
src_word = rfResp.readData   // 64-bit word from RF[0]

ident = (instr_ident + mem_tag + 1) % max_response_tags
      = (42 + 0 + 1) % 128 = 43
```

### Build WriteMemWordHeader

| Field | Value | Source |
|-------|-------|--------|
| target_x | 2 | From S6 (TLB response) |
| target_y | 2 | From S6 (TLB response) |
| source_x | 2 | thisX (this jamlet's X coordinate) |
| source_y | 1 | thisY (this jamlet's Y coordinate) |
| length | 3 | 1 (header) + 1 (addr) + 1 (data) |
| message_type | WRITE_MEM_WORD_REQ | Fixed for this witem type |
| send_type | SINGLE | Point-to-point message |
| ident | 43 | (instr_ident + mem_tag + 1) % max_response_tags |
| tag | 0 | Memory tag being processed |
| dst_byte_in_word | 0 | Byte offset in target word |
| n_bytes | 4 | Number of bytes to write |

### Build payload

```
payload[0] = addr       // KMAddr for VPU, ScalarAddr for scalar
payload[1] = src_word   // 64-bit word read from RF
```

### Send Packet

```
// Send header word
packetOut.valid = true
packetOut.bits.isHeader = true
packetOut.bits.data = header

// Wait for ready, then send addr word
packetOut.bits.isHeader = false
packetOut.bits.data = addr

// Wait for ready, then send data word
packetOut.bits.data = src_word
```

Update state: transaction_states[0] = WAITING_FOR_RESPONSE

## Response Handling (RxCh0)

### Receives WRITE_MEM_WORD_RESP

```
// Header contains: ident=43, tag=0, source_x=2, source_y=2
// Compute parent ident
parent_ident = (ident - tag - 1) % max_response_tags
             = (43 - 0 - 1) % 128 = 42

entry = lookup_entry(parent_ident=42)
entry.transaction_states[tag].state = COMPLETE
```

### Error Path: DROP

If DST can't handle the request (cache not ready, no witem slots):

```
// Receives WRITE_MEM_WORD_DROP
entry.transaction_states[tag].state = NEED_TO_SEND  // will retry
```

### Error Path: RETRY

If DST had to wait for cache but is now ready:

```
// Receives WRITE_MEM_WORD_RETRY
entry.transaction_states[tag].state = NEED_TO_SEND  // resend with data
```

**Note:** Unlike loads, stores use RETRY because DST needs the data resent after cache
becomes ready. DST creates a WaitingWriteMemWord entry that sends RETRY when ready.

## Two-Phase Synchronization

StoreStride uses synchronization to handle faults across kamlets. Synchronization is
handled by a **separate state machine outside the 15-stage pipeline**.

### Entry Table Extension

Each witem entry has an additional state bit:

```
WitemEntry (for StoreStride):
    ...
    ready_to_process    : Bool     // eligible for S1 selection
    had_page_fault      : Bool     // recorded during first pass
    global_min_fault    : UInt     // set when fault sync completes
```

### Sync Interface

WitemMonitor has an interface to send/receive sync events:

```
// Send local event to synchronizer (triggered after S6 completes all tags)
-> syncLocalEvent.valid     : Bool
-> syncLocalEvent.ident     : UInt     // fault_sync uses instr_ident, completion_sync uses instr_ident+1
-> syncLocalEvent.value     : UInt     // min_fault_element (or max value if no faults)
```

### Sync Receiver Hardware

WitemMonitor has hardware that receives sync completions from the synchronizer:

```
// On sync completion signal from synchronizer
syncComplete.valid     : Bool
syncComplete.ident     : UInt
syncComplete.min_value : UInt     // global min fault element (or max if no faults)

// When sync completes, find matching entry and update
when syncComplete.valid:
    entry = lookup_entry_by_sync_ident(syncComplete.ident)
    if entry is fault_sync:
        entry.global_min_fault = syncComplete.min_value
        entry.ready_to_process = true   // re-enable for second pass
    else if entry is completion_sync:
        // witem is done, signal witemComplete
```

### Phase 1: Fault Sync

**First pass through pipeline (S4-S12):**
- Process element, recording had_page_fault if TLB fault occurs
- Tags go to WAITING_IN_CASE_FAULT (non-idempotent), WAITING_FOR_RESPONSE, or COMPLETE
- After S12 finishes: set ready_to_process=0, trigger fault sync

```
// Trigger fault sync after first pass
fault_sync_ident = instr_ident
synchronizer.local_event(fault_sync_ident, value=min_fault_element)
entry.ready_to_process = false
```

**After fault sync completes (sync receiver):**
- Sync receiver sets global_min_fault and ready_to_process=true
- Entry becomes eligible for S1 selection again

**Second pass through pipeline (S11-S12):**
- S11-S12 checks tags in WAITING_IN_CASE_FAULT state
- If src_e >= global_min_fault: set COMPLETE (don't write past fault)
- Else: set NEED_TO_SEND (will proceed through S13-S15)
- After S12 finishes: set ready_to_process=0, trigger completion sync

### Phase 2: Completion Sync

After all transaction_states are COMPLETE:

```
completion_sync_ident = (instr_ident + 1) % max_response_tags
synchronizer.local_event(completion_sync_ident)
entry.ready_to_process = false
```

When completion sync completes, witem is ready for finalization.

### S1 Selection Criteria

S1 selects entries where:
```
entry.valid &&
entry.ready_to_process &&
(any tag in INITIAL || any tag in NEED_TO_SEND || any tag in WAITING_IN_CASE_FAULT)
```

## Completion

When all transaction_states == COMPLETE AND completion_sync_state == COMPLETE:

Signal `witemComplete.valid = true, witemComplete.bits = 42` to kamlet.

## Differences from LoadJ2JWords

| Aspect | LoadJ2JWords | StoreStride |
|--------|--------------|-------------|
| Data source | SRAM (cache) | RF |
| Data destination | RF | SRAM (via RxCh1) |
| DST handling | WitemMonitor dst_state | RxCh1 WaitingWriteMemWord |
| TLB needed | No | Yes (strided addressing) |
| TLB timing | N/A | S8-S10 (before tag iteration) |
| Tag iteration | S11-S12 (no TLB needed) | S11-S12 (after TLB, with mem_ew) |
| n_elements | Can span multiple vlines | Limited to j_in_l (one element per jamlet) |
| Page crossing | N/A | May need 2 TLB lookups per element |
| Mask check | At DST (RxCh1) | At SRC (S4-S7) |
| Message type | LOAD_J2J_WORDS_REQ | WRITE_MEM_WORD_REQ |
| RETRY used | No | Yes |
| Synchronization | None | Fault sync + completion sync |
