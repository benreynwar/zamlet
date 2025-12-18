# Trace: StoreWordSrc

Partial word store that crosses cache line boundaries between kamlets. Data flows from a
SRC jamlet (which has the register) to a DST jamlet in a different kamlet (which has the
cache line to write).

**Key characteristic:** Point-to-point transfer. Only ONE jamlet in the SRC kamlet participates
(the one specified by `instr.src.k_index` and `instr.src.j_in_k_index`). All other jamlets in
the kamlet immediately complete.

**Note:** This is the SRC side only. DST side is handled by WaitingStoreWordDst (separate witem
with instr_ident + 1), processed by RxCh1.

## Example Configuration

```
Lamlet geometry:
  k_cols = 2, k_rows = 2  (4 kamlets)
  j_cols = 2, j_rows = 2  (4 jamlets per kamlet)
  j_in_k = 4              (jamlets per kamlet)

Memory parameters:
  word_bytes = 8          (64-bit words)

This jamlet: (2, 1)
  k_index = 1             (kamlet at col=1, row=0)
  j_in_k_index = 2        (jamlet within kamlet)
```

## Instruction Parameters (from kamletEntryResp)

```
instr_ident = 42

Source (register):
  src.k_index = 1
  src.j_in_k_index = 2    (this jamlet is the SRC!)
  src.reg = 5
  src.offset_in_word = 2  (bytes 2-5 of the word)

Destination (cache):
  dst.k_index = 2         (different kamlet)
  dst.j_in_k_index = 0
  dst.bit_addr = ...
  dst.addr = ...

byte_mask = 0x3C          (bytes 2,3,4,5 = bits 00111100)
```

## Entry Creation

Protocol states initialized:
```
for j in 0..j_in_k-1:
  if j == src.j_in_k_index:  // j == 2
    protocol_states[j] = NEED_TO_SEND
  else:
    protocol_states[j] = COMPLETE
```

Only jamlet j_in_k_index=2 has work to do. All others are COMPLETE from the start.

**Note:** StoreWordSrc only has SRC-side state. There is no dst_state because the receiving
jamlet handles writes via WaitingStoreWordDst (separate witem).

## S1-S3: Entry Selection and Kamlet Lookup

**S1**: Entry selected (oldest entry where `valid && ready_for_s1`)

**S2**: Send kamletEntryReq with instr_ident=42

**S3**: Receive kamletEntryResp with instruction parameters

## Pipeline Register Summary

```
S3 -> S4:
    instr_ident         : UInt     // instruction identifier
    src_k_index         : UInt     // which kamlet has the source register
    src_j_in_k_index    : UInt     // which jamlet within that kamlet
    src_reg             : UInt     // register number
    dst_k_index         : UInt     // which kamlet has the destination cache
    dst_j_in_k_index    : UInt     // which jamlet within that kamlet
    byte_mask           : UInt     // which bytes to write

S4 -> S5:
    instr_ident         : UInt
    is_active           : Bool     // true if this jamlet is the SRC
    target_x            : UInt     // DST jamlet X coordinate
    target_y            : UInt     // DST jamlet Y coordinate
    src_reg             : UInt
    byte_mask           : UInt

S12 -> S13:
    instr_ident         : UInt
    is_active           : Bool
    target_x            : UInt
    target_y            : UInt
    src_reg             : UInt
    byte_mask           : UInt

S13 -> S14:
    instr_ident         : UInt
    target_x            : UInt
    target_y            : UInt
    byte_mask           : UInt
    (RF read issued for src_reg)

S14 -> S15:
    instr_ident         : UInt
    target_x            : UInt
    target_y            : UInt
    byte_mask           : UInt
    rf_word             : UInt     // 64-bit word read from RF
```

## S4: Check Active Jamlet

S4 determines if this jamlet is the SRC for this instruction. This is a simple comparison,
not an iteration.

```
is_active = (this_k_index == src_k_index) && (this_j_in_k_index == src_j_in_k_index)
          = (1 == 1) && (2 == 2)
          = true
```

If not active, the entry is already COMPLETE (from initialization) and no further processing
is needed. Pipeline can skip to next entry.

Compute target coordinates from dst indices:
```
target_x, target_y = k_indices_to_j_coords(dst_k_index=2, dst_j_in_k_index=0)
// Assuming kamlet 2 is at (0, 1) in kamlet grid:
// target_x = 0 * j_cols + 0 = 0
// target_y = 1 * j_rows + 0 = 2
// So target is jamlet (0, 2)
```

