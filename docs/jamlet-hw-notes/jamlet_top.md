# Jamlet Top-Level Module

## Overview

Jamlet is the top-level module for a single lane of the VPU. It contains routers, SRAM,
register file slice, and the witem processing logic.

## Block Diagram

```
                              ┌─────────────────────────────────────────────┐
                              │                  Jamlet                      │
                              │                                              │
   thisX, thisY ─────────────►│ position                                     │
                              │                                              │
   ══════════════════════════ │ ══════ Channel 0 Network ═══════════════════ │
   n0i, s0i, e0i, w0i ◄══════►│                            ◄═══════════════► n0o, s0o, e0o, w0o
                              │                                              │
   ══════════════════════════ │ ══════ Channel 1 Network ═══════════════════ │
   n1i, s1i, e1i, w1i ◄══════►│                            ◄═══════════════► n1o, s1o, e1o, w1o
                              │                                              │
   ══════════════════════════ │ ══════ Instruction Interface ════════════════ │
                              │                                              │
   instruction ─────────────►│ Valid: witem or ALU instruction              │
                              │   - instr_type (witem_create, alu_op, ...)   │
                              │   - instr_ident                              │
                              │   - (witem fields or ALU fields)             │
                              │                                              │
   witemCacheAvail ──────────►│ Valid: cache became ready                    │
                              │   - instr_ident                              │
                              │                                              │
   witemRemove ──────────────►│ Valid: delete witem entry                    │
                              │   - instr_ident                              │
                              │                                              │
   witemComplete ◄────────────│ Valid: all tags finished                     │
                              │   - instr_ident                              │
                              │                                              │
   ══════════════════════════ │ ══════ Cache Slot Interface ════════════════ │
                              │                                              │
   cacheSlotReq ◄─────────────│ Valid: jamlet needs a cache slot             │
                              │   - k_maddr, is_write                        │
                              │   - instr_ident, source (x, y)               │
                              │                                              │
   cacheSlotResp ────────────►│ Valid: kamlet responds with slot             │
                              │   - instr_ident, source (x, y)               │
                              │   - slot, cache_is_avail                     │
                              │                                              │
   cacheStateUpdate ◄─────────│ Valid: slot modified                         │
                              │   - slot                                     │
                              │                                              │
   ══════════════════════════ │ ══════ TLB Interface ═════════════════════ │
                              │                                              │
   tlbReq ◄──────────────────│ Valid: translation request (strided/indexed) │
                              │   - vaddr                                    │
                              │                                              │
   tlbResp ─────────────────►│ Valid: translation response                  │
                              │   - paddr, error                             │
                              │                                              │
   ══════════════════════════ │ ══════ Cache Line Interface ════════════════ │
                              │                                              │
   sendCacheLine ────────────►│ Valid: send SRAM data to memlet              │
                              │   - slot, ident, is_write_read               │
                              │                                              │
   cacheResponse ◄────────────│ Valid: cache line response received          │
                              │   - ident                                    │
                              │                                              │
   ══════════════════════════ │ ══════ Kamlet Packet Interface ═════════════ │
                              │                                              │
   kamletInjectPacket ───────►│ Decoupled: kamlet sends packet via router    │
                              │                                              │
   kamletReceivePacket ◄══════│ Decoupled: forward packets to kamlet         │
                              │                                              │
                              └─────────────────────────────────────────────┘

Legend: ═══► Decoupled (ready/valid + data)
        ───► Valid only (no backpressure)
```

## Port Descriptions

### Position
- `thisX`, `thisY`: Jamlet's coordinates in the mesh

### Network (Channel 0 and Channel 1)
- `n0i/n0o, s0i/s0o, e0i/e0o, w0i/w0o`: Channel 0 directional I/O
- `n1i/n1o, s1i/s1o, e1i/e1o, w1i/w1o`: Channel 1 directional I/O
- Channel 0: Always-consumable responses
- Channel 1: Requests (may need to send response)

### Instruction Interface

#### instruction (Valid, from Kamlet)
General instruction port - creates witem or executes ALU/memory operation.

Fields:
- `instr_type`: Enum (witem_create, alu_op, ...)
- `instr_ident`: Instruction identifier
- Type-specific fields (witem fields or ALU fields)

Behavior:
- **ALU ops**: Route to LocalExec → ALU, execute on RF
- **Simple witems** (LoadSimple, StoreSimple, WriteImmBytes, ReadByte): Route to LocalExec,
  execute SRAM↔RF transfer immediately. Kamlet only sends these when cache is ready.
- **Protocol witems** (J2J, Word, Stride, etc.): Store in WitemTable, WitemMonitor handles
  when ready

#### witemCacheAvail (Valid, from Kamlet)
Notifies that a cache line became ready.

Fields:
- `instr_ident`: Which witem's cache is now available

#### witemRemove (Valid, from Kamlet)
Delete a witem entry after completion acknowledged.

Fields:
- `instr_ident`: Which witem to remove

