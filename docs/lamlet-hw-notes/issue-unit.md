# IssueUnit

The IssueUnit converts RISC-V vector instructions into 64-bit kinstrs and dispatches them to the mesh.

## Pipeline Overview

```
DECODE → ADDR + TLB + FAULT → DISPATCH → BLOCKING
```

All four stages are within the IssueUnit. Output is a stream of 64-bit kinstrs to the DispatchQueue.

## Inputs

From VectorCoreIO.ex:
- `inst[31:0]` - Instruction bits
- `rs1`, `rs2` - Scalar register values
- `frs1` - Floating-point scalar (arrives in mem stage)
- `vconfig` - Current vtype + vl
- `vstart` - Starting element

From scalar core:
- `store_pending` - Scalar store buffer not empty

From mesh (for blocking):
- Fault sync responses

## Outputs

- `kinstr[63:0]` - 64-bit kamlet instruction (stream, may be multiple per RISC-V instruction)
- `kinstr_valid` - Kinstr ready to dispatch
- `decode_error` - Illegal instruction

## Pipeline Stages

### DECODE

Parses instruction bits, extracts fields:
- `vd[4:0]` - destination vector register
- `vs1[4:0]`, `vs2[4:0]` - source vector registers
- `vm` - mask enable bit
- `eew[1:0]` - encoded element width
- `mop[1:0]` - addressing mode (for memory ops)
- `nf[2:0]` - number of fields (for segment ops)
- `funct6[5:0]` - operation selector (for compute ops)

Classifies instruction:
- CONFIG (vsetvli)
- COMPUTE (vadd, vmul, etc.)
- UNIT_MEM (vle, vse)
- STRIDED_MEM (vlse, vsse)
- INDEXED_UNORD (vluxei, vsuxei)
- INDEXED_ORD (vloxei, vsoxei)
- SCALAR_RESULT (vmv.x.s)

### ADDR + TLB + FAULT

For memory instructions:
- Compute address from rs1 (+ offset if any)
- TLB lookup → memory type (VPU/scalar), permissions, element width
- For unit stride: check fault for full address range [base, base + vl*eew)
- Determine how to split into kinstrs (page boundaries, cache line boundaries)

### DISPATCH

Generate kinstr(s):
- May produce multiple kinstrs per RISC-V instruction (page splits, strided chunks)
- Each kinstr is 64 bits
- Allocate instruction ident for each kinstr

For each section (from ADDR+TLB+FAULT stage):
- Determine if address is in VPU memory or scalar memory (based on physical address range)
- **VPU memory sections**: Generate Load/Store kinstr → DispatchQueue → mesh
- **Scalar memory sections**:
  - Loads: Send to ScalarLoadQueue
  - Stores: Generate Store kinstr (kamlet sends WriteMemWord to VpuToScalarMem)

Stalls if:
- `store_pending` from scalar core
- Idents exhausted
- DispatchQueue full
- Flow control tokens exhausted
- ScalarLoadQueue full (for scalar memory load sections)
- Register hazard (see below)

### Register Hazard Stalling

IssueUnit checks RegisterScoreboard before dispatching:

| Instruction | Checks | Stalls if |
|-------------|--------|-----------|
| Load (any) | write_blocked[vd] | vd has pending scalar store |
| Store (any) | read_blocked[vs] | vs has pending scalar load |
| Compute | read_blocked[vs1,vs2], write_blocked[vd] | Any source/dest blocked |

When dispatching scalar memory operations, IssueUnit also signals RegisterScoreboard:
- Scalar load: Signal load_start(vd) → blocks reads AND writes to vd
- Scalar store: Signal store_start(vs, n_words) → blocks writes to vs

Kamlets handle register hazards internally for VPU memory operations, so this tracking
is only needed for scalar memory ops where the lamlet controls the timing.

### BLOCKING

Most instructions pass through immediately.

Strided/indexed memory instructions occupy this stage until fault sync received:
- Dispatch kinstr to mesh
- Wait for fault sync from kamlets
- If fault: signal exception, set vstart
- If no fault: release, next instruction proceeds

## Instruction Examples

### vle32.v (unit stride load)

```
DECODE:     Parse, classify as UNIT_MEM
ADDR+TLB:   TLB lookup for [base, base + vl*4)
            Check permissions → OK, no fault
            Determine kinstr split (page boundaries)
DISPATCH:   Generate Load kinstr(s)
BLOCKING:   Pass through (fault already checked)
```

### vlse32.v (strided load)

```
DECODE:     Parse, classify as STRIDED_MEM
ADDR+TLB:   TLB lookup for base page
DISPATCH:   Generate LoadStride kinstr
BLOCKING:   OCCUPIED - wait for fault sync
            Kamlets check faults in parallel
            Release when fault sync complete
```

### vluxei32.v (indexed unordered load)

```
DECODE:     Parse, classify as INDEXED_UNORD
ADDR+TLB:   TLB lookup for base (addresses unknown until kamlets read indices)
DISPATCH:   Generate LoadIndexedUnordered kinstr
BLOCKING:   OCCUPIED - wait for fault sync
            Kamlets report min faulting element (or none)
            Release when fault sync complete
```

### vadd.vv (compute)

```
DECODE:     Parse, classify as COMPUTE
ADDR+TLB:   Nothing (no memory access)
DISPATCH:   Generate VArithVvOp kinstr, broadcast to all kamlets
BLOCKING:   Pass through
```

## Subunits

### Decoder (potential subunit)

Pure combinational logic that parses instruction bits. Could be factored out for clarity.

### TLB Interface

Sends TLB requests, receives responses (memory type, permissions, physical address).
May need multiple lookups for operations spanning pages.

### ScalarLoadQueue Interface

For load sections targeting scalar memory, IssueUnit sends requests to ScalarLoadQueue
instead of generating Load kinstrs directly. See `scalar-load-queue.md` for details.

## Kinstr Format

TODO: Define the 64-bit kinstr encoding.

The kinstr must encode:
- Operation type
- Source/destination registers
- Memory address (for mem ops)
- Element counts/indices
- Mask register reference
- Instruction ident
