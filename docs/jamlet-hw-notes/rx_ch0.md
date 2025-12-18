# RxCh0 Design

## Overview

Receive handler for channel 0 (always-consumable responses). These messages don't require
sending responses - they just update local state.

## Messages Handled

| Message | SRAM | RF | State Update | To Kamlet |
|---------|------|----|--------------| ----------|
| READ_LINE_RESP | Write | - | - | cacheResponse |
| WRITE_LINE_RESP | - | - | - | cacheResponse |
| WRITE_LINE_READ_LINE_RESP | Write | - | - | cacheResponse |
| WRITE_LINE_READ_LINE_DROP | - | - | - | clear sent flag |
| LOAD_J2J_WORDS_RESP | - | - | src→COMPLETE | - |
| LOAD_J2J_WORDS_DROP | - | - | src→NEED_TO_SEND | - |
| LOAD_J2J_WORDS_RETRY | - | - | src→NEED_TO_SEND | - |
| STORE_J2J_WORDS_RESP | - | - | src→COMPLETE | - |
| STORE_J2J_WORDS_DROP | - | - | src→NEED_TO_SEND | - |
| STORE_J2J_WORDS_RETRY | - | - | src→NEED_TO_SEND | - |
| LOAD_WORD_RESP | - | - | src→COMPLETE | - |
| LOAD_WORD_DROP | - | - | src→NEED_TO_SEND | - |
| LOAD_WORD_RETRY | - | - | src→NEED_TO_SEND | - |
| STORE_WORD_RESP | - | - | src→COMPLETE | - |
| STORE_WORD_DROP | - | - | src→NEED_TO_SEND | - |
| STORE_WORD_RETRY | - | - | src→NEED_TO_SEND | - |
| READ_MEM_WORD_RESP | - | Write | src→COMPLETE | - |
| READ_MEM_WORD_DROP | - | - | src→NEED_TO_SEND | - |
| WRITE_MEM_WORD_RESP | - | - | src→COMPLETE | - |
| WRITE_MEM_WORD_DROP | - | - | src→NEED_TO_SEND | - |

## Interface

```
RxCh0:

  // From Router0
  ← packetIn          : Decoupled (packet words)

  // To/From SramArbiter (for READ_LINE_RESP)
  → sramReq           : Decoupled (addr + isWrite + writeData)
  ← sramResp          : Decoupled (readData)

  // To RfSlice (for READ_MEM_WORD_RESP)
  → rfWrite           : Valid + addr + writeData

  // To WitemTable (update protocol states)
  → updateSrcState    : Valid + instr_ident + tag + new_state

  // To Kamlet (cache line received)
  → cacheResponse     : Valid + ident
```

## Pipeline

6-stage pipeline to sustain line rate (one word per cycle):

```
S1 (Decode) → S2 (Issue) → S3 (Lookup 1) → S4 (Lookup 2) → S5 (Compute) → S6 (Execute)
```

**Stage 1: Receive + Decode**
- Accept word from router
- Decode type, extract fields

**Stage 2: Issue Lookup**
- Issue kamlet request (for messages needing it)

**Stage 3: Lookup 1**
- Kamlet lookup in progress (cycle 1 of 2)

**Stage 4: Lookup 2**
- Kamlet lookup completes, response arrives

**Stage 5: Compute**
- Compute RF addr, mask, SRAM addr from kamlet response + tag

**Stage 6: Execute**
- SRAM/RF write, state update

**Message context register** spans words of same message, carrying:
- msg_type, ident, tag
- kamlet response data
- computed addresses/masks

## Examples

### READ_MEM_WORD_RESP (header + 1 data word)

```
Cycle 1: S1=hdr   S2=-     S3=-     S4=-     S5=-     S6=-
Cycle 2: S1=data  S2=hdr   S3=-     S4=-     S5=-     S6=-     (issue req)
Cycle 3: S1=next  S2=data  S3=hdr   S4=-     S5=-     S6=-     (lookup 1)
Cycle 4: S1=...   S2=next  S3=data  S4=hdr   S5=-     S6=-     (lookup 2, resp)
Cycle 5: S1=...   S2=...   S3=next  S4=data  S5=hdr   S6=-     (compute)
Cycle 6: S1=...   S2=...   S3=...   S4=next  S5=data  S6=hdr
Cycle 7: S1=...   S2=...   S3=...   S4=...   S5=next  S6=data  (RF write)
```

### LOAD_J2J_WORDS_RESP (header only, state update)

```
Cycle 1: S1=hdr   S2=-     S3=-     S4=-     S5=-     S6=-
Cycle 2: S1=next  S2=hdr   S3=-     S4=-     S5=-     S6=-
...
Cycle 6: S1=...   S2=...   S3=...   S4=...   S5=...   S6=hdr   (state update)
```

### READ_LINE_RESP (header + N data words → SRAM)

```
Cycle 1: S1=hdr   S2=-     S3=-     S4=-     S5=-     S6=-
Cycle 2: S1=d0    S2=hdr   S3=-     S4=-     S5=-     S6=-
Cycle 3: S1=d1    S2=d0    S3=hdr   S4=-     S5=-     S6=-
...
Cycle 6: S1=d4    S2=d3    S3=d2    S4=d1    S5=d0    S6=hdr   (no exec)
Cycle 7: S1=d5    S2=d4    S3=d3    S4=d2    S5=d1    S6=d0    (SRAM write)
Cycle 8: S1=...   S2=d5    S3=d4    S4=d3    S5=d2    S6=d1    (SRAM write)
...
```
