# Trace: LoadIndexedUnordered

Indexed (gather) load where element i is loaded from address `(base + index_vector[i])`.
Uses READ_MEM_WORD_REQ messages to request data from target jamlets' cache.

**Key characteristics:**
- Address for each element comes from an index register (not a constant stride)
- n_elements limited to j_in_l (one element per jamlet)
- Sends READ_MEM_WORD_REQ, receives data in response
- Two-phase synchronization (fault sync + completion sync)

**Data flow:** Memory (remote cache or scalar) → RF (this jamlet)

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
  dst_vw = 1 * 4 + 2 = 6
```

## Instruction Parameters (from kamletEntryResp)

```
instr_ident = 42
dst = 0                   (destination register number)
g_addr = 0x1000           (base address)
index_reg = 8             (register containing byte offsets)

Index ordering (index_ordering):
  index_ew = 32           (32-bit index values)
  index_word_order = STANDARD

Destination ordering (dst_ordering):
  dst_ew = 32             (32-bit data elements)
  dst_word_order = STANDARD

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

**Note:** LoadIndexedUnordered only has SRC-side state (transaction_states). The "SRC" here is
the remote memory being read from. DST (this jamlet's RF) doesn't need protocol tracking because
we control the response write locally.

## S1-S3: Entry Selection and Kamlet Lookup

**S1**: Entry selected (has INITIAL tags AND ready_to_process=true)
**S2**: Send kamletEntryReq with instr_ident=42
**S3**: Receive kamletEntryResp with instruction parameters above

## Pipeline Register Summary

```
S3 -> S4:
    instr_ident         : UInt     // instruction identifier
    dst                 : UInt     // destination register number
    g_addr              : UInt     // base global address
    index_reg           : UInt     // register containing index values
    index_ew            : UInt     // index element width (bits)
    dst_ew              : UInt     // destination element width (bits)
    start_index         : UInt     // first element index in transfer
    n_elements          : UInt     // number of elements to transfer
    mask_reg            : UInt     // mask register (or invalid)
    mask_enabled        : Bool     // whether masking is enabled

S4 -> S5:
    instr_ident         : UInt
    dst                 : UInt
    dst_ew              : UInt
    dst_v               : UInt     // register vline offset from dst
    dst_e               : UInt     // actual element index being processed
    element_active      : Bool     // true if element is in range
    (index RF read issued)
    (mask RF read issued if mask_enabled)

S6 -> S7:
    instr_ident         : UInt
    dst                 : UInt
    dst_ew              : UInt
    dst_v               : UInt
    dst_e               : UInt
    element_active      : Bool
    index_word          : UInt     // RF response containing index value
    mask_word           : UInt     // RF response (if mask_enabled)

S7 -> S8:
    instr_ident         : UInt
    dst                 : UInt
    dst_ew              : UInt
    dst_v               : UInt
    dst_e               : UInt
    src_g_addr          : UInt     // computed source address for element start
    element_end_addr    : UInt     // address of last byte of element
    crosses_page        : Bool     // true if element spans two pages
    page_boundary       : UInt     // page boundary address (if crosses_page)
    masked_out          : Bool     // true if this element is masked
    element_active      : Bool     // updated with mask check

S10 -> S11:
    instr_ident         : UInt
    dst                 : UInt
    dst_ew              : UInt
    dst_v               : UInt
    dst_e               : UInt
    src_g_addr          : UInt
    element_active      : Bool
    crosses_page        : Bool
    page_boundary       : UInt
    // TLB responses:
    page1_is_vpu        : Bool
    page1_mem_ew        : UInt     // source memory's element width (if VPU memory)
    page1_target_x      : UInt
    page1_target_y      : UInt
    page1_fault         : Bool
    page2_info          : ...      // second page info (if crosses_page)

S12 -> S13 (per active tag, S11-S12 iterate):
    instr_ident         : UInt
    mem_tag             : UInt     // byte position in this jamlet's RF word (0-7)
    dst_v               : UInt
    target_x            : UInt     // remote jamlet X (or 0 for scalar)
    target_y            : UInt     // remote jamlet Y (or -1 for scalar)
    src_byte_in_word    : UInt     // byte offset in source word
    n_bytes             : UInt     // number of bytes to read
    is_vpu              : Bool     // VPU memory vs scalar memory
    addr                : UInt     // translated address (KMAddr or ScalarAddr)

S13 -> S14:
    instr_ident         : UInt
    mem_tag             : UInt
    target_x            : UInt
    target_y            : UInt
    src_byte_in_word    : UInt
    n_bytes             : UInt
    addr                : KMAddr/ScalarAddr
```

## S4: Element Computation + Index/Mask RF Read Issue

S4 computes element info and issues RF reads for the index register (to get the element's
byte offset) and the mask register (if mask_enabled).

### Step 1: Compute element info

```
// Which element does this jamlet hold?
dst_we = 0  // first element in word (since n_elements <= j_in_l)
dst_ve = dst_we * j_in_l + dst_vw = 0 * 16 + 6 = 6

elements_in_vline = vline_bytes * 8 / dst_ew = 128 * 8 / 32 = 32
dst_v = start_index / elements_in_vline = 0 / 32 = 0
dst_e = dst_v * elements_in_vline + dst_ve = 0 * 32 + 6 = 6

// Check if element is in range
element_active = (dst_e >= start_index) && (dst_e < start_index + n_elements)
               = (6 >= 0) && (6 < 16) = true
```

### Step 2: Issue index register read

The index register stores byte offsets for each element. We need to read the offset for
element dst_e=6.

```
// Index element position (same formula as destination)
index_elements_in_vline = vline_bytes * 8 / index_ew = 32
index_v = dst_e / index_elements_in_vline = 6 / 32 = 0
index_ve = dst_e % index_elements_in_vline = 6
index_we = index_ve / j_in_l = 6 / 16 = 0

index_reg_addr = index_reg + index_v = 8 + 0 = 8
byte_in_word = (index_we * index_ew / 8) % word_bytes = (0 * 4) % 8 = 0

// Issue RF read for index word
rfReq[0].valid = element_active
rfReq[0].addr = index_reg_addr * word_bytes = 64
rfReq[0].isWrite = false
```

**Note:** For this jamlet (vw=6), the index value is at byte 0 of the word (index_we=0).
Other jamlets with different vw values may have index_we=1, putting their index at bytes 4-7.

Also issues mask RF read if mask_enabled (not in this example).

**If element not active:** Skip to completion - batch-complete all tags.

## S5: Index/Mask RF Read Wait

Wait cycle for RF read latency. Pass-through stage when `s4_s5_forward_buf` is disabled.

## S6: Index/Mask RF Response

S6 receives the RF responses containing the index value (and mask word if mask_enabled).

## S7: Mask Check + Compute Address

S7 extracts the index value from the RF response, computes the source address, and checks
the mask.

### Mask check (if mask_enabled)

```
mask_bit = (mask_word >> mask_bit_pos) & 1
masked_out = mask_enabled && (mask_bit == 0)
element_active = element_active && !masked_out
```

### Compute source address

```
// Assume index register contains: [0x100, 0x200, 0x300, 0x400, ...]
// Element 6's index is at byte_in_word=0, so index_value = 0x100 (example)
index_value = index_word[byte_in_word : byte_in_word + index_ew/8]
            = index_word[0:4] as little-endian uint32
            = 0x100  (256 bytes)

// Source address = base + index_value
src_g_addr = g_addr + index_value = 0x1000 + 0x100 = 0x1100

element_bytes = dst_ew / 8 = 4
element_end_addr = src_g_addr + element_bytes - 1 = 0x1103

page_of_start = src_g_addr / page_bytes = 0x1100 / 4096 = 1
page_of_end = element_end_addr / page_bytes = 0x1103 / 4096 = 1

crosses_page = (page_of_start != page_of_end) = false
```

## S8: TLB Issue

```
tlbReq.valid = element_active && !masked_out
tlbReq.vaddr = src_g_addr = 0x1100
tlbReq.isWrite = false  // This is a READ (load)
```

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
tlbResp.j_in_k_index = 3
tlbResp.mem_ew = 32          // source memory's element width

// Store first page info
page1_is_vpu = tlbResp.is_vpu
page1_mem_ew = tlbResp.mem_ew
page1_target_x, page1_target_y = k_indices_to_j_coords(k_index=1, j_in_k_index=3)
page1_fault = (tlbResp.fault != NONE)
```

**Fault handling:** If TLB returns fault, record min_fault_element, set page1_fault=true.
Element may still proceed if it's idempotent memory (will be resolved in fault sync).

## S11-S12: Tag Iteration (Multi-cycle, stalls pipeline)

S11 computes tag bounds, and S12 emits active tags to S13. These stages iterate through
tags, using the TLB response(s) to compute nBytes and determine which tags generate
requests. These stages stall the pipeline while iterating.

**Key insight:** Now that we have mem_ew (source element width) from TLB, we can compute
the correct nBytes for each tag.

### Tag activity condition

A tag generates a request if ANY of:
- `dst_eb == 0` (destination element boundary)
- `src_eb == 0` (source element boundary)
- `page_byte_offset == 0` (page boundary)

### Function: computeTagInfo(tag, page_info)

```
function computeTagInfo(
    tag, dst_ew, mem_ew, src_g_addr, page_bytes
) -> (tag_active, n_bytes, src_byte_in_word, dst_eb):

    dst_wb = tag * 8                          // bit offset in destination word
    dst_eb = dst_wb % dst_ew                  // byte within destination element

    tag_src_addr = src_g_addr + (dst_wb / 8)  // source address for this tag
    page_byte_offset = tag_src_addr % page_bytes

    src_eb = (tag_src_addr * 8) % mem_ew      // bit offset in source element
    src_byte_in_word = tag_src_addr % word_bytes

    // Tag is active if at any boundary
    tag_active = (dst_eb == 0) || (src_eb == 0) || (page_byte_offset == 0)

    // Compute n_bytes: minimum of remaining dst element, remaining src element,
    // remaining page, remaining word
    remaining_dst = (dst_ew - dst_eb) / 8
    remaining_src = (mem_ew - src_eb) / 8
    remaining_page = page_bytes - page_byte_offset
    remaining_word = word_bytes - src_byte_in_word

    n_bytes = min(remaining_dst, remaining_src, remaining_page, remaining_word)

    return (tag_active, n_bytes, src_byte_in_word, dst_eb)
```

### Example: Tag iteration (no page crossing)

With dst_ew=32, mem_ew=32, src_g_addr=0x1100:

**Tag 0:**
```
dst_wb = 0, dst_eb = 0
tag_src_addr = 0x1100, page_byte_offset = 0x100
src_eb = 0
src_byte_in_word = 0

tag_active = (0 == 0) || (0 == 0) || (0x100 == 0) = true

remaining_dst = 4, remaining_src = 4, remaining_page = 0xF00, remaining_word = 8
n_bytes = min(4, 4, 0xF00, 8) = 4

-> Emit to S13: tag=0, n_bytes=4, src_byte_in_word=0
-> Set transaction_states[0] = WAITING_FOR_RESPONSE
-> Advance tag by 4: tag = 4
```

**Tags 4-7:** Out of element range (dst_ew=32 means only 4 bytes = tags 0-3).
Batch-complete tags 4-7.

**State after S11-S12:**

| Tag | transaction_state |
|-----|-------------------|
| 0   | WAITING_FOR_RESPONSE |
| 1-3 | COMPLETE (covered by tag 0's n_bytes=4) |
| 4-7 | COMPLETE (out of element range) |

## S13: Build Header (No Data RF Read Needed)

Unlike StoreStride, LoadIndexedUnordered doesn't read source data here - the data comes
back in the response. S13 just prepares the request packet.

```
// Compute translated address
if is_vpu:
    k_maddr = translate(src_g_addr)
    word_offset = k_maddr.addr % word_bytes
    addr = k_maddr.word_aligned()
else:
    addr = translate_to_scalar(src_g_addr)
```

### Build ReadMemWordHeader

| Field | Value | Source |
|-------|-------|--------|
| target_x | 3 | From S10 (TLB response) |
| target_y | 1 | From S10 (TLB response) |
| source_x | 2 | thisX (this jamlet's X coordinate) |
| source_y | 1 | thisY (this jamlet's Y coordinate) |
| length | 2 | 1 (header) + 1 (addr) |
| message_type | READ_MEM_WORD_REQ | Fixed for this witem type |
| send_type | SINGLE | Point-to-point message |
| ident | 43 | (instr_ident + mem_tag + 1) % max_tags |
| tag | 0 | Memory tag being processed |
| element_index | 6 | dst_e (for ordered loads, unused for unordered) |
| ordered | false | Unordered load |
| parent_ident | 42 | Original instr_ident |

**Note:** Unlike WRITE_MEM_WORD_REQ which has 3 words (header + addr + data),
READ_MEM_WORD_REQ only has 2 words (header + addr). Data comes back in response.

### Build payload

```
payload[0] = addr   // KMAddr for VPU, ScalarAddr for scalar
```

## S14: Pass Through

Wait cycle for pipeline latency. Since LoadIndexedUnordered doesn't need a data RF read,
S14 passes through.

## S15: Send Packet

```
// Send header word
packetOut.valid = true
packetOut.bits.isHeader = true
packetOut.bits.data = header

// Wait for ready, then send addr word
packetOut.bits.isHeader = false
packetOut.bits.data = addr
```

## Response Handling (RxCh0)

### Receives READ_MEM_WORD_RESP

```
// Header contains: ident=43, tag=0, source_x=3, source_y=1
// Payload contains: data word from remote cache

// Compute parent ident
parent_ident = (ident - tag - 1) % max_response_tags
             = (43 - 0 - 1) % 128 = 42

entry = lookup_entry(parent_ident=42)
entry.transaction_states[tag] = COMPLETE

// Write received data to RF
// Shift and mask based on src_byte_in_word, dst_byte (tag), n_bytes
dst_reg = dst + dst_v = 0 + 0 = 0
rf_word = shift_and_merge(old_rf_word, response_data, src_byte_in_word, tag, n_bytes)
write_rf(dst_reg, rf_word)
```

### Error Path: DROP

If target can't handle the request:
```
// Receives READ_MEM_WORD_DROP
entry.transaction_states[tag] = NEED_TO_SEND  // will retry
```

## Two-Phase Synchronization

LoadIndexedUnordered uses synchronization to handle faults across kamlets.
Same as StoreStride.

### Phase 1: Fault Sync

After all tags leave INITIAL state (either NEED_TO_SEND, WAITING_IN_CASE_FAULT, or COMPLETE):
- Trigger fault sync with min_fault_element
- Wait for global_min_fault from sync network
- Tags in WAITING_IN_CASE_FAULT with dst_e >= global_min_fault → COMPLETE
- Tags in WAITING_IN_CASE_FAULT with dst_e < global_min_fault → NEED_TO_SEND

### Phase 2: Completion Sync

After all transaction_states == COMPLETE:
- Trigger completion sync
- When sync completes, witem is ready for finalization

## Completion

When all transaction_states == COMPLETE AND completion_sync_state == COMPLETE:

Signal `witemComplete.valid = true, witemComplete.bits = 42` to kamlet.

## Differences from StoreStride

| Aspect | LoadIndexedUnordered | StoreStride |
|--------|----------------------|-------------|
| Data direction | Memory → RF | RF → Memory |
| Address source | Index register (RF read) | Constant stride |
| Message type | READ_MEM_WORD_REQ | WRITE_MEM_WORD_REQ |
| Request payload | [header, addr] (2 words) | [header, addr, data] (3 words) |
| Response payload | [header, data] | [header] (just ACK) |
| RF read in pipeline | Index register (S4-S6) | Source data (S13-S15) |
| RF write | In RxCh0 (response handler) | None (DST handles via RxCh1) |
| TLB request type | Read (is_write=false) | Write (is_write=true) |
| RETRY message | No (use DROP + resend) | Yes |

## Differences from LoadJ2JWords

| Aspect | LoadIndexedUnordered | LoadJ2JWords |
|--------|----------------------|--------------|
| Address computation | Index register + base | Cache-relative |
| TLB needed | Yes | No |
| Participants | ONE jamlet (one element) | ALL jamlets |
| Tag iteration timing | S11-S12 (after TLB) | S11-S12 (no TLB) |
| Message type | READ_MEM_WORD_REQ | LOAD_J2J_WORDS_REQ |
| Data source | Remote cache (via request) | Local SRAM |
| Synchronization | Fault + completion sync | None |

## Pipeline Summary

```
S1: Select entry
S2: Request kamlet entry
S3: Receive kamlet response
S4: Compute element info, issue index RF read (+ mask RF read if enabled)
S5: Index/mask RF read wait
S6: Receive index/mask RF response
S7: Check mask, extract index value, compute source address
S8: Issue TLB request
S9: TLB wait
S10: Receive TLB response
S11-S12: Tag iteration with mem_ew (multi-cycle)
S13: Build READ_MEM_WORD_REQ packet
S14: Pass through
S15: Send packet (2 words: header + addr)

Response path (RxCh0):
- Receive READ_MEM_WORD_RESP with data
- Write data to RF
- Mark tag COMPLETE
```
