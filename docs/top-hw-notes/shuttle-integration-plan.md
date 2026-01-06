# Plan: End-to-End Skeleton with Shuttle Integration

## Goal
Run a simple RISC-V kernel that sends a vector load and store through Zamlet, following Saturn's integration pattern.

## Key Decisions (Confirmed)
1. **Use Shuttle/RocketChip libraries** - import from `freechips.rocketchip`, `shuttle.common` (like Saturn does)
2. **Shuttle core in RTL from day 1** - not mocking the interface
3. **Cocotb for testing** - provides memory, loads binaries
4. **Standalone dependencies** - add Shuttle/RocketChip as Bazel deps, not full Chipyard

## Understanding from Exploration

### Saturn's Pattern
- `SaturnShuttleUnit extends ShuttleVectorUnit` (from Shuttle library)
- Imports from `freechips.rocketchip.rocket._`, `shuttle.common._`
- Uses `CoreBundle`, `VConfig`, `ShuttleVectorCoreIO` directly

Key interface signals (`ShuttleVectorCoreIO`):
- `ex` - instruction dispatch (valid, uop, vconfig, vstart, ready, fire)
- `mem` - TLB access (tlb_req/tlb_resp), FP operands
- `com/wb` - commit stage, scalar_check, exceptions
- `resp` - scalar results back to core
- `set_vstart/vxsat/vconfig/fflags` - CSR updates
- `backend_busy`, `trap_check_busy`

### Saturn's Modules
```
SaturnShuttleUnit extends ShuttleVectorUnit
├── VectorDispatcher - routes instructions
├── SaturnShuttleFrontend - decode, fault check
├── VectorBackend - execution units
├── VectorMemUnit - load/store queues
└── TLSplitInterface - TileLink memory
```

### Current Zamlet State
- Jamlet: Network routing done, WitemMonitor partially implemented (16-stage pipeline)
- Missing: Lamlet, Kamlet, Memlet, SRAM, RfSlice

## Architecture

### Test Harness Structure
```
Cocotb Testbench
├── Provides: Clock, Reset
├── Scalar Memory Model (TileLink) - instruction fetch, scalar data
├── VPU Memory Model - dedicated VPU DRAM interface (per memlet)
├── Loads: RISC-V binary into scalar memory, test data into VPU memory
└── Observes: Memory accesses, completion signals

Top-Level RTL (ZamletTile or similar)
├── Shuttle Core (scalar RISC-V)
│   └── TileLink → Scalar Memory (cocotb)
├── ZamletShuttleUnit extends ShuttleVectorUnit
│   ├── Lamlet (instruction decode, dispatch)
│   ├── Kamlet[] (tile clusters)
│   │   └── Jamlet[] (lanes)
│   └── Memlet[] → VPU Memory (cocotb)
└── Two separate memory interfaces exposed to testbench
```

### Memory Interfaces for Cocotb

1. **Scalar Memory (TileLink)**
   - Instruction fetch
   - Scalar load/store
   - Standard TileLink protocol

2. **VPU Memory (Memlet interface)**
   - Vector load/store data
   - Dedicated per-memlet (not shared with scalar)
   - Simpler interface than TileLink (read_line_req/resp, write_line_req/ack)
   - Cocotb provides memory model responding to memlet requests

## Implementation Phases

### Phase 1: Shuttle Standalone with Cocotb

Get Shuttle running by itself with cocotb before adding Zamlet:
- Add Shuttle/RocketChip as Bazel deps (or local paths)
- Generate Verilog for a minimal Shuttle tile (no vector unit)
- Create cocotb test that:
  - Drives TileLink memory interface
  - Loads a simple RISC-V binary (e.g., loop that writes to memory)
  - Verifies scalar core executes correctly

This proves: Bazel build works, Verilog generation works, cocotb+TileLink works.

Files:
- BUILD updates for Shuttle/RocketChip deps
- `src/main/scala/zamlet/tile/ShuttleTestTile.scala` (minimal Shuttle config)
- `python/zamlet/tile_test/test_shuttle_standalone.py`
- `python/zamlet/tile_test/tilelink_model.py`

