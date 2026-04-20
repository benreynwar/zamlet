# SramArbiter Design

## Overview

Fixed-priority arbiter for SRAM access. Three clients compete for SRAM.

**Clients:**
- **LocalExec**: Simple witems (LoadSimple, StoreSimple, WriteImmBytes, ReadByte)
- **WitemMonitor**: Protocol witems (J2J SRC, Word SRC reads data to send)
- **RxCh1**: RX-initiated ops (ReadMemWord read, WriteMemWord write) and DST writes (J2J, Word)

Note: RxCh0 handles responses only (state updates), no SRAM access needed.

**Priority:** LocalExec > RxCh1 > WitemMonitor

(LocalExec highest priority since it's on the instruction issue path)

## Interface

```
SramArbiter:

  // From requesters (Decoupled)
  ← localExecReq      : Decoupled (addr + isWrite + writeData + mask)
  ← rxCh1Req          : Decoupled (addr + isWrite + writeData + mask)
  ← monitorReq        : Decoupled (addr + isWrite + writeData + mask)

  // To requesters (Decoupled)
  → localExecResp     : Decoupled (readData)
  → rxCh1Resp         : Decoupled (readData)
  → monitorResp       : Decoupled (readData)

  // To Sram
  → sramAddr          : Addr
  → sramWriteEn       : Bool
  → sramWriteData     : Data
  → sramWriteMask     : Mask
  ← sramReadData      : Data
```

## Behavior

Each cycle, grant goes to highest-priority requester with valid request.
