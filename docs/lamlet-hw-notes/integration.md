# Lamlet Hardware Integration

## Overview

The lamlet integrates with the scalar core (Rocket/BOOM) via RocketChip's `VectorCoreIO` interface.
We follow Saturn's integration pattern but replace the centralized backend with our distributed
kamlet/jamlet mesh.

## Saturn vs Our Architecture

| Saturn Component | Our Replacement | Notes |
|------------------|-----------------|-------|
| VectorBackend | Kamlet/Jamlet mesh | Distributed execution |
| VectorMemUnit | Memlets | Each memlet has own DRAM interface |
| Sequencers | Lamlet fission + kamlet iteration | Different granularity |
| Centralized VRF | Distributed in jamlets | Fundamental difference |
| Frontend fault check | Hybrid (lamlet + kamlets) | Lamlet: unit-stride, Kamlets: indexed |

## Key Interfaces

### VectorCoreIO (from scalar core)

Reuse directly from RocketChip:

**Execute stage (instruction receive):**
- `ex.valid/ready` - handshake
- `ex.inst` - 32-bit instruction
- `ex.pc, vconfig, vstart, rs1, rs2` - context

**Writeback stage (completion):**
- `wb.replay` - instruction needs replay
- `wb.retire` - instruction retiring
- `wb.xcpt, cause, tval` - exception info

**CSR updates:**
- `set_vstart, set_vxsat, set_vconfig, set_fflags`

**Scalar result (vmv.x.s, etc.):**
- `resp` - Decoupled(fp, rd, data)

**Busy signals:**
- `trap_check_busy` - still checking for faults
- `backend_busy` - VPU execution ongoing

### TileLink Slave Interface (scalar → VPU memory)

Lamlet exposes a TileLink target interface for scalar core to access VPU memory:

```
Scalar core
    ↓ TileLink (Get/Put)
Lamlet (TileLink slave)
    ↓ internal messages
Jamlet → Kamlet cache table → Memlet → VPU DRAM
```

**Requirements:**
- Support concurrent outstanding requests (not just single)
- Request table to track in-flight transactions
- Tag/source ID to match responses
- Route by address to appropriate kamlet/jamlet
- Uses kamlet's cache table for coherency

**Characteristics:**
- Low throughput (occasional access for setup/teardown)
- Memory-mapped from scalar core's perspective

### Memlet DRAM Interface

Each memlet has its own dedicated DRAM interface (TBD). Not shared with scalar memory system.

```
Memlet → dedicated VPU DRAM
```

## Instruction Flow Control

We keep the IdentQuery approach from the Python model (not credit-based or backpressure).

### Lamlet State

```
available_tokens[k_in_l]         -- per-kamlet instruction queue slots
tokens_used_since_query[k_in_l]  -- accumulates until query sent
tokens_in_active_query[k_in_l]   -- returned when response arrives
next_instr_ident                 -- 7-bit wrapping allocator
oldest_active_ident              -- 7-bit, from last query response
ident_query_state                -- DORMANT / READY_TO_SEND / WAITING_FOR_RESPONSE
```

### Flow

1. On dispatch to kamlet k: `available_tokens[k] -= 1`
2. When `any(available_tokens < threshold)` or idents running low: trigger IdentQuery
3. IdentQuery broadcasts to all kamlets, uses sync network to find oldest active ident
4. Response returns tokens and updates `oldest_active_ident`

### Ident Lifecycle

```
Lamlet allocates ident → Dispatched → Kamlet creates waiting items →
Waiting items complete → Ident removed from tables → Ident is "free"
```

An ident is "complete" when no longer used as a key in any waiting item table (not when
instruction leaves queue).

Reserved token: Regular instructions need `available_tokens[k] > 1`. IdentQuery only needs `> 0`.

## RISC-V → Kinstr Conversion

Unlike Saturn's element-by-element sequencers, we fission at region boundaries:

| Aspect | Saturn | Ours |
|--------|--------|------|
| Fission level | Element/EG | Memory region |
| Where iteration happens | Sequencer (centralized) | Kamlet (distributed) |
| Micro-op granularity | 1 element group | Whole cache line section |

Lamlet fissions by:
- Page boundaries
- Cache line boundaries
- VPU vs scalar memory transitions

Each kinstr handles a contiguous section. Kamlets handle element iteration internally.

## TLB Architecture

Lamlet and kamlets all have TLBs. Lamlet is authoritative, kamlets cache.

### Two Separate Lookups

**Standard TLB** (via DCacheTLBPort):
- Virtual → Physical address
- Permissions (R/W/X)
- Uses scalar core's page table walker

**VPU Metadata Table** (our own):
- Virtual → (element_width, word_order)
- Only covers VPU-mapped virtual addresses
- Sv39-like hierarchical structure
- Lives in scalar memory (like standard page tables)
- Lamlet has base register (like `satp`)

### Physical Address Determines is_vpu

No need to store is_vpu in metadata - determined by whether physical address falls in VPU memory range.

