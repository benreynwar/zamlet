# Instruction Set Architecture

The Zamlet ISA implements a VLIW (Very Long Instruction Word) SIMT (Single Instruction, Multiple Thread) architecture with 6 parallel instruction slots per bundle.

## VLIW Bundle Format

Each instruction bundle contains exactly 6 slots executed in parallel:

```
┌─────────────┬───────────┬─────────┬──────────┬────────────┬─────────┐
│   Control   │ Predicate │ Packet  │ ALU Lite │ Load/Store │   ALU   │
│   (Flow)    │  (Mask)   │ (Comm)  │ (16-bit) │  (Memory)  │ (32-bit)│
└─────────────┴───────────┴─────────┴──────────┴────────────┴─────────┘
```

## Register File Types

| Type | Count | Width | Purpose |
|------|-------|-------|---------|
| **D** | 16 | 32-bit | Data values, ALU results |
| **A** | 16 | 16-bit | Addresses, loop counters |  
| **P** | 16 | 1-bit | Predicate masks |
| **G** | 16 | 16-bit | Global shared values |

## Instruction Types

### ALU Instructions (32-bit Data Path)

Operations on D-registers with 32-bit precision.

| Instruction | Operands | Description |
|------------|----------|-------------|
| `ADD` | `rd, rs1, rs2` | `rd = rs1 + rs2` |
| `SUB` | `rd, rs1, rs2` | `rd = rs1 - rs2` |
| `MUL` | `rd, rs1, rs2` | `rd = rs1 × rs2` |
| `AND` | `rd, rs1, rs2` | `rd = rs1 & rs2` |
| `OR` | `rd, rs1, rs2` | `rd = rs1 \| rs2` |
| `XOR` | `rd, rs1, rs2` | `rd = rs1 ^ rs2` |
| `SLL` | `rd, rs1, shamt` | `rd = rs1 << shamt` |
| `SRL` | `rd, rs1, shamt` | `rd = rs1 >> shamt` |

**Register Access:** Reads from D-registers, writes to A- or D-registers  
**Implementation:** [`src/main/scala/zamlet/amlet/ALUInstruction.scala`](../src/main/scala/zamlet/amlet/ALUInstruction.scala)

### ALU Lite Instructions (16-bit Address Path)

Lightweight operations on A-registers for address computation.

| Instruction | Operands | Description |
|------------|----------|-------------|
| `ADD` | `rd, rs1, rs2` | `rd = rs1 + rs2` |
| `SUB` | `rd, rs1, rs2` | `rd = rs1 - rs2` |
| `MUL` | `rd, rs1, rs2` | `rd = rs1 × rs2` |
| `AND` | `rd, rs1, rs2` | `rd = rs1 & rs2` |
| `OR` | `rd, rs1, rs2` | `rd = rs1 \| rs2` |
| `XOR` | `rd, rs1, rs2` | `rd = rs1 ^ rs2` |

**Register Access:** Reads from A-registers, writes to A- or D-registers  
**Implementation:** [`src/main/scala/zamlet/amlet/ALULiteInstruction.scala`](../src/main/scala/zamlet/amlet/ALULiteInstruction.scala)

### Predicate Instructions

Generate conditional execution masks for SIMT control flow.

| Instruction | Operands | Description |
|------------|----------|-------------|
| `LT` | `pd, src1, src2, pmask` | `pd = (src1 < src2) && pmask` |
| `LTE` | `pd, src1, src2, pmask` | `pd = (src1 <= src2) && pmask` |
| `GT` | `pd, src1, src2, pmask` | `pd = (src1 > src2) && pmask` |
| `GTE` | `pd, src1, src2, pmask` | `pd = (src1 >= src2) && pmask` |
| `EQ` | `pd, src1, src2, pmask` | `pd = (src1 == src2) && pmask` |
| `NEQ` | `pd, src1, src2, pmask` | `pd = (src1 != src2) && pmask` |

**Operand Constraints:**
- `src1`: Immediate, loop index, or G-register
- `src2`: A-register  
- `pmask`: Base predicate (P-register)
- `pd`: Destination predicate (P-register)

**Implementation:** [`src/main/scala/zamlet/amlet/PredicateInstruction.scala`](../src/main/scala/zamlet/amlet/PredicateInstruction.scala)

### Control Instructions

Hardware-accelerated loop control and program flow.

