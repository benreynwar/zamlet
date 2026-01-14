# Lamlet First Draft Plan

## Overview

The lamlet is the integration point between Shuttle and the mesh. It receives vector instructions
from Shuttle, generates kinstrs, dispatches them to the mesh, and tracks completions.

This document plans a minimal first implementation.

## Key Constraint

We **cannot** wait for one instruction to complete before starting the next. Multiple instructions
must be in flight. The lamlet must:

1. Accept new instructions from Shuttle while previous ones are still executing
2. Track multiple outstanding instructions
3. Report completions as they arrive

## Python Model Reference

From `python/zamlet/lamlet/lamlet.py`:

```
instruction_buffer: Deque    # Queued kinstrs waiting to be sent
waiting_items: List          # In-flight instructions awaiting completion
next_instr_ident: int        # Allocator for instruction IDs (wraps at max_response_tags)
```

Flow:
1. Vector instruction arrives (vle8.v)
2. Lamlet decodes, allocates instr_ident, creates kinstr
3. Kinstr added to instruction_buffer
4. monitor_instruction_buffer() batches and sends to mesh
5. Mesh executes, sends completion with instr_ident
6. Lamlet matches completion to waiting_item
7. Reports completion to Shuttle

## Shuttle Interface

The lamlet receives instructions via `ShuttleVectorCoreIO.ex` and reports completions via
`ShuttleVectorCoreIO.com`.

Key signals:
- `ex.valid/ready/fire` - instruction handshake
- `ex.uop.inst` - 32-bit instruction
- `ex.uop.rs1_data` - base address
- `ex.vconfig` - vl and vtype
- `com.retire_late` - instruction complete
- `com.xcpt` - exception occurred
- `backend_busy` - outstanding work

**Open questions:**
- Does Shuttle expect in-order retirement? (Likely yes for RVV precise exceptions)
- What happens if we're not ready? (Shuttle stalls)

## Mesh Interface

The lamlet connects to the mesh network at position (0, -1), sending packets south into the
mesh. The mesh is a grid of jamlets, each with north/south/east/west network ports.

