# Shuttle Integration Plan

## Goal

Integrate Zamlet with Shuttle (scalar RISC-V core) to run real vector programs.

## Architecture Overview

```
Cocotb Testbench
├── Scalar Memory Model (TileLink) - instruction fetch, scalar data
├── VPU Memory Model - dedicated VPU DRAM interface (per memlet)
└── Loads: RISC-V binary, test data

Top-Level RTL (ZamletTile)
├── Shuttle Core (scalar RISC-V)
│   └── TileLink → Scalar Memory (cocotb)
├── ZamletShuttleUnit extends ShuttleVectorUnit
│   ├── Zamlet
│   │   ├── Lamlet (instruction decode, dispatch)
│   │   └── KamletMesh (compute tiles)
│   └── Memlet[] → VPU Memory (cocotb)
└── ScalarMemPort → Scalar Memory (for vector ops targeting scalar memory)
```

## Two Memory Domains

### Scalar Memory (TileLink)
- Instruction fetch
- Scalar load/store
- Vector ops targeting scalar memory range (via ScalarMemPort)
- Standard TileLink protocol

### VPU Memory (Memlet interface)
- Vector load/store to VPU DRAM
- Dedicated per-memlet (not shared with scalar)
- Simpler interface than TileLink (read_line_req/resp, write_line_req/ack)

## Shuttle Interface (ShuttleVectorCoreIO)

Based on Saturn's integration pattern. Key signals:

### Execute Stage (ex)
```
ex.valid           - instruction ready
ex.uop.inst        - 32-bit instruction
ex.vconfig         - vtype + vl (from vsetvli)
ex.vstart          - starting element
ex.uop.rs1_data    - base address (rs1)
ex.uop.rs2_data    - stride/index (rs2)
ex.ready           - can accept instruction (output)
```

### Memory Stage (mem)
```
mem.tlb_req        - TLB request (vaddr, cmd, size)
mem.tlb_resp       - TLB response (paddr, miss, xcpt)
mem.frs1           - FP scalar operand
mem.block_mem      - block scalar memory ops (output)
mem.block_all      - block all scalar ops (output)
```

### Writeback/Commit Stage (wb)
```
wb.store_pending   - scalar store buffer not empty
wb.retire          - instruction complete (output)
wb.inst            - retiring instruction (output)
wb.xcpt            - exception (output)
wb.cause           - exception cause (output)
wb.tval            - trap value (output)
```

### Scalar Results (resp)
```
resp.valid/ready   - decoupled
resp.rd            - destination register
resp.data          - result data
resp.fp            - is FP result
```

### CSR Updates
```
set_vstart         - update vstart CSR
set_vxsat          - update vxsat CSR
set_vconfig        - update vtype/vl CSRs
set_fflags         - update FP flags
```

### Status
```
backend_busy       - has outstanding work
trap_check_busy    - fault checking in progress
```

## vsetvli Handling

Shuttle handles vsetvli/vsetivli in the scalar pipeline. The result is provided via
`ex.vconfig` for subsequent vector instructions. Zamlet doesn't execute these - just
uses the provided vconfig.

## Integration Class

```scala
class ZamletShuttleUnit(implicit p: Parameters) extends ShuttleVectorUnit {
  // Contains Zamlet + Memlets
  // Bridges ShuttleVectorCoreIO ↔ Lamlet interfaces
}
```

Key imports (following Saturn's pattern):
```scala
import freechips.rocketchip.rocket._
import shuttle.common._
```

## Implementation Phases

### Phase 0: Shuttle Standalone (COMPLETE)
Shuttle running with cocotb, TileLink memory model, simple RISC-V programs.

### Phase 1: ZamletShuttleUnit Skeleton
- Create ZamletShuttleUnit extending ShuttleVectorUnit
- Accept instructions, return backend_busy=false, do nothing
- Verify Shuttle+Zamlet builds and runs

### Phase 2+: Internal Zamlet Implementation
See `docs/lamlet-hw-notes/minimal-load-store-plan.md` for detailed phases:
- Phase 0-1: Kamlet mesh + sync, IdentQuery (COMPLETE)
- Phase 2: Scalar memory load/store (NEXT)
- Phase 3: VPU memory load/store
- Phase 4-5: Memory interface, cache fill

### Final: End-to-End Test
```c
void test() {
    asm volatile("vsetivli t0, 8, e8, m1");
    asm volatile("vle8.v v1, (%0)" :: "r"(data));
    // v1 contains loaded data
}
```

## Files

```
src/main/scala/zamlet/
  shuttle/
    ZamletShuttleUnit.scala    # ShuttleVectorUnit implementation
    ZamletTile.scala           # Tile configuration

  lamlet/
    Zamlet.scala            # Lamlet + KamletMesh (exists)
    ...

  memlet/
    Memlet.scala               # VPU memory interface

python/zamlet/
  shuttle_test/
    test_shuttle_standalone.py # Shuttle-only tests (exists)
    tilelink_model.py          # TileLink responder

  tile_test/
    test_vector_load.py        # End-to-end vector tests
    memlet_model.py            # VPU memory responder
```

## Reference Repositories

Local copies for understanding:
- `~/Code/shuttle` - Shuttle core
- `~/Code/saturn-vectors` - Saturn vector unit (integration patterns)
- `~/Code/rocket-chip` - RocketChip library
- `~/Code/chipyard` - Chipyard SoC framework
