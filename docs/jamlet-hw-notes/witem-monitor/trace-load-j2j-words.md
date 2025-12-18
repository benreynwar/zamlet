# Trace: LoadJ2JWords

Unaligned load where cache data transfers between jamlets via J2J messaging.
Each jamlet may be SRC (has cache data), DST (receives into RF), both, or neither for
different tags.

## Example Configuration

```
Lamlet geometry:
  k_cols = 2, k_rows = 2  (4 kamlets)
  j_cols = 2, j_rows = 2  (4 jamlets per kamlet)
  j_in_l = 16             (total jamlets in lamlet)

Memory parameters:
  word_bytes = 8          (64-bit words)
  vline_bytes = 128       (16 words per vline)
  cache_line_bytes = 256  (32 words, 2 vlines per cache slot)
  vlines_in_cache_line = 2

Word ordering: STANDARD
  vw_index = j_y * j_cols_total + j_x
  j_cols_total = j_cols * k_cols = 4

This jamlet: (2, 1)
  j_x = 2, j_y = 1
  mem_vw = 1 * 4 + 2 = 6
```

## Instruction Parameters (from kamletEntryResp)

```
instr_ident = 42
cache_slot = 3

Memory ordering (k_maddr.ordering):
  mem_ew = 32             (32-bit elements in memory)
  mem_word_order = STANDARD

Register ordering (dst_ordering):
  reg_ew = 32             (32-bit elements in register)
  reg_word_order = STANDARD

Transfer range:
  start_index = 0
  n_elements = 32

Base address calculation:
  k_maddr points to some offset within a cache line
  mem_base_addr.index = 0       (starting vline index)
  mem_base_addr.bit_addr = 64   (8-byte offset into first vline)
```

## Entry Creation

All tags initialized:
```
for tag in 0..7:
  protocol_states[tag].src_state = INITIAL
  protocol_states[tag].dst_state = WAITING_FOR_REQUEST
```

**Note:** In the hardware implementation, each jamlet has its own array of protocol states
(word_bytes entries). This differs from the Python model where protocol states are combined
at the kamlet level with `j_in_k * word_bytes` entries indexed by `j_in_k_index * word_bytes + tag`.

## S1-S3: Entry Selection and Kamlet Lookup

**S1**: Entry selected (oldest entry where `valid && ready_for_s1`)
**S2**: Send kamletEntryReq with instr_ident=42
**S3**: Receive kamletEntryResp with instruction parameters above

## S4-S10: Pass Through

LoadJ2JWords does not use TLB or mask/index RF reads, so S4-S10 pass through.
Pipeline registers carry instruction parameters forward to S11.

## Pipeline Register Summary

Values passed between pipeline stages:

```
S10 -> S11:
    instr_ident         : UInt     // instruction identifier
    cache_slot          : UInt     // which cache slot holds the data
    mem_ew              : UInt     // memory element width (bits)
    reg_ew              : UInt     // register element width (bits)
    base_bit_addr       : UInt     // bit offset within vline (mem_base_addr.bit_addr)
    base_index          : UInt     // starting vline index (mem_base_addr.index)
    start_index         : UInt     // first element index in transfer
    n_elements          : UInt     // number of elements to transfer

S11 -> S12:
    instr_ident         : UInt
    cache_slot          : UInt
    mem_tag             : UInt     // byte position in this jamlet's cache word (0-7)
    startRegVline       : UInt     // first register vline for this tag
    endRegVline         : UInt     // last register vline for this tag
    mem_v_offset        : UInt     // 0 or 1, added to reg_v for SRAM address
    reg_bit_addr        : UInt     // bit address in register space (for reg_tag calc)
    (also: parameters from S10 needed for computeMemTagTarget)

S12 -> S13:
    instr_ident         : UInt
    cache_slot          : UInt
    mem_tag             : UInt
    reg_tag             : UInt     // byte position in DST's RF word (computed from reg_bit_addr)
    reg_v               : UInt     // current register vline being processed
    mem_v_offset        : UInt
    target_x            : UInt     // DST jamlet X coordinate
    target_y            : UInt     // DST jamlet Y coordinate
    nVlines             : UInt     // total vlines for this tag (for header.length)
    base_index          : UInt     // for SRAM address calculation

S13 -> S14:
    instr_ident         : UInt
    cache_slot          : UInt
    mem_tag             : UInt
    reg_tag             : UInt
    target_x            : UInt
    target_y            : UInt
    nVlines             : UInt
    sram_addr           : UInt     // computed SRAM address for read

S14 -> S15:
    instr_ident         : UInt
    mem_tag             : UInt
    reg_tag             : UInt
    target_x            : UInt
    target_y            : UInt
    nVlines             : UInt
    sram_read_data      : UInt     // 64-bit word read from SRAM
```