#### witemComplete (Valid, to Kamlet)
All protocol states for this witem reached COMPLETE.

Fields:
- `instr_ident`: Which witem finished

### Cache Slot Interface

Used by RX-initiated witems (ReadMemWord, WriteMemWord) to request cache slots.

#### cacheSlotReq (Valid, to Kamlet)
Jamlet received a REQ and needs a cache slot for the address.

Fields:
- `k_maddr`: The memory address
- `is_write`: Read vs write access
- `instr_ident`: For tracking
- `source (x, y)`: Source of the REQ (for matching)

#### cacheSlotResp (Valid, from Kamlet)
Kamlet responds with allocated slot.

Fields:
- `instr_ident`: Matching the request
- `source (x, y)`: Matching the request
- `slot`: Allocated slot (or rejected indicator)
- `cache_is_avail`: Whether data is ready now

#### cacheStateUpdate (Valid, to Kamlet)
Cache slot state changed to MODIFIED (after a write).

Fields:
- `slot`: Which cache slot was modified

### TLB Interface

For address translation (strided/indexed operations).

#### tlbReq (Valid, to Kamlet)
Request virtual-to-physical address translation.

Fields:
- `vaddr`: Virtual address to translate

Used by WitemMonitor for strided/indexed operations that need per-element translation.

#### tlbResp (Valid, from Kamlet)
Translation response from kamlet TLB cache.

Fields:
- `paddr`: Physical address
- `error`: Page fault or access error

Latency: 2 cycles from request.

### Cache Line Interface

For memlet communication (READ_LINE, WRITE_LINE_READ_LINE).

#### sendCacheLine (Valid, from Kamlet)
Command jamlet to send its SRAM data to memlet.

Fields:
- `slot`: Which SRAM slot to read
- `ident`: For response tracking
- `is_write_read`: WRITE_LINE_READ_LINE vs WRITE_LINE

Flow: Each jamlet sends its own packet. Memlet assembles j_in_k packets.

#### cacheResponse (Valid, to Kamlet)
A cache line response (READ_LINE_RESP) was received by this jamlet.

Fields:
- `ident`: The cache request identifier

The kamlet tracks which jamlets have received responses (one wire per jamlet).

### Kamlet Packet Interface

Generic packet interface between jamlet and kamlet.

#### kamletInjectPacket (Decoupled, from Kamlet)
Kamlet sends a packet out via this jamlet's router.

Used for: READ_LINE initiation, etc.

#### kamletReceivePacket (Decoupled, to Kamlet)
Forward received packets to kamlet.

Used for: Instructions, other control packets.

## Internal Submodules

1. **Router0** - Channel 0 network router
2. **Router1** - Channel 1 network router
3. **Sram** - Local cache memory (with arbitration)
4. **RfSlice** - Register file portion for this jamlet
5. **RxCh0** - Channel 0 receive handler
6. **RxCh1** - Channel 1 receive handler (includes RxPendingTable)
7. **WitemMonitor** - Protocol witem table + pipeline (combined module)
8. **Ch0Arbiter** - Arbitrates Channel 0 transmit
9. **Ch1Arbiter** - Arbitrates Channel 1 transmit
10. **ALU** - Arithmetic/logic operations on RF (see alu.md)
11. **LocalExec** - Executes immediate instructions (Simple witems + ALU ops)

## Design Decisions

1. **Simple types handled by LocalExec**: Simple witems (LoadSimple, StoreSimple,
   WriteImmBytes, ReadByte) and ALU instructions are sent by kamlet only when ready to
   execute. They go directly to LocalExec for immediate SRAM↔RF or RF↔RF transfer. These
   never enter the jamlet WitemTable - they wait in the kamlet WitemTable until cache is
   ready.

2. **Protocol witems use WitemTable + WitemMonitor**: Protocol witems (J2J, Word, Stride,
   etc.) require jamlet-to-jamlet coordination. These are stored in the jamlet WitemTable
   with protocol_states for tag tracking. WitemMonitor scans for ready entries and handles
   packet building/sending.

3. **Reduction operations split**: Reductions are split into communication ops (handled by
   WitemMonitor) and ALU ops (handled by LocalExec). This keeps ALU access exclusive to
   LocalExec.

4. **RX-initiated witems request slots**: ReadMemWord/WriteMemWord are created by RX handlers.
   They use `cacheSlotReq/Resp` to get cache slots from kamlet since kamlet owns cache state.

5. **Each jamlet sends its own cache line data**: For WRITE_LINE_READ_LINE, kamlet commands
   each jamlet to send. Memlet assembles the j_in_k packets.

6. **Each jamlet receives its own cache response**: Memlet sends j_in_k separate responses.
   Each jamlet signals `cacheResponse` when received. Kamlet tracks completion.

7. **Generic packet interface**: `kamletReceivePacket` handles all packets destined for
   kamlet (instructions, etc.) rather than having type-specific ports.
