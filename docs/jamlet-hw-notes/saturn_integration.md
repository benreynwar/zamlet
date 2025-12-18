# Saturn/RocketChip Integration

## Decision

Adopt RocketChip ecosystem for:
- Scalar core interface (Rocket/BOOM integration)
- hardfloat library for FP units
- Chipyard build infrastructure

## What We Reuse from Saturn

| Component | Reuse Level | Notes |
|-----------|-------------|-------|
| `VectorCoreIO` | Direct | Interface to scalar core |
| hardfloat | Direct | FP units (MulAddRecFNPipe, etc.) |
| Chipyard ecosystem | Direct | Build, sim, FPGA flows |
| AdderArray pattern | Adapt | Strip deps, use carry-masking concept |
| CompareArray pattern | Adapt | Strip deps |
| TandemFMAPipe | Adapt | May simplify for our needs |

## What We Replace

| Saturn Component | Our Replacement | Reason |
|------------------|-----------------|--------|
| VectorBackend | Kamlet/Jamlet mesh | Different execution model |
| Frontend (fault check) | Distributed in mesh | Our TLB/fault is distributed |
| VectorDispatcher | Lamlet dispatcher | Different instruction flow |
| VectorMemUnit | Memlet mesh nodes | Mesh-based memory interface |

## Saturn Structure (for reference)

```
SaturnRocketUnit (extends RocketVectorUnit)
├── VectorDispatcher      - instruction dispatch
├── SaturnRocketFrontend  - decode, fault check, TLB
│   ├── PipelinedFaultCheck
│   └── IterativeFaultCheck
├── VectorBackend         - execution
│   ├── RegisterFile
│   ├── Sequencers
│   └── ExecutionUnits
└── VectorMemUnit         - memory interface
    └── TLSplitInterface (TileLink)
```

## Our Structure (proposed)

```
ZamletRocketUnit (extends RocketVectorUnit)
├── ZamletFrontend        - instruction decode, dispatch to lamlet
│   └── (simplified - no centralized fault check)
├── Lamlet                - top-level VPU
│   ├── TLB (distributed)
│   ├── Kamlet[]          - tile clusters
│   │   └── Jamlet[]      - lanes (our execution)
│   └── Memlet[]          - memory interfaces
└── MemoryInterface       - TileLink adapter
```

## Key Interfaces

### VectorCoreIO (from RocketChip)

Saturn's scalar core interface - we keep this:

```scala
class VectorCoreIO extends Bundle {
  val ex = new Bundle {           // Execute stage
    val valid: Bool
    val inst: UInt
    val pc: UInt
    val vconfig: VConfig
    val vstart: UInt
    val rs1, rs2: UInt
    val ready: Bool               // Output: VPU ready
  }
  val mem = new Bundle { ... }    // Memory stage
  val wb = new Bundle { ... }     // Writeback stage
  val status: MStatus
  val resp: ScalarWrite           // Scalar result to core
  // CSR interfaces...
}
```

### TLB Interface

Saturn uses centralized TLB access. We need to adapt:
- Saturn: `io.tlb <> DCacheTLBPort` in frontend
- Ours: TLB queries distributed from kamlets/jamlets

**RISC-V spec on TLB coherence** (supervisor.adoc, lines 1607-1616):

> "The results of implicit address-translation reads in step 2 may be held
> in a read-only, incoherent _address-translation cache_ but not shared
> with other harts. ... To ensure that implicit reads observe writes to the
> same memory locations, an SFENCE.VMA instruction must be executed after
> the writes to flush the relevant cached translations."

Key points:
- TLB is explicitly "read-only, incoherent" - no hardware coherence required
- Software executes SFENCE.VMA after modifying page tables
- Between modification and SFENCE, old or new translation may be used (not undefined)
- TLB shootdown between harts is software-coordinated (IPIs + SFENCE.VMA)

**Implications for our distributed TLB:**
- Each kamlet can cache translations locally - no coherence protocol needed
- SFENCE.VMA on scalar core must broadcast "flush all" to entire VPU mesh
- During vector instruction execution, page tables assumed stable
- Simple design: distributed read-only caches, global invalidate on SFENCE.VMA

### Memory Interface

Saturn uses TileLink via `TLSplitInterface`. We can:
1. Adapt memlets to speak TileLink
2. Use memlet mesh internally, TileLink adapter at edge

## Dependencies to Add

```scala
// build.sbt additions
libraryDependencies ++= Seq(
  "org.chipsalliance" %% "rocketchip" % "...",
  "edu.berkeley.cs" %% "hardfloat" % "...",
)
```

## Files to Study in Saturn

Key files for understanding integration:
- `src/main/scala/rocket/Integration.scala` - Rocket integration
- `src/main/scala/rocket/Frontend.scala` - Frontend to core
- `src/main/scala/common/Parameters.scala` - Config system
- `src/main/scala/common/Bundles.scala` - Common data types
- `src/main/scala/exu/FunctionalUnit.scala` - FU patterns
- `src/main/scala/exu/int/IntegerPipe.scala` - Integer SIMD
- `src/main/scala/exu/fp/FPFMAPipe.scala` - FP units

## Next Steps

1. Set up Chipyard environment with Saturn as reference
2. Define Zamlet parameters matching our Python model
3. Implement scalar core interface (VectorCoreIO adapter)
4. Build jamlet with ALU using hardfloat
5. Integrate with kamlet/lamlet hierarchy
6. Adapt memory interface to TileLink
