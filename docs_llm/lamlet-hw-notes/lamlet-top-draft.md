# Lamlet Top Module (First Draft)

Wires together the lamlet submodules and connects to external interfaces.

## Block Diagram

```
                    ShuttleVectorCoreIO
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         │    ┌────────────▼────────────┐    │
         │    │        IssueUnit        │    │
         │    │  decode, TLB, kinstr gen│    │
         │    └────────────┬────────────┘    │
         │                 │ kinstr (no ident)
         │                 │ k_index
         │                 ▼                 │
         │    ┌────────────────────────┐     │
         │    │      IdentTracker      │◄────┼─── sync_result (from Synchronizer)
         │    │  fill ident, tokens    │────►│    sync_local_event
         │    │  inject IdentQuery     │     │
         │    └────────────┬───────────┘     │
         │                 │ kinstr (with ident)
         │                 │ k_index
         │                 ▼                 │
         │    ┌────────────────────────┐     │
         │    │     DispatchQueue      │     │
         │    │  batch, gen packets    │     │
         │    └────────────┬───────────┘     │
         │                 │ network words
         │                 ▼                 │
         │    ┌────────────────────────┐     │
         │    │      Ch0Sender         │     │
         │    │    (passthrough)       │─────┼───► io_mesh
         │    └────────────────────────┘     │
         │                                   │
         │    ┌────────────────────────┐     │
         │    │     Synchronizer       │◄────┼───► io_sync (8 neighbor ports)
         │    │   (lamlet at 0,-1)     │     │
         │    └────────────────────────┘     │
         │                                   │
         │    backend_busy ◄── IdentTracker  │
         │    retire_late  ◄── IssueUnit     │
         └───────────────────────────────────┘
```

## External Interfaces

```
Lamlet

// Scalar core interface (from Shuttle)
├── IO:  io.core: ShuttleVectorCoreIO
│        ├── ex.valid, ex.uop, ex.vconfig, ex.vstart
│        ├── ex.ready
│        ├── mem.tlb_req, mem.tlb_resp
│        ├── wb.retire_late, wb.inst, wb.xcpt, ...
│        └── backend_busy

// Mesh network (packet output)
├── OUT: io_mesh.valid
├── OUT: io_mesh.bits      (network word)
├── IN:  io_mesh.ready

// Sync network (8 neighbor ports, directly wired)
├── IO:  io_sync.port_s.out.valid, io_sync.port_s.out.bits[8:0]
├── IO:  io_sync.port_s.in.valid, io_sync.port_s.in.bits[8:0]
```

Note: Lamlet only connects S to kamlet (0,0). Other directions unused.

## Submodule Instantiation

```scala
val issueUnit = Module(new IssueUnit)
val identTracker = Module(new IdentTracker)
val dispatchQueue = Module(new DispatchQueue)
val synchronizer = Module(new Synchronizer(x=0, y=-1))  // lamlet position
```

## Wiring

```scala
// IssueUnit ← Shuttle
issueUnit.io.ex <> io.core.ex
issueUnit.io.tlb_req <> io.core.mem.tlb_req
issueUnit.io.tlb_resp := io.core.mem.tlb_resp

// IssueUnit → IdentTracker
identTracker.io.in <> issueUnit.io.kinstr_out

// IdentTracker → DispatchQueue
dispatchQueue.io.in <> identTracker.io.out

// DispatchQueue → Mesh (Ch0Sender is just passthrough)
io_mesh <> dispatchQueue.io.out

// Synchronizer ← → IdentTracker
identTracker.io.sync_local_event <> synchronizer.io.local_event
identTracker.io.sync_result <> synchronizer.io.result

// Synchronizer ← → External sync network
synchronizer.io.port_s <> io_sync.port_s

// Status signals
io.core.backend_busy := identTracker.io.backend_busy

// Retire (immediate on dispatch, post-commit model)
io.core.wb.retire_late := issueUnit.io.retire_late
io.core.wb.inst := issueUnit.io.retire_inst
io.core.wb.xcpt := issueUnit.io.xcpt
// ... other wb signals
```

## Ch0Sender

For first draft, Ch0Sender is just a wire:
```scala
io_mesh <> dispatchQueue.io.out
```

Future: Ch0Sender will multiplex packets from multiple sources (e.g., responses to scalar
memory requests from mesh).

## First Draft Scope

**Included:**
- IssueUnit: unit-stride vle/vse only
- IdentTracker: full implementation
- DispatchQueue: batching + packet generation
- Synchronizer: full implementation

**Stubbed/Omitted:**
- Ch0Receiver: not needed (IdentQuery response via sync network)
- FaultChecker: unit-stride faults checked inline
- Scalar memory path: no VPU↔scalar memory
- Exception aggregation: just fail on first fault

## Parameters

```scala
case class ZamletParams(
    k_cols: Int,
    k_rows: Int,
    instruction_queue_length: Int = 8,
    max_response_tags: Int = 128,
    // ... passed to submodules
)
```
