# Memlet RTL Implementation Plan

## Overview

The Memlet is the VPU's interface to external DRAM. One Memlet per kamlet. It receives
cache line requests from jamlets via the mesh network, performs AXI4 memory transactions,
and sends responses back.

## IO

### AXI4 Memory Port

Uses rocket-chip's `AXI4Bundle` (from `freechips.rocketchip.amba.axi4`), not diplomacy.
Constructed with:
```
AXI4BundleParameters(
  addrBits = params.memAddrWidth,      // 48
  dataBits = params.memBeatWords * params.wordWidth,  // 1 * 64 = 64
  idBits = 4
)
```

Cache line transfers use AXI4 burst mode: `len = memBeatsPerCacheLine - 1`,
`burst = INCR`, `size = log2(memBeatWords * wordBytes)`. One beat per cycle,
`memBeatsPerCacheLine` beats per cache line.

### Mesh Ports

Per router: N/S/E/W channel ports (same pattern as Kamlet edge ports). Connected to
CombinedNetworkNode routers inside the module.

### Configuration Inputs

- Per-router coordinates `(x, y)` — for source fields in response headers
- Kamlet base coordinates `(kBaseX, kBaseY)` — jamlet targets computed as
  `(kBaseX + j_x, kBaseY + j_y)`

## Routers

`nRouters` CombinedNetworkNodes instantiated inside the module. N/S/E/W ports exposed
as module IO for mesh connection. For multi-router memlets, routers are connected N-S
internally; outer N/S and all E/W exposed.

Internal connections:
- Each router's **bHo** (B channel local output) feeds a KamletToBuffer FSM
- Each router's **aHi** (A channel local input) is driven by a BufferToKamlet FSM
- Unused: **aHo** tied off (`ready := false`), **bHi** tied off (`valid := false`)

## Message Protocol

### Requests (channel B, kamlet → memlet)

| Message | Header | Body | Sender |
|---------|--------|------|--------|
| ReadLine | AddressHeader | memAddr (1 word) | One jamlet |
| WriteLineAddr | AddressHeader | memAddr (1 word) | One jamlet |
| WriteLineReadLineAddr | AddressHeader | writeAddr + readAddr (2 words) | One jamlet |
| CacheLineData | AddressHeader | N data words | Each jamlet |

WriteLineAddr / WriteLineReadLineAddr are sent by one designated jamlet per kamlet.
They allocate a gathering slot. CacheLineData packets are sent by every jamlet and
carry that jamlet's portion of the cache line (cacheSlotWordsPerJamlet words).

### Responses (channel A, memlet → kamlet)

| Message | Header | Body | Recipient |
|---------|--------|------|-----------|
| ReadLineResp | AddressHeader | N data words | Each jamlet |
| WriteLineResp | IdentHeader | (none) | One jamlet |
| WriteLineReadLineResp | AddressHeader | N data words | Each jamlet |
| ReadLineDrop | IdentHeader | (none) | Requesting jamlet |
| WriteLineDrop | IdentHeader | (none) | Requesting jamlet |
| WriteLineReadLineDrop | IdentHeader | (none) | Requesting jamlet |
| CacheLineDataDrop | IdentHeader | (none) | Sending jamlet |

Drop responses are sent when the memlet cannot accept a request (readLineQueue full,
no free gathering slot, or data arrives before its address packet).

### New Message Types Needed

- WriteLineAddr, WriteLineReadLineAddr, CacheLineData (requests)
- ReadLineDrop, WriteLineDrop, CacheLineDataDrop (responses)

Existing types removed or repurposed: the old WriteLine and WriteLineReadLine
(which combined addresses + data) are replaced by the split protocol above.

## Architecture

### KamletToBuffer

One per router, but router 0 handles all message types while other routers only
handle CacheLineData. ReadLine, WriteLineAddr, and WriteLineReadLineAddr always
arrive at router 0 (the designated address router).

Reads packets word-by-word from its router's bHo port. Writes data directly into
shared gathering structures (no large body buffer).

#### Router 0 (address + data)