| Instruction | Operands | Description |
|------------|----------|-------------|
| `LoopImmediate` | `body_len, iterations` | Loop with immediate iteration count |
| `LoopLocal` | `body_len, areg` | Loop with A-register iteration count |
| `LoopGlobal` | `body_len, greg` | Loop with G-register iteration count |
| `Halt` | - | Terminate execution |

**Loop Semantics:**
- `body_len`: Number of instruction bundles in loop body
- For `LoopLocal`: Iterations = max(A-register value across all Amlets)
- Predicates must mask execution for correct per-Amlet iteration counts
- Nested loops supported

**Implementation:** [`src/main/scala/zamlet/amlet/ControlInstruction.scala`](../src/main/scala/zamlet/amlet/ControlInstruction.scala)

### Load/Store Instructions

Aligned memory access operations.

| Instruction | Operands | Description |
|------------|----------|-------------|
| `Load` | `rd, addr, offset` | `rd = memory[addr + offset]` |
| `Store` | `addr, offset, data` | `memory[addr + offset] = data` |

**Register Access:**
- `addr`: A-register (base address)
- `offset`: Immediate offset  
- `data`/`rd`: A- or D-register

**Alignment:** All accesses must be naturally aligned
**Implementation:** [`src/main/scala/zamlet/amlet/LoadStoreInstruction.scala`](../src/main/scala/zamlet/amlet/LoadStoreInstruction.scala)

### Packet Instructions

Inter-processor communication via mesh network.

| Instruction | Operands | Description |
|------------|----------|-------------|
| `Receive` | `len_reg, channel` | Start receiving packet |
| `GetWord` | `data_reg` | Get next word from active packet |
| `Send` | `len_reg, dest_reg, channel` | Send packet to destination |
| `Broadcast` | `len_reg, dest_reg, channel` | Broadcast within rectangle |
| `ReceiveAndForward` | `len_reg, dest_reg, channel` | Receive and forward packet |
| `ReceiveForwardAndAppend` | `len_reg, dest_reg, append_len, channel` | Receive, forward, and append |
| `ForwardAndAppend` | `dest_reg, append_len, channel` | Forward active packet with append |

**Packet Construction:**
- Any write to D-register 0 adds word to outgoing packet
- Packet length must be set before transmission
- Multiple independent channels supported

**Network Routing:** X-Y routing with destination coordinates  
**Implementation:** [`src/main/scala/zamlet/amlet/PacketInstruction.scala`](../src/main/scala/zamlet/amlet/PacketInstruction.scala)

## Instruction Encoding Example

```scala
// VLIW Bundle Example: Parallel execution across 6 slots
Bundle(
  control = LoopImmediate(body_len=4, iterations=100),
  predicate = LT(p1, loop_index, a2, p0),
  packet = Receive(a3, channel=0), 
  alu_lite = ADD(a1, a1, immediate(1)),
  loadstore = Load(d2, a0, offset=4),
  alu = MUL(d1, d2, d3)
)
```

## Dependency Rules

**VLIW Constraint Enforcement:**
1. All reads occur before all writes within a bundle
2. At most one slot may write to any register  
3. Dependency tracker performs minor reordering to enforce constraints

**Inter-Bundle Dependencies:**
- Resolved by register renaming and reservation stations
- Out-of-order execution hides dependency latencies
- No bypassing between slots within same bundle

## Programming Model

### Typical Usage Pattern

```scala
// 1. Setup loop and data
control: LoopLocal(body_len=3, a_iterations)
alu_lite: ADD(a_base, a_base, a_stride) 

// 2. Load data  
loadstore: Load(d_data, a_base, 0)
packet: Receive(d_network, channel=1)

// 3. Compute and predicate
alu: ADD(d_result, d_data, d_network)  
predicate: LT(p_mask, d_result, a_threshold, p_true)

// 4. Store result
loadstore: Store(a_out, 0, d_result) [predicated by p_mask]
```

### Best Practices

1. **Maximize Parallelism:** Fill all relevant VLIW slots
2. **Predicate Efficiently:** Use predicates for SIMT divergence  
3. **Balance Network:** Avoid hotspots in mesh communication
4. **Manage Dependencies:** Compiler or programmer must ensure VLIW constraints

## Implementation Status

✅ **All instruction types implemented**  
✅ **Basic functionality verified**  
🔄 **Complex interaction testing in progress**  
🔄 **Performance optimization ongoing**

The ISA provides a rich set of operations for parallel computation while maintaining the simplicity needed for efficient hardware implementation.