For first draft, connect to a single point (kamlet 0,0's north port):

```
io_mesh:
  a_out: Decoupled[NetworkWord]   # Instructions to mesh (broadcast)
  a_in:  Flipped(Decoupled[NetworkWord])  # Responses from mesh
  b_out: Decoupled[NetworkWord]   # Requests to mesh
  b_in:  Flipped(Decoupled[NetworkWord])  # Requests from mesh
```

## First Draft Architecture

```
                 ShuttleVectorCoreIO
                        │
          ┌─────────────┴─────────────┐
          │                           │
          ▼                           │
    ┌──────────┐                      │
    │  Decode  │                      │
    └────┬─────┘                      │
         │                            │
         ▼                            │
    ┌──────────┐                      │
    │   TLB    │ ◄── io.mem.tlb_*     │
    └────┬─────┘                      │
         │                            │
         ▼                            │
    ┌──────────┐    ┌────────────┐    │
    │  Kinstr  │───►│ Instr      │    │
    │  Gen     │    │ Buffer     │    │
    └──────────┘    └─────┬──────┘    │
                          │           │
                          ▼           │
                   ┌────────────┐     │
                   │  Dispatch  │─────┼──► io_mesh (network)
                   └────────────┘     │
                                      │
    ┌───────────────┐                 │
    │ IdentTracker  │◄────────────────┼─── io_sync (sync network)
    │               │                 │
    │ next_ident    │                 │
    │ oldest_active │─────────────────┼──► backend_busy
    └───────────────┘                 │
                                      │
    ┌──────────┐                      │
    │  Retire  │──────────────────────┘
    └──────────┘    (immediate on dispatch)
                         io.com.retire_late
```

**Interfaces:**
- `io` (inherited): ShuttleVectorCoreIO - Shuttle handshake, TLB, retire
- `io_mesh`: Network packets to/from mesh (A channel only for first draft)
- `io_sync`: Sync network for IdentQuery (separate from packet network)

**Dispatch logic (simplified DispatchQueue):**
- 2 sources: IdentQuery (high priority), regular kinstrs
- Check tokens before dispatch
- IdentQuery uses reserved token (only needs > 0)
- Regular kinstrs need > 1 token (reserve last for IdentQuery)

## Post-Commit Execution Model

Vector instructions are **post-commit** from the scalar core's perspective. Once the lamlet
accepts an instruction, Shuttle considers it committed. The lamlet immediately signals
`retire_late` - no need to wait for mesh completion.

This works because:
1. Vector loads/stores don't affect scalar memory
2. Results go to vector registers, not scalar registers
3. Scalar execution can continue immediately

The only thing Shuttle needs to know:
- `backend_busy` = true while any vector work outstanding (blocks fences, CSR access)
- Exceptions (can be imprecise for idempotent VPU memory)

**Flow:**
```
1. Shuttle sends vle8.v
2. Lamlet accepts, decodes, generates kinstr
3. Lamlet dispatches kinstr to mesh
4. Lamlet immediately signals retire_late to Shuttle
5. Mesh executes asynchronously
6. backend_busy stays true until all mesh work completes
```

**No completion packet needed for retire.** We just track outstanding work for `backend_busy`.

## Tracking Outstanding Work (backend_busy)

Uses the sync network and IdentQuery mechanism from the Python model.

**How it works:**
1. Each kinstr gets an `instr_ident` (7 bits, wraps at 128)
2. Lamlet tracks `next_instr_ident` (what we've allocated)
3. To find `oldest_active_ident`, lamlet sends IdentQuery via sync network
4. Each kamlet reports its oldest active ident
5. Sync network does MIN aggregation across all kamlets
6. Result returns to lamlet

**backend_busy** = `(next_instr_ident != oldest_active_ident)`

**Two sources of backpressure (both from IdentQuery):**

1. **Ident space**: Can't wrap around and collide with active idents
   ```python
   available_idents = (oldest_active_ident - next_instr_ident) % max_tags - 1
   ```

2. **Kamlet queue tokens**: Each kamlet has limited instruction queue slots
   ```python
   _available_tokens[k] = how many more instructions we can send to kamlet k
   ```

**Token tracking:**
- `available_tokens[k]` - current tokens for kamlet k
- `tokens_used_since_query[k]` - tokens used since last IdentQuery
- `tokens_in_active_query[k]` - will be returned when query completes

When IdentQuery response arrives:
- `oldest_active_ident` updates → frees ident space
- `tokens_in_active_query` added back to `available_tokens` → frees queue space

**Backpressure conditions:**
- `available_idents < 1` → stall (can't allocate ident)
- `available_tokens[k] <= 1` → stall for that kamlet (reserve last token for IdentQuery)

**When to send IdentQuery:**
- `available_idents < max_tags // 2` (idents running low)
- OR `any(available_tokens[k] < threshold)` (any kamlet queue running low)

**Required for first draft:**
- Sync network interface (lamlet ↔ mesh)
- IdentQuery kinstr encoding
- IdentQuery response handling
- Per-kamlet token tracking
- Backpressure logic for `ex.ready`

## First Draft Scope

**Principle:** Build the actual modules from lamlet-top.md with reduced functionality. Don't create
a monolithic "simplified lamlet" that needs refactoring later.

**Modules to implement (matching full plan structure):**

| Module | First Draft Functionality |
|--------|---------------------------|
| IssueUnit | Decode unit-stride vle/vse only, single TLB lookup, no BLOCKING stage |
| IdentTracker | Full implementation - ident allocation, token tracking, IdentQuery generation |
| Synchronizer | Full implementation - needed for IdentQuery |
| DispatchQueue | 2 inputs (IdentQuery, IssueUnit), no OrderedBuffer |
| Ch0Sender | Send instruction packets |
| Ch0Receiver | Receive IdentQuery responses |

**Modules stubbed/omitted:**
| Module | Status |
|--------|--------|
| FaultChecker | Omit (unit-stride checks inline) |
| FlagCollector | Stub (no vxsat/fflags) |
| Disambiguator | Omit (no scalar memory) |
| VpuToScalarMem | Omit |
| ScalarToKinstr | Omit |
| Ch1Sender/Receiver | Omit (no B channel) |
| OrderedBuffer | Omit |

**Functionality in scope:**
- Accept unit-stride vle/vse from Shuttle
- TLB lookup (use Shuttle's TLB)
- Generate Load/Store kinstr with instr_ident
- IdentQuery flow control (full implementation)
- Per-kamlet token tracking
- Backpressure via `ex.ready`
- `backend_busy` signal
- Immediate `retire_late` (post-commit model)

**Out of scope:**
- Strided/indexed operations
- Masking
- Scalar memory path
- Page boundary splitting
- Exception handling/aggregation

## Kinstr Packet Format

Need to define how kinstrs are encoded in network packets.

From `jamlet/Packet.scala`, packet header is:
- targetX, targetY, sourceX, sourceY (8 bits each)
- length (4 bits)
- messageType (6 bits)
- sendType (2 bits)

MessageType.Instructions (value 1) is for instruction packets.

Kinstr payload needs:
- instr_ident (7 bits)
- opcode (load/store)
- vd/vs3 (5 bits)
- start_index
- n_elements
- k_maddr (kamlet memory address)
- ordering info

**TODO**: Define exact encoding. Look at Python model's packet generation.

## Open Questions

1. **In-order vs out-of-order retirement**: Does Shuttle require in-order? If so, we need
   a reorder buffer or must retire in order.

2. **How many instructions can Shuttle have in flight?** This determines our table size.

3. **TLB timing**: Is response combinational or takes a cycle?

4. **vsetvli handling**: Does Shuttle send it to us or handle internally? Saturn has
   special handling in frontend.

5. **Physical topology**: For first draft, single connection. Later may need multiple
   for bandwidth.