**Registers:**
- `rxHeader`: AddressHeader
- `rxWordCount`: counter for data words
- `rxJIndex`: j_index for current packet
- `rxSlotIndex`: gathering slot index
- `rxState`: enum

**States:**

- **Idle**: accept header from bHo. Parse AddressHeader, compute j_index from source
  coords (`j_x = sourceX % jCols`, `j_y = sourceY % jRows`,
  `j_index = j_y * jCols + j_x`). Branch by messageType:
  - ReadLine → if readLineQueue not full, go to ReceiveReadLineAddr. Else enqueue
    ReadLineDrop, stay in Idle.
  - WriteLineAddr → find/alloc gathering slot. If none free, enqueue WriteLineDrop,
    stay in Idle. Else go to ReceiveWriteAddr.
  - WriteLineReadLineAddr → find/alloc gathering slot. If none free, enqueue
    WriteLineReadLineDrop, stay in Idle. Else go to ReceiveWriteAddr.
  - CacheLineData → find gathering slot by ident. If not found, go to DrainAndDrop.
    Else go to ReceiveData.

- **ReceiveReadLineAddr**: on bHo.fire, enqueue `{ident, sramAddr, memAddr}` to
  readLineQueue. Go to Idle.

- **ReceiveWriteAddr**: on bHo.fire, store address into gathering slot.
  - If WriteLineReadLineAddr: go to ReceiveReadAddr.
  - If WriteLineAddr: go to Idle.

- **ReceiveReadAddr**: on bHo.fire, store read address into gathering slot. Set
  `needsRead = true`. Go to Idle.

- **ReceiveData**: on bHo.fire, write word directly into
  `gatheringSlots(rxSlotIndex).data(rxJIndex + rxWordCount * jInK)`. Increment
  counter. When last word: set `arrived(rxJIndex)`. If all jInK arrived, enqueue
  slot index to completeQueue. Go to Idle.

- **DrainAndDrop**: accept and discard remaining data words from bHo. Enqueue
  CacheLineDataDrop. When packet complete, go to Idle.

#### Routers 1..N-1 (data only)

Same registers minus address-related ones. Only two message types:

- **Idle**: accept header from bHo. Parse AddressHeader, compute j_index.
  - CacheLineData → find gathering slot by ident in local replica. If not found,
    go to DrainAndDrop. Else go to ReceiveData.
  - Anything else → unexpected, ignore/drain.

- **ReceiveData**: same as router 0.

- **DrainAndDrop**: same as router 0.

#### Slot Ident Replication

Each router maintains a local replica of `{valid, ident}` for each gathering slot.
Router 0 is authoritative — when it allocates or frees a slot, the update propagates
down the router chain, one hop per cycle. Routers 1..N-1 check their local replica
when a CacheLineData packet arrives.

If a CacheLineData packet arrives before the slot allocation has propagated (slot
appears unallocated in the local replica), the data is drained and a CacheLineDataDrop
is sent. The kamlet will retry. This cleanly handles the propagation race without
requiring cross-router combinational paths.

### MemoryEngine (one per memlet)

Fully pipelined AXI4 master. Dequeues from completeQueue and readLineQueue, issues
AXI4 write and read transactions, receives responses, and scatters read data into
the distributed Response Buffer. All AXI4 interaction is contained here.

#### Transaction Tracker

Array indexed by AXI4 ID (`2^idBits` entries). Tracks all in-flight transactions
and pairs WLRL write/read completions.

Per entry:
- `valid: Bool`
- `type: WL | ReadLine | WlrlWrite | WlrlRead`
- `ident: UInt(identWidth)`
- `sramAddr: UInt(sramAddrWidth)`
- `sourceX, sourceY: UInt` — requester coordinates (for WriteLineResp)
- `partnerId: UInt(idBits)` — links WlrlWrite ↔ WlrlRead
- `complete: Bool` — B received (write types) or R received (read types)
- `responseBufAllocated: Bool` — read types only, set on first R beat
- `responseSlotIdx: UInt` — read types only, set on first R beat