### Combined Cache

Cache entries contain both:
```
VA tag | PA | perms | ew (2 bits) | word_order (1 bit)
```

On miss, both walks happen (can be parallel):
- TLB miss → DCacheTLBPort to scalar core's PTW
- Metadata miss → our walker reads from scalar memory

### Kamlet TLB Caches

- Each kamlet has local TLB cache
- Hit → use cached translation + metadata
- Miss → request fill from lamlet
- SFENCE.VMA → lamlet broadcasts invalidate to all kamlet caches

### When TLBs Are Used

- **Lamlet TLB**: Unit-stride fault check before dispatch (check page range)
- **Kamlet TLBs**: Per-element lookup for strided/indexed ops

## Completion Signals

Signals from VPU back to scalar core via VectorCoreIO.

### backend_busy

Indicates VPU has uncommitted work. Scalar core uses this to:
- Stall fence instructions until VPU drains
- Prevent vector CSR access while VPU is working

**Implementation**: Lamlet determines this locally from instr_ident tracking:
```
backend_busy = any instr_idents still active
             = (next_instr_ident != oldest_active_ident)
```

No need to aggregate from kamlets - lamlet knows from its own state.

### set_vxsat (saturation flag)

Set when fixed-point saturating operations saturate (vsadd, vssub, vnclip, etc.).

**Implementation**:
1. Kamlets locally track if saturation occurred during execution
2. Sync operation with OR aggregation collects flags across kamlets
3. Lamlet receives aggregated flag, reports to scalar core

### set_fflags (FP exception flags)

5 bits: NV (invalid), DZ (div-by-zero), OF (overflow), UF (underflow), NX (inexact).
Set by vector FP instructions (vfadd, vfmul, vfdiv, vfcvt, etc.).

**Implementation**: Same as vxsat - sync with OR aggregation.

### Sync Network Operations

Extended to support:
- **MIN** - fault element finding, oldest ident (existing)
- **OR** - flag aggregation for vxsat, fflags (new)

### resp (scalar result)

For `vmv.x.s` / `vfmv.f.s` - reading element 0 to scalar/FP register.

**Implementation**:
- Element 0 lives in a specific jamlet (determined by word ordering)
- Lamlet sends targeted instruction to that kamlet
- Response returns via message channel
- Not an aggregation - just a point read

## Ordered Indexed Operations

Ordered indexed loads/stores (vloxei.v/vsoxei.v) require memory accesses in element order.
Element i might store to an address that element j reads - if i < j, the load must see the store.

### OrderedBuffer (Sliding Window)

Lamlet maintains ordered buffers to track element-by-element progress:

```
Capacity = N slots (parameter)

Elements: [0] [1] [2] [3] [4] [5] [6] [7] ...
           ↑                   ↑
      base_index          next_to_dispatch (up to capacity ahead)
           ↑
      next_to_process (strict in-order)
```

### Per-Element State Machine

```
DISPATCHED → READY → [IN_FLIGHT] → COMPLETE
```

- **DISPATCHED**: Sent to kamlet, waiting for address/data message
- **READY**: Have addr/data, waiting for turn (must process in element order)
- **IN_FLIGHT**: (VPU stores) Writes sent, waiting for responses
- **COMPLETE**: Done, slot reusable

### Ordered Load Flow

1. Lamlet dispatches LoadIndexedElement to kamlet
2. Kamlet computes addr from index reg, sends ADDR message to lamlet
3. Lamlet buffers in OrderedBuffer, waits for element's turn
4. When turn comes:
   - **Scalar memory**: lamlet reads via HellaCacheInterface
   - **VPU memory**: lamlet sends ReadMemWord to appropriate jamlet
5. On response, mark complete, advance to next element

### Ordered Store Flow

1. Lamlet dispatches StoreIndexedElement to kamlet
2. Kamlet computes addr from index reg, reads data from RF, sends ADDR+DATA to lamlet
3. Lamlet buffers, waits for turn
4. When turn comes:
   - **Scalar memory**: lamlet writes via HellaCacheInterface
   - **VPU memory**: lamlet sends WriteMemWord to appropriate jamlet
5. On ack, mark complete, advance

### Lamlet State

- `ordered_buffers[N]` - support multiple concurrent ordered ops (N = parameter)
- Each buffer: element states, addresses, data
- HellaCacheInterface port for scalar memory access

### Barrier Instructions

Before ordered indexed ops, lamlet broadcasts OrderedIndexedLoad/Store barrier to all kamlets.
This creates a waiting item that blocks until previous writes complete, ensuring ordering.

## Memlet DRAM Interface

Each memlet has its own dedicated DRAM interface (not shared with scalar memory).

Simple request/response interface (following Saturn's pattern):

```
read_line_req:  addr →
read_line_resp: ← data

write_line_req: addr + data + mask →
write_line_ack: ← done
```

Physical DRAM controller (AXI, DDR PHY, etc.) is an implementation detail outside the VPU design.