### Phase 2: ZamletShuttleUnit Skeleton

Create our vector unit that extends ShuttleVectorUnit:

```scala
class ZamletShuttleUnit(implicit p: Parameters) extends ShuttleVectorUnit {
  // Like SaturnShuttleUnit but with our backend
}
```

Files:
- `src/main/scala/zamlet/shuttle/Integration.scala` (ZamletShuttleUnit)
- `src/main/scala/zamlet/shuttle/Frontend.scala` (ZamletShuttleFrontend)

Initially: Accept instructions, return `backend_busy=false`, do nothing.

### Phase 3: Minimal Lamlet

Decode RISC-V vector instructions, generate kinstrs:
- Decode vle/vse (unit-stride load/store)
- Generate kinstr for kamlet
- Track instruction completion

Files:
- `src/main/scala/zamlet/lamlet/Lamlet.scala`
- `src/main/scala/zamlet/lamlet/IssueUnit.scala`

### Phase 4: Minimal Kamlet

Receive kinstrs, create witems:
- Simple instruction queue
- Create witem in jamlet table
- Signal completion back

Files:
- `src/main/scala/zamlet/kamlet/Kamlet.scala`

### Phase 5: Memlet (VPU Memory Interface)

Simple memory interface for VPU DRAM:
- Read/write cache line requests
- Exposed to cocotb as testbench interface
- Initially just one memlet

Files:
- `src/main/scala/zamlet/memlet/Memlet.scala`
- `src/main/scala/zamlet/memlet/MemletParams.scala`

### Phase 6: Complete Jamlet Load Path

Wire WitemMonitor to do a real load:
- RF slice for vector register storage
- Process witem: request from memlet, write to RF
- Connect to memlet for memory access

Files:
- `src/main/scala/zamlet/jamlet/RfSlice.scala`
- Updates to existing Jamlet files

### Phase 7: Top-Level Tile + Cocotb Harness

Create a tile that combines Shuttle + Zamlet:
- Based on `ShuttleTile` but with our vector unit
- Expose both memory interfaces for cocotb
- Generate Verilog

Cocotb test:
- Scalar memory model (TileLink) - serves instruction fetch + scalar data
- VPU memory model (Memlet interface) - serves vector load/store
- Load RISC-V binary into scalar memory
- Pre-populate VPU memory with test data
- Verify vector load moves data from VPU memory → RF

Files:
- `src/main/scala/zamlet/tile/ZamletTile.scala` (or config)
- `python/zamlet/tile_test/test_vector_load.py`
- `python/zamlet/tile_test/tilelink_model.py` (TileLink responder)
- `python/zamlet/tile_test/memlet_model.py` (VPU memory responder)

## First Milestone Target

Simple program that does:
```c
// data lives in VPU memory (address in VPU DRAM range)
#define VPU_MEM_BASE 0x80000000
volatile uint8_t *data = (uint8_t*)VPU_MEM_BASE;

void test() {
    // cocotb pre-populates VPU memory: data[0..7] = {1,2,3,4,5,6,7,8}
    asm volatile("vsetivli t0, 8, e8, m1");
    asm volatile("vle8.v v1, (%0)" :: "r"(data));
    // v1 should now contain {1,2,3,4,5,6,7,8}
}
```

Data flow:
1. Cocotb pre-populates VPU memory with test data
2. Shuttle executes vle8.v instruction
3. ZamletShuttleUnit receives instruction via ShuttleVectorCoreIO
4. Lamlet decodes, dispatches kinstr to kamlet
5. Kamlet creates witem in jamlet
6. Jamlet requests data from memlet
7. Memlet requests from VPU memory (cocotb responds)
8. Data written to jamlet RF slice

Success criteria: Data appears in correct jamlet RF slice.

## Risks & Notes

1. **Bazel + RocketChip**: RocketChip typically uses SBT. Getting it to work as a Bazel dep may require some effort. Fallback: use local sbt-compiled JARs.
2. **Cocotb + TileLink**: TileLink protocol is complex. May need a simple wrapper/adapter or use existing cocotb-TileLink helpers if available.
3. **Scope creep**: Resist temptation to add features. First milestone is just one unit-stride load working.
