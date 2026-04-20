# ALU Design

## Overview

The ALU performs arithmetic/logic operations on the register file slice. Operations are driven
by kamlet instructions and execute element-wise with masking support.

## Operations Required

From `python/zamlet/kamlet/kinstructions.py`:

### Integer Arithmetic (VArithVvOp, VArithVxOp)
- **ADD**: dst = src1 + src2
- **MUL**: dst = src1 * src2
- **MACC**: dst = dst + (src1 * src2)
- Element widths: 8, 16, 32, 64 bits
- VV form: both operands from RF
- VX form: one operand is scalar (broadcast)

### Floating Point (VArithVxOp with is_float=True)
- ADD, MUL, MACC
- Element widths: 32 (float), 64 (double)

### Reductions (VreductionVsOp)
- SUM, MAXU, MAX, MINU, MIN, AND, OR, XOR
- Note: Reductions need kamlet-level coordination (reduce across all jamlets)

### Comparison (VmsleViOp)
- Signed less-than-or-equal: result_bit = (src <= simm5)
- Produces 1-bit per element into mask register

### Mask Operations (VmnandMmOp)
- Bitwise NAND: dst = ~(src1 & src2)

### Move Operations
- **VBroadcastOp**: Fill vector with scalar value
- **VmvVvOp**: Copy vector to vector

## Saturn-Vectors Reference

`~/Code/saturn-vectors` is an open-source RISC-V VPU with reusable Chisel code.

### Relevant Files

```
src/main/scala/exu/
├── FunctionalUnit.scala      - Base classes: PipelinedFunctionalUnit, IterativeFunctionalUnit
├── ExecutionUnit.scala       - Composes multiple FUs, handles issue/write arbitration
├── int/
│   ├── IntegerPipe.scala     - ADD/SUB, compare, min/max, saturating ops (2-stage)
│   │   └── AdderArray        - Element-wise adder with carry, averaging, saturation
│   │   └── CompareArray      - Element-wise comparison with signed/unsigned
│   │   └── SaturatedSumArray - Saturation clipping
│   ├── BitwisePipe.scala     - AND, OR, XOR, NAND, etc. (1-stage)
│   ├── ShiftPipe.scala       - Shifts, rotates (2-stage)
│   │   └── ShiftArray        - With rounding support
│   ├── ElementwiseMultiplyPipe.scala
│   └── SegmentedMultiplyPipe.scala
└── fp/
    ├── FPFMAPipe.scala       - Fused multiply-add
    ├── FPConv.scala          - Format conversions
    └── FPDiv.scala           - Division
```

### Key Patterns

**PipelinedFunctionalUnit(depth)**:
```scala
abstract class PipelinedFunctionalUnit(val depth: Int) extends FunctionalUnit {
  val io = IO(new PipelinedFunctionalUnitIO(depth))
  // io.pipe(i) gives pipeline stage i data
  // io.write outputs result
  // io.stall for backpressure
}
```

**Array building blocks** (combinatorial, parameterized by dLenB):
- `AdderArray`: handles add/sub with element-width-aware carry propagation
- `CompareArray`: handles eq/lt/le with signed/unsigned variants
- Saturn processes `dLenB` bytes in parallel with SIMD masking

### Adaptation Needed

Saturn's design assumes:
- `dLen`-wide datapath (e.g., 64 bytes) with SIMD parallelism
- RocketChip/RISC-V tooling dependencies
- Micro-op format with fu_sel, pipe_depth, etc.

Our jamlet:
- Processes one word (8 bytes) from RF per cycle
- Element width determines elements per word (1×64b, 2×32b, 4×16b, 8×8b)
- Simpler control flow (kamlet sends op, jamlet executes)

**Potentially reusable**:
- Adder/compare array concepts (adapt width)
- Pipeline stage patterns
- Rounding logic for averaging/scaling

**Needs new design**:
- FP support strategy (shared FPU? per-jamlet?)
- Reduction coordination with kamlet
- Integration with RF read/write ports

## Design Decisions

1. **Control model**: Kamlet sends instruction once, jamlet iterates through elements autonomously
2. **RF ports**: Give everything its own ports (WitemMonitor, RxCh0/1, ALU). May add arbitration later.
3. **Reductions**: Done through message passing between jamlets (fits existing infrastructure)
4. **Pipelining**: ALU is pipelined
5. **Dependencies**: Adopt RocketChip ecosystem for scalar core interface and hardfloat for FP
6. **SIMD parallelism**: Process multiple small-ew elements per cycle (8×8b / 4×16b / 2×32b / 1×64b)

## Architecture Implications

**Jamlet-autonomous iteration**:
- Jamlet stores instruction (op, dst_reg, src_regs, element_width, n_elements, mask_reg)
- FSM/counter iterates through elements
- One word (8 bytes) per cycle → 1-8 elements depending on ew

**RF port estimate** (before arbitration):
- WitemMonitor: 1 read, 1 write
- RxCh0/RxCh1: 1 read, 1 write each
- ALU: 2 read (src1, src2), 1 write (dst)
- Total: ~5 read, ~4 write (may consolidate later)

**Reduction via messages**:
- Each jamlet computes partial result
- Messages pass partial results (tree or chain topology)
- Final result written to one jamlet's RF

## Integer SIMD Approach (from Saturn)

Saturn uses carry masking to do multiple small-ew ops with one adder:

```scala
// AdderArray: single wide adder, carries masked at element boundaries
val use_carry = VecInit.tabulate(4)({ eew =>
  Fill(dLenB >> eew, ~(1.U((1 << eew).W)))
})(io.eew)
```

For our 8-byte word:
- eew=0 (8-bit): 8 independent adds
- eew=1 (16-bit): 4 independent adds
- eew=2 (32-bit): 2 independent adds
- eew=3 (64-bit): 1 add

## FP Approach (from Saturn)

Saturn uses hardfloat library with separate FMA units per precision:

```scala
// TandemFMAPipe instantiates:
// - 1× FP64 MulAddRecFNPipe
// - 2× FP32 MulAddRecFNPipe
// - 4× FP16 MulAddRecFNPipe
// Only one set active at a time based on eew
```

FP can't share hardware like integers (exponent/mantissa handling differs per format).
Pipeline depth minimum 4 cycles for FMA.

## Instruction Delivery

The `witemCreate` port becomes a general **instruction port** from kamlet→jamlet.
Instruction types:
- Witem create (protocol operations)
- ALU operation (arithmetic on RF)

Jamlet decodes instruction type, routes to WitemTable or ALU accordingly.

## Open Questions

1. Pipeline depths per operation? (ADD=1?, MUL=2-3?, FP FMA=4+)
2. Reduction message protocol design?
