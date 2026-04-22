# Ch0Arbiter / Ch1Arbiter Design

## Overview

Arbiters for transmitting packets on channel 0 and channel 1 routers.

## Ch0Arbiter (Responses)

Arbitrates channel 0 transmit for response packets.

**Senders:**
- RxCh1: RESP/DROP after handling requests
- WitemMonitor: READ_MEM_WORD_RESP, WRITE_MEM_WORD_RETRY

**Interface:**
```
Ch0Arbiter:
  ← rxCh1Packet       : Decoupled (packet)
  ← monitorPacket     : Decoupled (packet)
  → routerInject      : Decoupled (packet words)
```

**Priority:** RxCh1 > WitemMonitor (keep responses flowing to avoid backpressure)

## Ch1Arbiter (Requests)

Arbitrates channel 1 transmit for request packets.

**Senders:**
- WitemMonitor: J2J REQs, Word REQs, READ_MEM_WORD_REQ, WRITE_MEM_WORD_REQ
- CacheLineSender: WRITE_LINE_READ_LINE (with SRAM data)
- kamletInjectPacket: READ_LINE (no SRAM data needed)

**Interface:**
```
Ch1Arbiter:
  ← monitorPacket     : Decoupled (packet)
  ← cacheLinePacket   : Decoupled (packet)
  ← kamletPacket      : Decoupled (packet)
  → routerInject      : Decoupled (packet words)
```

**Priority:** TBD - possibly round-robin or based on urgency