ID allocation via free list (bit vector). Dequeue engine stalls if no free IDs.

#### Queues

| Queue | Entry |
|-------|-------|
| Write Addr | {writeAddr, axiId} |
| Write Data | cache line data (cacheSlotWords words) |
| Read Addr | {memAddr, axiId} |
| WriteLineResp FIFO | {ident, targetX, targetY} — fed to BufferToKamlet (router 0) |

Write Addr and Write Data queues stay synchronized (same enqueue order). AXI4
requires W data in AW issue order.

#### Engines (all run concurrently)

**Dequeue Engine**: Pops from completeQueue and readLineQueue.
- completeQueue: allocate one AXI4 ID for WL or two for WLRL. Initialize
  tracker entries (copy ident, sramAddr, sourceX/Y from gathering slot;
  set partnerId on each for WLRL). Copy cache line data from gathering
  slot into Write Data queue. Enqueue {writeAddr, axiId} to Write Addr
  queue. If WLRL: also enqueue {readAddr, readAxiId} to Read Addr queue.
  **Free gathering slot immediately** (data has been copied out).
- readLineQueue: allocate one AXI4 ID, initialize tracker entry
  (type=ReadLine, copy ident, sramAddr from queue entry).
  Enqueue {memAddr, axiId} to Read Addr queue.

**AW Engine**: Pop Write Addr queue → drive AW channel (awid = axiId,
awaddr = writeAddr, awlen = memBeatsPerCacheLine - 1, awburst = INCR,
awsize = log2(memBeatWords * wordBytes)).

**W Engine**: Pop Write Data queue → stream cacheSlotWords beats on W channel.
wlast on final beat. One cache line at a time, in Write Addr queue order.

**B Engine**: Accept B channel response. Look up tracker[bid]:
- WL: enqueue {ident, sourceX, sourceY} to WriteLineResp FIFO, free
  tracker entry.
- WlrlWrite: set complete. Check tracker[partnerId]: if partner also
  complete → mark Response Buffer slot sendable, free both entries.
  Else wait.

**AR Engine**: Pop Read Addr queue → drive AR channel (arid = axiId,
araddr = memAddr, arlen = memBeatsPerCacheLine - 1, arburst = INCR,
arsize = log2(memBeatWords * wordBytes)).

**R Engine**: Accept R channel beats. Lazy Response Buffer allocation
and scatter to distributed per-router storage (see Response Buffer
under Shared State). On each beat:
- If `!responseBufAllocated`: allocate a free Response Buffer slot.
  If none free, hold RREADY low until one frees. Set
  `responseBufAllocated = true`, record `responseSlotIdx` in tracker,
  initialize slot metadata (ident, sramAddr, responseType from tracker).
- Compute target router and local data index from beat position
  (see R Engine scatter formula under Response Buffer). Write beat
  data to that router's local storage.
- On `rlast`, look up tracker[rid]:
  - ReadLine: mark Response Buffer slot sendable, free tracker entry.
  - WlrlRead: set complete. Check tracker[partnerId]: if partner
    also complete → mark sendable, free both. Else wait.

### BufferToKamlet (one per router)

Each router has a fully independent BufferToKamlet instance. Sends response
packets through its router's aHi port, one word per cycle.

#### Per-router instance (duplicated at each router)

