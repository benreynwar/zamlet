# Instruction Set Architecture

The Zamlet ISA implements a VLIW (Very Long Instruction Word) SIMD (Single Instruction,
Multiple Thread) architecture with 6 parallel instruction slots per bundle.

## VLIW Bundle Format

Each instruction bundle contains exactly 6 slots executed in this order:

```
┌─────────────┬───────────┬─────────┬──────────┬────────────┬─────────┐
│   Control   │ Predicate │ Packet  │ ALU Lite │ Load/Store │   ALU   │
│   (Flow)    │  (Mask)   │ (Comm)  │ (16-bit) │  (Memory)  │ (32-bit)│
└─────────────┴───────────┴─────────┴──────────┴────────────┴─────────┘
```

**Execution Order:** Control → Predicate → Packet → ALU Lite → Load/Store → ALU

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
**Implementation:** 
[`src/main/scala/zamlet/amlet/ALUInstruction.scala`](../src/main/scala/zamlet/amlet/ALUInstruction.scala)

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
**Implementation:** 
[`src/main/scala/zamlet/amlet/ALULiteInstruction.scala`](../src/main/scala/zamlet/amlet/ALULiteInstruction.scala)

### Predicate Instructions

Generate conditional execution masks for SIMD control flow.

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

**Implementation:** 
[`src/main/scala/zamlet/amlet/PredicateInstruction.scala`](../src/main/scala/zamlet/amlet/PredicateInstruction.scala)

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

**Implementation:** 
[`src/main/scala/zamlet/amlet/ControlInstruction.scala`](../src/main/scala/zamlet/amlet/ControlInstruction.scala)

### Load/Store Instructions

Aligned memory access operations.

| Instruction | Operands | Description |
|------------|----------|-------------|
| `Load` | `rd, addr` | `rd = memory[addr]` |
| `Store` | `addr, data` | `memory[addr] = data` |

**Register Access:**
- `addr`: A-register (address)
- `data`/`rd`: A- or D-register

**Alignment:** All accesses must be naturally aligned
**Implementation:** 
[`src/main/scala/zamlet/amlet/LoadStoreInstruction.scala`](../src/main/scala/zamlet/amlet/LoadStoreInstruction.scala)

### Packet Instructions

Inter-processor communication via mesh network.

| Instruction | Operands | Description |
|------------|----------|-------------|
| `Receive` | `len_reg, channel` | Start receiving packet |
| `GetWord` | `data_reg` | Get next word from active packet |
| `Send` | `len_reg, dest_reg, channel` | Send packet to destination |
| `Broadcast` | `len_reg, dest_reg, channel` | Broadcast within rectangle |
| `ReceiveAndForward` | `len_reg, dest_reg, channel` | Receive and forward packet |
| `ReceiveForwardAndAppend` | `len_reg, dest_reg, append_len, channel` | Receive, forward, append |
| `ForwardAndAppend` | `dest_reg, append_len, channel` | Forward active packet with append |

**Packet Construction:**
- Any write to D-register 0 adds word to outgoing packet
- Packet length must be set before transmission
- Multiple independent channels supported

**Network Routing:** X-Y routing with destination coordinates  
**Implementation:** 
[`src/main/scala/zamlet/amlet/PacketInstruction.scala`](../src/main/scala/zamlet/amlet/PacketInstruction.scala)

## Instruction Encoding

See [detailed examples](#instruction-encoding-examples) at the end of this document.

## Instruction Encoding Examples

### Scala Implementation

```scala
// VLIW Bundle: Parallel execution across all 6 slots
val bundle = Wire(new VLIWInstr.Base(params))

// Control: Loop with immediate iteration count
bundle.control.mode := ControlInstr.Modes.LoopImmediate
bundle.control.length := 4.U
bundle.control.iterations := 100.U

// Predicate: Compare and set mask  
bundle.predicate.mode := PredicateInstr.Modes.Lt
bundle.predicate.dst := 1.U       // P-register 1
bundle.predicate.src1.mode := PredicateInstr.Src1Mode.LoopIndex
bundle.predicate.src2 := 2.U      // A-register 2
bundle.predicate.base := 0.U      // P-register 0 (base mask)

// Packet: Receive from network
bundle.packet.mode := PacketInstr.Modes.Receive
bundle.packet.length := 3.U       // A-register 3 (length)
bundle.packet.channel := 0.U

// ALU Lite: Increment address
bundle.aluLite.mode := ALULiteInstr.Modes.Add
bundle.aluLite.dst := 1.U         // A-register 1
bundle.aluLite.src1 := 1.U        // A-register 1
bundle.aluLite.src2 := 0.U        // A-register 0 (contains 1)

// Load/Store: Load from memory
bundle.loadStore.mode := LoadStoreInstr.Modes.Load
bundle.loadStore.reg := 2.U       // D-register 2 (destination)
bundle.loadStore.addr := 0.U      // A-register 0 (base address)

// ALU: Multiply data values  
bundle.alu.mode := ALUInstr.Modes.Mult
bundle.alu.dst := 1.U             // D-register 1
bundle.alu.src1 := 2.U            // D-register 2
bundle.alu.src2 := 3.U            // D-register 3
```

### Python Interface

```python
from zamlet.amlet.instruction import VLIWInstruction
from zamlet.amlet.control_instruction import ControlInstruction, ControlModes
from zamlet.amlet.predicate_instruction import PredicateInstruction, PredicateModes, Src1Mode
from zamlet.amlet.packet_instruction import PacketInstruction, PacketModes
from zamlet.amlet.alu_lite_instruction import ALULiteInstruction, ALULiteModes
from zamlet.amlet.ldst_instruction import LoadStoreInstruction, LoadStoreModes
from zamlet.amlet.alu_instruction import ALUInstruction, ALUModes

# Create VLIW instruction bundle
instruction = VLIWInstruction(
    # Control: Loop 100 times with 4-instruction body
    control=ControlInstruction(
        mode=ControlModes.LOOP_IMMEDIATE,
        body_len=4,
        immediate_value=100
    ),
    
    # Predicate: Set mask based on loop index comparison
    predicate=PredicateInstruction(
        mode=PredicateModes.LT,
        dst=1,                    # P-register 1
        src1_mode=Src1Mode.LOOP_INDEX,
        src2=2,                   # A-register 2
        src_predicate=0           # P-register 0 (base mask)
    ),
    
    # Packet: Receive data from network channel 0
    packet=PacketInstruction(
        mode=PacketModes.RECEIVE,
        reg=3,                    # A-register 3 (length)
        channel=0
    ),
    
    # ALU Lite: Increment address register
    alu_lite=ALULiteInstruction(
        mode=ALULiteModes.ADD,
        dst=1,                    # A-register 1
        src1=1,                   # A-register 1  
        src2=0                    # A-register 0 (step size)
    ),
    
    # Load/Store: Load from computed address
    load_store=LoadStoreInstruction(
        mode=LoadStoreModes.LOAD,
        d_reg=2,                  # D-register 2 (destination)
        addr=0                    # A-register 0 (address)
    ),
    
    # ALU: Multiply loaded data
    alu=ALUInstruction(
        mode=ALUModes.MULT,
        dst=1,                    # D-register 1
        src1=2,                   # D-register 2
        src2=3                    # D-register 3
    )
)
```