Pass (is_active=true, target_x=0, target_y=2, src_reg=5, byte_mask=0x3C) to S5.

## S5-S12: Pass Through

StoreWordSrc does not use mask/index RF reads, TLB, or tag iteration, so S5-S12 pass
through. Pipeline registers carry instruction parameters forward to S13.

## S13: Issue RF Read + Build Header

If is_active, issue RF read for the source word.

```
rf_addr = src_reg * word_bytes = 5 * 8 = 40

rfReq.valid = is_active
rfReq.addr = rf_addr
rfReq.isWrite = false
```

Set protocol state:
```
protocol_states[this_j_in_k_index] = WAITING_FOR_RESPONSE
```

## S14: RF Read Wait

Wait cycle for RF read latency. Pass-through stage when `s13_s14_forward_buf` is disabled.

## S15: RF Response + Build Packet + Send

S15 receives the RF response, builds the packet, and sends it.

```
rf_word = rfResp.readData   // 64-bit word from RF[40:48]
```

### Build TaggedHeader

| Field | Value | Source |
|-------|-------|--------|
| target_x | 0 | From S4 (computed from dst indices) |
| target_y | 2 | From S4 (computed from dst indices) |
| source_x | 2 | thisX (this jamlet's X coordinate) |
| source_y | 1 | thisY (this jamlet's Y coordinate) |
| length | 2 | 1 (header) + 1 (data word) |
| message_type | STORE_WORD_REQ | Fixed for this witem type |
| send_type | SINGLE | Point-to-point message |
| ident | 42 | instr_ident |
| tag | 0 | Always 0 for StoreWord |

**Note:** Unlike LoadJ2JWords which has multiple tags (one per byte), StoreWord always uses
tag=0. The byte_mask in the instruction tells DST which bytes to actually write.

### Build payload

```
payload[0] = rf_word   // 64-bit word read from RF
```

### Send Packet

```
// Send header word
packetOut.valid = true
packetOut.bits.isHeader = true
packetOut.bits.data = header

// Wait for ready, then send data word
packetOut.bits.isHeader = false
packetOut.bits.data = rf_word
```

## Response Handling (RxCh0)

### Receives STORE_WORD_RESP

```
// Header contains: ident=42, tag=0
entry = lookup_entry(ident=42)
protocol_states[this_j_in_k_index] = COMPLETE
```

### Error Path: STORE_WORD_DROP

If DST doesn't have the witem entry yet:
```
// Receives STORE_WORD_DROP
protocol_states[this_j_in_k_index] = NEED_TO_SEND  // will retry
```

### Error Path: STORE_WORD_RETRY

If DST had to wait for cache but is now ready:
```
// Receives STORE_WORD_RETRY
protocol_states[this_j_in_k_index] = NEED_TO_SEND  // resend
```

## Completion

When protocol_states[this_j_in_k_index] == COMPLETE (for the active jamlet):

Signal `witemComplete.valid = true, witemComplete.bits = 42` to kamlet.

## Differences from Other Witem Types

| Aspect | StoreWordSrc | LoadJ2JWords | StoreStride |
|--------|--------------|--------------|-------------|
| Participants | ONE jamlet | ALL jamlets (word_bytes tags each) | ONE jamlet (one element) |
| Tag count | 1 (always 0) | word_bytes | word_bytes (but only element's bytes active) |
| Tag iteration | None | S11-S12 iterates tags | S11-S12 iterates tags |
| TLB needed | No | No | Yes |
| Target | Known from instr | Computed per tag | Computed from TLB |
| SRAM access | None | Read | None |
| RF access | Read (S13) | None (writes at DST) | Read (S13) |
| Data source | RF | SRAM (cache) | RF |
| Vline iteration | None | S12 iterates vlines | None |
| RETRY message | Yes | No | Yes |
| Synchronization | None | None | Fault sync + completion sync |

## Pipeline Utilization

StoreWordSrc is the simplest protocol witem type:

```
S1: Select entry
S2: Request kamlet entry
S3: Receive kamlet response
S4: Check if active, compute target (single cycle)
S5-S12: Pass through
S13: Issue RF read (single cycle)
S14: RF read wait (single cycle)
S15: RF response + build packet + send packet (multiple cycles: header + data)
```

Total: ~15 cycles for active jamlet, ~4 cycles for inactive jamlets (S1-S4 then done).