**Local state:**
- Drop queue (fed by this router's KamletToBuffer)
- Response Buffer data storage (this router's portion of each slot)
- `routerDone` bit per slot (set when this router finishes sending)
- FSM registers: `txState`, `txJamletIdx`, `txWordIdx`, `txSlotIdx`,
  `txHeader`

**Router 0 additionally has:**
- WriteLineResp FIFO (fed by MemoryEngine B Engine)

#### Shared inputs (read-only, central at router 0)

Response Buffer metadata: `sendable`, `ident`, `sramAddr`, `responseType`.
All routers read the same metadata to discover sendable slots. Each router
independently processes its own local jamlets — no coordination needed.

#### Priority

| Priority | Source | Types | Data? |
|----------|--------|-------|-------|
| 1 | Local Drop Queue | All drop types | No |
| 2 | WriteLineResp FIFO (router 0) | WriteLineResp | No |
| 3 | Response Buffer | ReadLineResp, WLRL Resp | Yes |

Drops first so senders can retry quickly. WriteLineResp is a single
word. Response Buffer takes many cycles (multi-jamlet, multi-word).

#### Broadcast responses (Response Buffer)

Router `r` sends one packet per local jamlet. Each packet is
`1 + cacheSlotWordsPerJamlet` words (AddressHeader + data). Local
jamlets for router `r` are global indices `r * localJamlets` through
`(r+1) * localJamlets - 1`.

Target coordinates for global jamlet `j`:
`(kBaseX + j % jCols, kBaseY + j / jCols)`.

Data for local jamlet `lj`, word `w` is at local storage index
`lj * cacheSlotWordsPerJamlet + w` — contiguous per jamlet.

#### States

- **Idle**: check sources in priority order.
  - Drop Queue not empty → dequeue, build IdentHeader,
    go to **SendSingleWord**
  - WriteLineResp FIFO not empty (router 0) → dequeue,
    build IdentHeader, go to **SendSingleWord**
  - Response Buffer has slot with `sendable && !routerDone[myId]` →
    latch slot index, `txJamletIdx = 0`, go to **SendResponseHeader**

- **SendSingleWord**: drive aHi with header. On fire → **Idle**.

- **SendResponseHeader**: build AddressHeader for current jamlet
  (target coords from jamlet index, ident/sramAddr/messageType from
  Response Buffer metadata, source = this router's coords,
  length = cacheSlotWordsPerJamlet). Drive aHi. On fire →
  `txWordIdx = 0`, go to **SendResponseData**.

- **SendResponseData**: read local data at index
  `txJamletIdx * cacheSlotWordsPerJamlet + txWordIdx`, drive aHi.
  On fire:
  - Increment `txWordIdx`
  - If last word (`txWordIdx == cacheSlotWordsPerJamlet - 1`):
    - Increment `txJamletIdx`
    - If more local jamlets → **SendResponseHeader**
    - If last local jamlet → set `routerDone[myId]`, → **Idle**

## Shared State Between FSMs

All shared state lives in the Memlet module. The three block types
read/write it as described below.

### Gathering Slots

`nMemletGatheringSlots` entries (default 4). Used for both WriteLineAddr and
WriteLineReadLineAddr operations.

#### Per-slot fields and physical location

**Router 0 only (authoritative):**
- `valid: Bool` — slot is allocated
- `sramAddr: UInt(sramAddrWidth)` — SRAM word address (from AddressHeader)
- `sourceX, sourceY: UInt` — requester coordinates (for WriteLineResp)
- `writeAddr: UInt(wordWidth)` — memory byte address to write
- `readAddr: UInt(wordWidth)` — memory byte address to read (WLRL only)
- `needsRead: Bool` — true for WLRL, false for WL
- `allArrived: Bool` — true when all jamlets have sent data

**Replicated at every router (propagated from router 0, 1 cycle per hop):**
- `valid: Bool`
- `ident: UInt(identWidth)` — instruction identifier

Used by each router's KamletToBuffer to look up slots for CacheLineData packets.
Propagated when router 0 allocates or frees a slot.

**Per router (local storage):**
- `arrived: Vec(localJamlets, Bool)` — which of this router's jamlets have sent
  data. Each router only tracks arrived bits for jamlets that route to it
  (jamlet j maps to router `j / (jInK / nRouters)`).
- `data: Vec(localWords, UInt(wordWidth))` — this router's portion of the cache
  line. Each router stores `cacheSlotWordsPerJamlet * localJamlets` words, where
  `localJamlets = jInK / nRouters`.

Arrived bits propagate toward router 0 (1 cycle per hop). When router 0 sees
all arrived bits set (local + propagated from other routers), it sets `allArrived`
and enqueues the slot index to `completeQueue`.

#### Data ordering

Jamlet j's word i is at index `j + i * jInK` in the logical cache line. Physically,
this word lives at router `j / (jInK / nRouters)`. When BufferToMemory streams the
cache line to AXI4, MemoryEngine reads words in order (0, 1, 2, ...),
pulling from each router's local storage in turn.

For nRouters=1, all data is local — no distribution needed.

#### Slot lifecycle
1. KamletToBuffer (router 0) allocates slot on address packet: sets valid, ident,
   sramAddr, addresses, needsRead. Clears arrived bits. Allocation propagates to
   other routers over subsequent cycles.
2. KamletToBuffer (any router) fills local data words and local arrived bits from
   CacheLineData. Local arrived bits propagate toward router 0.
3. When router 0 sees all arrived bits set, enqueues slot index to `completeQueue`.
4. MemoryEngine dequeues from completeQueue, copies cache line data into Write
   Data queue, copies metadata into tracker and Write Addr / Read Addr queues.
   **Frees gathering slot immediately** (data has been copied out).
5. AXI4 write and read proceed through the pipeline independently.
6. Read response data is stored in a Response Buffer slot (separate from gathering
   slots). For WLRL, the Response Buffer slot is marked sendable only after both
   write (B response) and read (R response) complete.
7. BufferToKamlet sends response packets from the Response Buffer slot, then frees
   the Response Buffer slot.

### Read Line Queue

Depth 2. Each entry holds:
- `ident: UInt(identWidth)`
- `sramAddr: UInt(sramAddrWidth)` — SRAM word address (from AddressHeader)
- `memAddr: UInt(wordWidth)` — memory byte address to read

Writer: KamletToBuffer (router 0) on ReadLine packet.
Reader: MemoryEngine dequeues and issues AXI4 read.

Read responses go into a Response Buffer slot (shared with WLRL read responses).
BufferToKamlet reads from the Response Buffer to send response packets.

### Complete Queue

Depth = nMemletGatheringSlots. Holds gathering slot indices.

Writer: KamletToBuffer (any router) when all arrived bits set.
Reader: MemoryEngine.

### Drop Queue

Depth TBD. Each entry holds:
- `messageType` — which drop response to send (ReadLineDrop, WriteLineDrop,
  WriteLineReadLineDrop, CacheLineDataDrop)
- `ident: UInt(identWidth)`
- `targetX, targetY` — where to send the drop response (back to requester)

Writer: KamletToBuffer (any router) when it can't accept a request.
Reader: local BufferToKamlet (each router sends its own drops through
its own aHi).

If the drop queue is full when a KamletToBuffer needs to enqueue a drop, it
back-pressures bHo (deasserts ready) until a drop queue slot is available.
This is safe because drop responses go on channel A (always-consumable), so
the back-pressure cannot cause deadlock.

### Response Buffer

`nResponseBufferSlots` entries (default 4). Stores read response data for
ReadLine and WriteLineReadLine operations. Data is physically distributed
across routers; metadata is central. No separate per-router response
queues — each BufferToKamlet scans the Response Buffer directly.

Mirrors the gathering slot pattern but in reverse direction:

| | Gathering Slots | Response Buffer |
|---|---|---|
| Data flow | Distributed → central | Central → distributed |
| Per-router data | Local portion of cache line | Local portion of cache line |
| Coordination | `arrived` → router 0 | `routerDone` → router 0 |
| Ident/metadata | Replicated from router 0 | Central at router 0 |
| Freed by | Router 0 (all arrived) | Router 0 (all routerDone) |

#### Per-slot fields and physical location

**Central (at router 0 / near AXI4 port):**
- `valid: Bool` — slot is allocated
- `ident: UInt(identWidth)`
- `sramAddr: UInt(sramAddrWidth)`
- `responseType: ReadLine | WlrlRead`
- `beatCount: UInt` — words received so far
- `sendable: Bool` — all data received AND (for WLRL) write complete

**Per router (local storage):**
- `data: Vec(localWords, UInt(wordWidth))` — this router's portion.
  `localWords = localJamlets * cacheSlotWordsPerJamlet`. Stored
  contiguously per jamlet:
  `data(localJamletIdx * cacheSlotWordsPerJamlet + w)`.
- `routerDone: Bool` — set by BufferToKamlet when done sending.
  Propagates toward router 0 (1 cycle per hop).

Slot freed when `sendable && all routerDone bits set` (at router 0).

#### R Engine scatter

R Engine receives AXI4 R beats centrally (one word per cycle for
memBeatWords=1). Each beat is routed to the appropriate router's
local storage via direct write paths. Address computation for beat
`beatIdx` in the cache line:

- `jamletIdx = beatIdx % jInK`
- `routerIdx = jamletIdx / localJamlets`
- `localJamletIdx = jamletIdx % localJamlets`
- `wordWithinJamlet = beatIdx / jInK`
- `localDataIdx = localJamletIdx * cacheSlotWordsPerJamlet
  + wordWithinJamlet`

One router written per cycle, matching AXI4 rate. For nRouters=1,
all writes are local.

#### Lazy slot allocation

Response Buffer slots are NOT pre-allocated when reads are issued.
The R Engine allocates on the first R beat for a transaction:

1. First R beat for `rid`. Look up tracker[rid].
2. `!responseBufAllocated` → allocate free Response Buffer slot.
   If none free: hold RREADY low until one frees. Set
   `responseBufAllocated = true`, record `responseSlotIdx` in tracker,
   initialize slot metadata from tracker.
3. Store beat data into computed router's local storage.
4. Subsequent beats: store directly (slot already allocated).
5. On `rlast`: completion logic per MemoryEngine R Engine.

This avoids wasting slots on in-flight reads that haven't returned
data yet. The number of in-flight AXI4 reads (up to 2^idBits) can
far exceed nResponseBufferSlots.

#### Slot lifecycle

1. R Engine allocates on first R beat: sets valid, metadata.
2. R Engine scatters beats to per-router local storage.
3. Marked sendable: by R Engine for ReadLine (on rlast), or by whichever
   of R Engine / B Engine completes last for WLRL.
4. Each BufferToKamlet finds sendable slot with `!routerDone[myId]`,
   sends packets for local jamlets, sets `routerDone`.
5. `routerDone` propagates toward router 0. All set → slot freed.

## Module Hierarchy

```
Memlet
├── MemletSlice[0..nRouters-1]
│   ├── CombinedNetworkNode (router)
│   ├── KamletToBuffer logic
│   ├── BufferToKamlet logic
│   ├── Local gathering slot storage (data + arrived)
│   ├── Local response buffer storage (data + routerDone)
│   └── Local drop queue
└── MemoryEngine
    ├── Transaction tracker + AXI4 ID free list
    ├── Write Addr / Write Data / Read Addr queues
    ├── WriteLineResp FIFO
    ├── Response Buffer central metadata
    └── Dequeue, AW, W, B, AR, R engines
```

The module boundary forces explicit decisions about cross-module signal
timing. All inter-slice communication uses registered propagation chains
(one hop per cycle). MemletSlice IO is parameterized by `routerId` —
slice 0 has additional ports for gathering slot metadata and readLineQueue.

### MemletSlice IO

#### Mesh ports

N/S/E/W channel ports (A and B channels). Memlet top level exposes
external edges and connects adjacent slices N-S internally.

#### Inter-slice propagation chains

Event-based, registered one hop per cycle. Memlet top level wires
slice 0 out → slice 1 in → slice 1 out → slice 2 in, etc.

**Ident allocation (outward from slice 0):**
`{valid, slotIdx, ident}`. Sent when KamletToBuffer (slice 0)
allocates a gathering slot. Each downstream slice latches the ident
into its local replica for that slot. Freeing is local — each slice
clears its replica when all its local arrived bits are set (no more
CacheLineData lookups needed for that slot).

**Arrived (inward toward slice 0):**
`{valid, slotIdx}`. Sent when all of a slice's local jamlets have
arrived for a gathering slot. Slice 0 counts these events per slot;
when count equals `nMemletRouters - 1` AND its own local jamlets
are all arrived, it sets allArrived and enqueues to completeQueue.

**RouterDone (inward toward slice 0):**
`{valid, slotIdx}`. Sent when a slice's BufferToKamlet finishes sending
all response packets for a Response Buffer slot. Slice 0 collects and
forwards to MemoryEngine for slot freeing.

#### Gathering side (slice → MemoryEngine)

**Complete queue enqueue (slice 0 only):**
Decoupled, carries `slotIdx`. Slice 0 enqueues when all arrived bits
are set for a gathering slot.

**Read line queue enqueue (slice 0 only):**
Decoupled, carries `{ident, sramAddr, memAddr}`. Slice 0 enqueues when
a ReadLine packet is received.

**Gathering slot data read (all slices):**
MemoryEngine's Dequeue Engine reads local gathering data from each
slice. Port: `{slotIdx, wordIdx}` → data. For nRouters>1, Dequeue
Engine reads from slices in memory-word order (interleaved across
slices).

**Gathering slot metadata read (slice 0 only):**
MemoryEngine reads authoritative metadata from slice 0: `slotIdx` →
`{ident, sramAddr, sourceX/Y, writeAddr, readAddr, needsRead}`.

**Gathering slot free (MemoryEngine → slice 0):**
Pulse `{slotIdx}`. After Dequeue Engine copies data, it tells slice 0
to clear the authoritative valid bit.

#### Response side (MemoryEngine → slices)

**Response Buffer data write (ME → all slices):**
Per slice: `{valid, slotIdx, localDataIdx, data: UInt(wordWidth)}`.
R Engine asserts valid on exactly one slice's port per beat. The slice
latches the word at the given address — no handshake needed.

**Response Buffer metadata replication (ME → slice 0 → outward):**
Event-based propagation chain, same pattern as gathering slot ident
replication. Shared wires with a type bit to distinguish two events:
- Allocate (`type=0`): `{valid, type, slotIdx, ident, sramAddr,
  responseType}`. Sent when R Engine allocates a Response Buffer
  slot on the first R beat. Each slice latches into its local
  metadata replica for that slot.
- Sendable (`type=1`): `{valid, type, slotIdx}`. `ident`, `sramAddr`,
  `responseType` fields are don't-care. Sent when a slot becomes
  sendable (all data received, and for WLRL the write is also
  complete). Each slice sets the sendable flag in its local replica.
These cannot conflict: Allocate fires on the first R beat,
Sendable fires on rlast or later (B response for WLRL).
Freeing is local — each slice clears its replica when it sets
`routerDone` for that slot.

**WriteLineResp FIFO dequeue (ME → slice 0 only):**
Decoupled `{ident, targetX, targetY}`. Slice 0's BufferToKamlet
dequeues to send WriteLineResp packets.

**Response Buffer free (slice 0 → ME):**
Pulse `{slotIdx}`. Slice 0 sends when all routerDone bits are
collected for a slot. MemoryEngine clears the central valid bit.

## Packet Length Constraint

`cacheSlotWordsPerJamlet <= 12` — CacheLineData needs `1 + cacheSlotWordsPerJamlet`
words, must fit in 4-bit length field (max 15). Enforced by require in ZamletParams.

## Parameters

Added to ZamletParams:
- `nMemletGatheringSlots: Int = 4`
- `nResponseBufferSlots: Int = 4`
- `memBeatWords: Int = 1` — words per AXI4 beat (default matches Shuttle's 8-byte bus)

Derived:
- `cacheSlotWordsPerJamlet = cacheSlotWords / jInK`
- `memBeatsPerCacheLine = cacheSlotWords / memBeatWords`

## BUILD File

New `src/main/scala/zamlet/memlet/BUILD` with:
- `filegroup` for memlet_sources
- `chisel_binary` target depending on jamlet_sources (Packet, NetworkWord),
  ZamletParams, ModuleGenerator, utils, and rocket-chip AXI4 bundles
