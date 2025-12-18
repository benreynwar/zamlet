# CacheLineSender Design

## Overview

Handles `sendCacheLine` command from kamlet - reads SRAM and builds cache line packet.

## Interface

```
CacheLineSender:

  // From Kamlet
  ← sendCacheLine     : Valid + slot + ident + is_write_read

  // To/From SramArbiter
  → sramReq           : Decoupled (addr + isWrite=false)
  ← sramResp          : Decoupled (readData)

  // To Ch1Arbiter
  → packetOut         : Decoupled (packet)
```

## Operation

1. Receive sendCacheLine command (slot, ident, is_write_read)
2. Compute SRAM base address from slot
3. Read N words from SRAM (N = cache_line_bytes / j_in_k / word_bytes)
4. Build WRITE_LINE_READ_LINE packet: header + write_addr + read_addr + data words
5. Send via Ch1Arbiter