## S11: Tag Iteration - Bounds

S11 iterates over tags to determine which ones this jamlet participates in. Rather than
precomputing bitmask vectors, we call `computeMemTagBounds()` starting at tag=0, advance
by nBytes, and repeat until tag >= word_bytes. For each active tag, S12 calls
`computeMemTagTarget()` for each vline.

### Function: computeMemTagBounds(mem_tag)

Given a memory tag (byte position in this jamlet's cache word), determine if this tag is
active across any vline, how many bytes this mapping covers (for skipping inactive tags),
and the register vline range.

```
function computeMemTagBounds(
    mem_tag,
    mem_ew, reg_ew, j_in_l, mem_vw,
    base_bit_addr,   // mem_base_addr.bit_addr - bit offset within vline
    start_index, n_elements, elements_per_vline
) -> (tagActive, nBytes, startRegVline, endRegVline, mem_v_offset):

    // Memory side position
    mem_wb = mem_tag * 8
    mem_eb = mem_wb % mem_ew
    mem_ve = (mem_wb / mem_ew) * j_in_l + mem_vw
    mem_bit_addr_in_vline = mem_ve * mem_ew + mem_eb

    // Register side position (subtraction to convert mem->reg address space)
    reg_bit_addr = mem_bit_addr_in_vline - base_bit_addr
    reg_eb = reg_bit_addr % reg_ew
    reg_vw = (reg_bit_addr / reg_ew) % j_in_l

    // Bytes covered by this mapping (until we hit an element boundary on either side)
    nBytes = min(mem_ew - mem_eb, reg_ew - reg_eb) / 8

    // Register vline range
    reg_ve = (reg_bit_addr / reg_ew / j_in_l) * j_in_l + reg_vw
    startRegVline = start_index / elements_per_vline
    endRegVline = (start_index + n_elements - 1) / elements_per_vline

    // Check if any vline is in range
    first_element = reg_ve + startRegVline * elements_per_vline
    last_element = reg_ve + endRegVline * elements_per_vline
    tagActive = (first_element < start_index + n_elements) && (last_element >= start_index)

    // Memory vline offset: if mem position < base within vline, we're in next vline
    // Used to compute mem_v = base_index + reg_v + mem_v_offset for SRAM access
    mem_v_offset = (mem_bit_addr_in_vline < base_bit_addr) ? 1 : 0

    return (tagActive, nBytes, startRegVline, endRegVline, mem_v_offset)
```

**Usage:** Start with mem_tag=0, call the function, advance by nBytes. Repeat until
mem_tag >= word_bytes.

### Function: computeMemTagTarget(mem_tag, reg_v)

Given a memory tag and a specific register vline, get the target register word and whether
this specific tag+vline combination is active.

```
function computeMemTagTarget(
    mem_tag, reg_v,
    mem_ew, reg_ew, j_in_l, mem_vw, base_bit_addr,
    start_index, n_elements, elements_per_vline
) -> (active, targetVw):

    // Memory side position
    mem_wb = mem_tag * 8
    mem_eb = mem_wb % mem_ew
    mem_ve = (mem_wb / mem_ew) * j_in_l + mem_vw
    mem_bit_addr_in_vline = mem_ve * mem_ew + mem_eb

    // Register side position
    reg_bit_addr = mem_bit_addr_in_vline - base_bit_addr
    reg_eb = reg_bit_addr % reg_ew
    reg_vw = (reg_bit_addr / reg_ew) % j_in_l

    // Range check for this specific vline
    reg_ve = (reg_bit_addr / reg_ew / j_in_l) * j_in_l + reg_vw
    element_index = reg_ve + reg_v * elements_per_vline
    active = (start_index <= element_index) && (element_index < start_index + n_elements)

    targetVw = reg_vw

    return (active, targetVw)
```

### Function: computeRegTagBounds(reg_tag)

Given a register tag (byte position in this jamlet's RF word), determine if this tag is
active across any vline, how many bytes this mapping covers, and the vline range.

```
function computeRegTagBounds(
    reg_tag,
    mem_ew, reg_ew, j_in_l, reg_vw, base_bit_addr,
    start_index, n_elements, elements_per_vline
) -> (tagActive, nBytes, startVline, endVline):

    // Register side position
    reg_wb = reg_tag * 8
    reg_eb = reg_wb % reg_ew
    reg_ve = (reg_wb / reg_ew) * j_in_l + reg_vw
    reg_bit_addr_in_vline = reg_ve * reg_ew + reg_eb

    // Memory side position (addition to convert reg->mem address space)
    mem_bit_addr_in_vline = reg_bit_addr_in_vline + base_bit_addr
    mem_eb = mem_bit_addr_in_vline % mem_ew

    // Bytes covered by this mapping
    nBytes = min(mem_ew - mem_eb, reg_ew - reg_eb) / 8

    // Vline range
    startVline = start_index / elements_per_vline
    endVline = (start_index + n_elements - 1) / elements_per_vline

    // Check if any vline is in range
    first_element = reg_ve + startVline * elements_per_vline
    last_element = reg_ve + endVline * elements_per_vline
    tagActive = (first_element < start_index + n_elements) && (last_element >= start_index)

    return (tagActive, nBytes, startVline, endVline)
```

### Function: computeRegTagTarget(reg_tag, vline)

Given a register tag and a specific vline, get the source memory word and whether this
specific tag+vline combination is active.

```
function computeRegTagTarget(
    reg_tag, vline,
    mem_ew, reg_ew, j_in_l, reg_vw, base_bit_addr,
    start_index, n_elements, elements_per_vline
) -> (active, sourceVw):

    // Register side position
    reg_wb = reg_tag * 8
    reg_eb = reg_wb % reg_ew
    reg_ve = (reg_wb / reg_ew) * j_in_l + reg_vw
    reg_bit_addr_in_vline = reg_ve * reg_ew + reg_eb

    // Memory side position
    mem_bit_addr_in_vline = reg_bit_addr_in_vline + base_bit_addr
    mem_vw = (mem_bit_addr_in_vline / mem_ew) % j_in_l

    // Range check for this specific vline
    element_index = reg_ve + vline * elements_per_vline
    active = (start_index <= element_index) && (element_index < start_index + n_elements)

    sourceVw = mem_vw

    return (active, sourceVw)
```

### Instruction-level setup

```
// This jamlet's position in the memory word order
mem_vw = j_coords_to_vw_index(STANDARD, j_x=2, j_y=1) = 1*4 + 2 = 6

// Vline range for this transfer (register-side)
reg_elements_in_vline = vline_bytes * 8 / reg_ew = 128 * 8 / 32 = 32
start_vline = start_index / reg_elements_in_vline = 0 / 32 = 0
end_vline = (start_index + n_elements - 1) / reg_elements_in_vline = 31 / 32 = 0

// Base address info
base_index = mem_base_addr.index = 0
base_bit_addr = mem_base_addr.bit_addr = 64
```

### Example: Iterating memory tags

For LoadJ2JWords, iterate over memory tags (bytes in the cache word) using
`computeMemTagBounds()`. Each cycle processes one active tag and batch-completes the
skipped tags up to (tag + nBytes - 1).

**Cycle 1: computeMemTagBounds(mem_tag=0)**
```
mem_wb = 0 * 8 = 0
mem_eb = 0 % 32 = 0
mem_ve = (0 / 32) * 16 + 6 = 6
mem_bit_addr_in_vline = 6 * 32 + 0 = 192

reg_bit_addr = 192 - 64 = 128
reg_eb = 128 % 32 = 0
reg_vw = (128 / 32) % 16 = 4

nBytes = min(32 - 0, 32 - 0) / 8 = 4

reg_ve = (128 / 32 / 16) * 16 + 4 = 4
startRegVline = 0 / 32 = 0
endRegVline = (0 + 32 - 1) / 32 = 0

first_element = 4 + 0 * 32 = 4
last_element = 4 + 0 * 32 = 4
tagActive = (4 < 32) && (4 >= 0) = true

mem_v_offset = (192 < 64) ? 1 : 0 = 0

-> (tagActive=true, nBytes=4, startRegVline=0, endRegVline=0, mem_v_offset=0)
```

- Tag 0 is active, pass (tag=0, startRegVline=0, endRegVline=0, mem_v_offset=0) to S12
- Batch-complete tags 1, 2, 3 (set src_state = COMPLETE)
- Advance to tag 0 + 4 = 4

**Cycle 2: computeMemTagBounds(mem_tag=4)**
```
mem_wb = 4 * 8 = 32
mem_eb = 32 % 32 = 0
mem_ve = (32 / 32) * 16 + 6 = 22
mem_bit_addr_in_vline = 22 * 32 + 0 = 704

reg_bit_addr = 704 - 64 = 640
reg_eb = 640 % 32 = 0
reg_vw = (640 / 32) % 16 = 4

nBytes = min(32 - 0, 32 - 0) / 8 = 4

reg_ve = (640 / 32 / 16) * 16 + 4 = 20
startRegVline = 0 / 32 = 0
endRegVline = (0 + 32 - 1) / 32 = 0

first_element = 20 + 0 * 32 = 20
last_element = 20 + 0 * 32 = 20
tagActive = (20 < 32) && (20 >= 0) = true

mem_v_offset = (704 < 64) ? 1 : 0 = 0

-> (tagActive=true, nBytes=4, startRegVline=0, endRegVline=0, mem_v_offset=0)
```

- Tag 4 is active, pass (tag=4, startRegVline=0, endRegVline=0, mem_v_offset=0) to S12
- Batch-complete tags 5, 6, 7 (set src_state = COMPLETE)
- Advance to tag 4 + 4 = 8, which is >= word_bytes, so done with send tags

### Iterating register tags (receive side)

After send tags, iterate register tags using `computeRegTagBounds()` to batch-complete
dst_state for tags where this jamlet doesn't receive.

For this jamlet (j_x=2, j_y=1), reg_vw = 6. The register-side iteration determines which
RF bytes will receive data from other jamlets.

**Cycle 1: computeRegTagBounds(reg_tag=0)**
```
reg_wb = 0 * 8 = 0
reg_eb = 0 % 32 = 0
reg_ve = (0 / 32) * 16 + 6 = 6
reg_bit_addr_in_vline = 6 * 32 + 0 = 192

mem_bit_addr_in_vline = 192 + 64 = 256
mem_eb = 256 % 32 = 0

nBytes = min(32 - 0, 32 - 0) / 8 = 4

first_element = 6 + 0 * 32 = 6
tagActive = (6 < 32) && (6 >= 0) = true

-> (tagActive=true, nBytes=4, startVline=0, endVline=0)
```

- Tag 0 is active (this jamlet receives for this tag), keep dst_state[0] = WAITING_FOR_REQUEST
- Batch-complete tags 1, 2, 3 (set dst_state = COMPLETE, covered by tag 0's message)
- Advance to tag 0 + 4 = 4

**Cycle 2: computeRegTagBounds(reg_tag=4)**
```
reg_wb = 4 * 8 = 32
reg_eb = 32 % 32 = 0
reg_ve = (32 / 32) * 16 + 6 = 22
reg_bit_addr_in_vline = 22 * 32 + 0 = 704

mem_bit_addr_in_vline = 704 + 64 = 768
mem_eb = 768 % 32 = 0

nBytes = min(32 - 0, 32 - 0) / 8 = 4

first_element = 22 + 0 * 32 = 22
tagActive = (22 < 32) && (22 >= 0) = true

-> (tagActive=true, nBytes=4, startVline=0, endVline=0)
```

- Tag 4 is active (this jamlet receives for this tag), keep dst_state[4] = WAITING_FOR_REQUEST
- Batch-complete tags 5, 6, 7 (set dst_state = COMPLETE, covered by tag 4's message)
- Advance to tag 4 + 4 = 8, done with receive tags

**State after both iterations:**

| Tag | src_state | dst_state |
|-----|-----------|-----------|
| 0 | INITIAL | WAITING_FOR_REQUEST |
| 1 | COMPLETE | COMPLETE |
| 2 | COMPLETE | COMPLETE |
| 3 | COMPLETE | COMPLETE |
| 4 | INITIAL | WAITING_FOR_REQUEST |
| 5-7 | COMPLETE | COMPLETE |

Note: In this example, both memory tags (0, 4) and register tags (0, 4) are active for
this jamlet. Tags 0 and 4 are the "lead" tags for each element - they carry the data for
the covered bytes (1-3 and 5-7 respectively).

## S12: Tag Iteration - Emit (Vline Iteration)

S12 receives (tag, startRegVline, endRegVline, mem_v_offset) from S11 and iterates over
register vlines, calling `computeMemTagTarget()` for each one.

**Processing tag 0 (startRegVline=0, endRegVline=0, mem_v_offset=0):**

First, set src_state[0] = WAITING_FOR_RESPONSE.

**Call computeMemTagTarget(mem_tag=0, reg_v=0):**
```
// Recompute memory/register positions (same as computeMemTagBounds)
mem_bit_addr_in_vline = 192
reg_bit_addr = 128
reg_vw = (128 / 32) % 16 = 4

// Range check for reg_v=0
reg_ve = 4
element_index = 4 + 0 * 32 = 4
active = (0 <= 4) && (4 < 32) = true

targetVw = 4

-> (active=true, targetVw=4)
```

This vline is active. Compute target coordinates from targetVw:
```
target_x, target_y = vw_index_to_j_coords(STANDARD, targetVw=4)
  target_x = 4 % j_cols_total = 4 % 4 = 0
  target_y = 4 / j_cols_total = 4 / 4 = 1
```

Pass (reg_v=0, target_x=0, target_y=1, active=true) to S13.

For multi-vline transfers (startRegVline != endRegVline), S12 iterates:
```
nVlines = endRegVline - startRegVline + 1   // travels down pipeline for header.length

for reg_v in startRegVline..endRegVline:
    (active, targetVw) = computeMemTagTarget(tag, reg_v, ...)
    if active:
        pass (reg_v, targetVw, active) to S13
```

## S13: Data Read Issue + Build Header

S13 computes the SRAM address and issues the read request.

```
mem_v = base_index + reg_v + mem_v_offset
      = 0 + 0 + 0 = 0

cache_base_addr = cache_slot * vlines_in_cache_line * word_bytes
                = 3 * 2 * 8 = 48

vline_offset_in_cache = mem_v % vlines_in_cache_line = 0 % 2 = 0
sram_addr = cache_base_addr + vline_offset_in_cache * word_bytes
          = 48 + 0 * 8 = 48

// Issue SRAM read request
sramReq.valid = true
sramReq.addr = sram_addr
sramReq.isWrite = false
```

## S14: Data Read Wait

Wait cycle for SRAM read latency. Pass-through stage when `s13_s14_forward_buf` is disabled.

## S15: Data Response + Send Packet

S15 receives the SRAM response, assembles the header, and sends the packet.

```
sram_read_data = sramResp.readData   (64-bit word from SRAM[48])
payload_words = [sram_read_data]     // one word for single-vline
num_payload_words = 1
```

The header is built from values computed in earlier stages and passed down the pipeline.

### Build TaggedHeader

| Field | Value | Source |
|-------|-------|--------|
| target_x | 0 | From S5 (computed from targetVw) |
| target_y | 1 | From S5 (computed from targetVw) |
| source_x | 2 | thisX (this jamlet's X coordinate) |
| source_y | 1 | thisY (this jamlet's Y coordinate) |
| length | 2 | 1 (header) + 1 (data word) |
| message_type | LOAD_J2J_WORDS_REQ (16) | Fixed for this witem type |
| send_type | SINGLE (0) | Point-to-point message |
| ident | 42 | instr_ident from kamletEntryResp |
| mem_tag | 0 | Memory tag being processed (byte in SRC's word) |
| reg_tag | 0 | Register tag at DST (byte in DST's word) |

**Note:** The hardware header includes both `mem_tag` and `reg_tag`. This differs from the Python
model which only sends `mem_tag` (as `tag`) and has DST recompute `reg_wb` from the mapping.
The hardware optimization avoids recomputation at DST.

**Computing reg_tag:** From `computeMemTagTarget`, we have `reg_bit_addr`. The register tag is:
```
reg_eb = reg_bit_addr % reg_ew = 128 % 32 = 0
reg_we = reg_bit_addr / reg_ew / j_in_l = 128 / 32 / 16 = 0
reg_wb = reg_we * reg_ew + reg_eb = 0 * 32 + 0 = 0
reg_tag = reg_wb / 8 = 0
```

### Build payload

```
payload[0] = sram_read_data   // 64-bit word read from SRAM
```

### Multi-vline transfers

If the mapping spans multiple vlines (start_vline != end_vline), `get_mapping_from_mem()`
returns one mapping per vline. Each mapping requires a separate SRAM read, and all data
words are included in the packet:

```
header.length = 1 + num_vlines_with_mappings
payload[0] = sram_data_from_vline_0
payload[1] = sram_data_from_vline_1
...
```

### Send Packet

```
packetOut.valid = true
packetOut.bits.header = header
packetOut.bits.payload = payload

// Wait for packetOut.ready (backpressure from arbiter)
// When ready, packet is sent to network
```

## Pipeline Flow: Multiple Tags in Flight

The pipeline is fully pipelined - S11 emits a new tag each cycle (when not stalled by
backpressure or multi-vline iteration). Multiple tags can be in flight simultaneously.

**Cycle N:** S11 emits tag 0 → S12
**Cycle N+1:** S11 emits tag 4 → S12, while tag 0 is in S13
**Cycle N+2:** Tag 4 in S13, tag 0 in S14
... and so on

For tag 4:
```
src_state[4] = WAITING_FOR_RESPONSE
S11 emits to S12:
  tag = 4
  startRegVline = 0, endRegVline = 0, mem_v_offset = 0
```

Tag 4 flows through S12-S15 with:
- Same target jamlet (0, 1) - both tags map to same DST in this example
- `header.mem_tag = 4`, `header.reg_tag = 4`

**Stall conditions:**
- S12 needs multiple cycles for multi-vline iteration (endRegVline > startRegVline)
- Backpressure from downstream (S15 arbiter not ready)

## Response Handling (Outside WitemMonitor)

The following sections describe how other modules handle the protocol messages.
WitemMonitor only handles the SRC-side send path (S1-S15 above).

### RxCh1: Receives LOAD_J2J_WORDS_REQ at DST jamlet (0,1)

RxCh1 handles incoming REQ packets. This happens at the destination jamlet, not the
source jamlet that ran the WitemMonitor pipeline above.

```
// Extract from header: ident=42, mem_tag=0, reg_tag=0, source_x=2, source_y=1
// Payload contains the data word

entry = lookup_entry(ident=42)

// Check mask (if this is a masked operation)
// For loads, mask bits are at DST - SRC sends data regardless of mask
if entry.mask_enabled:
    // Compute element index for this reg_tag
    reg_ve = ...  // from mapping
    element_index = reg_ve + reg_v * elements_per_vline

    // Extract mask bit from local RF
    mask_word_index = element_index / (word_bytes * 8)
    mask_bit_position = element_index % (word_bytes * 8)
    mask_word = rf_read(mask_reg + mask_word_index)
    mask_bit = (mask_word >> mask_bit_position) & 1

    if mask_bit == 0:
        // Element is masked out - skip RF write but complete protocol
        goto complete_protocol

// Compute where to write in RF using get_mapping_from_mem with source coords:
mappings = get_mapping_from_mem(mem_wb=mem_tag*8, mem_x=source_x, mem_y=source_y)

for each mapping:
  shift = mapping.mem_wb - mapping.reg_wb
  byte_mask = ((1 << mapping.n_bits) - 1) << mapping.reg_wb
  dst_reg = base_reg + mapping.reg_v

  // Apply shift and mask to write data to RF
  rf_write(dst_reg, payload_word, shift, byte_mask)

complete_protocol:
// Update protocol state using reg_tag from header
response_tag = j_in_k_index * word_bytes + reg_tag
             = 0 * 8 + 0 = 0
entry.protocol_states[response_tag].dst_state = COMPLETE

// Send response (include both tags for SRC to identify which one completed)
// Response is sent regardless of mask - protocol must complete
send LOAD_J2J_WORDS_RESP to (source_x=2, source_y=1) with ident=42, mem_tag=0, reg_tag=0
```

### RxCh0: Receives LOAD_J2J_WORDS_RESP at SRC jamlet (2,1)

RxCh0 handles incoming RESP packets. This happens back at the source jamlet.

```
// Header contains: ident=42, mem_tag=0, reg_tag=0, source_x=0, source_y=1
entry = lookup_entry(ident=42)

// Use mem_tag to update src_state (SRC tracks by memory tag)
src_response_tag = j_in_k_index * word_bytes + mem_tag
                 = 0 * 8 + 0 = 0
entry.protocol_states[src_response_tag].src_state = COMPLETE
```

### Error Path: DROP (Entry Not Ready at DST)

If DST receives a REQ but the entry doesn't exist yet (witem not created), DST sends
a DROP instead of processing the request. This can happen due to message reordering
or timing differences in entry creation.

**Note:** RETRY is not used for loads (only DROP with SRC retry). RETRY only makes sense for
stores where DST can request a resend after cache becomes ready.

**RxCh1 at DST: Entry not found**
```
entry = lookup_entry(ident=42)
if entry is None:
    // Entry not ready - send DROP
    send LOAD_J2J_WORDS_DROP to (source_x, source_y) with ident, mem_tag, reg_tag
    return
```

**RxCh0 at SRC: Receives DROP**
```
// Header contains: ident=42, mem_tag=0, source_x=0, source_y=1
entry = lookup_entry(ident=42)

// Reset src_state to retry
src_response_tag = j_in_k_index * word_bytes + mem_tag
entry.protocol_states[src_response_tag].src_state = NEED_TO_SEND
```

SRC will retry sending the REQ on a subsequent iteration through the WitemMonitor pipeline.

## Completion

When all tags have:
- `src_state == COMPLETE`
- `dst_state == COMPLETE`

Signal `witemComplete.valid = true, witemComplete.bits = 42` to kamlet.
