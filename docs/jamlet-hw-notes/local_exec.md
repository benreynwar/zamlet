# LocalExec Design

## Overview

LocalExec handles immediate instructions from kamlet that don't require jamlet-to-jamlet
coordination. These execute directly without entering the jamlet WitemTable.

**Handles:**
- Simple witems (LoadSimple, StoreSimple, WriteImmBytes, ReadByte) - SRAM↔RF transfers
- ALU instructions - RF↔RF operations via ALU
- Reduction ALU ops - the ALU portion of reduction operations (communication handled by
  WitemMonitor)

**Does NOT handle:**
- Protocol witems (J2J, Word, Stride) - these go to WitemTable → WitemMonitor

## Interface

```
LocalExec:

  // From Kamlet (immediate instructions)
  ← instruction        : Valid + instr_type + fields
                         - instr_type: LoadSimple, StoreSimple, WriteImmBytes, ReadByte, AluOp
                         - cache_slot, reg_addr, mem_addr, mask (for Simple types)
                         - alu_op, src1_addr, src2_addr, dst_addr (for ALU)
                         - imm_data (for WriteImmBytes and some ALU ops)

  // To/From SramArbiter (competes with WitemMonitor)
  → sramReq            : Valid + addr + isWrite + writeData + mask
  ← sramGrant          : Bool
  ← sramReadData       : Data

  // To/From RfSlice (competes with WitemMonitor)
  → rfReq              : Valid + addr + isWrite + writeData
  ← rfReadData         : Data

  // To/From ALU (exclusive access)
  → aluReq             : Valid + op + operand1 + operand2
  ← aluResult          : Data

  // Back to Kamlet (optional, for completion tracking)
  → done               : Valid + instr_ident
```

## Operations

### LoadSimple (SRAM → RF)

Aligned load from cache line to register file.

```
1. Receive instruction with cache_slot, reg_addr, mem_addr, mask
2. Compute SRAM address from cache_slot + mem_addr offset
3. Request SRAM read via SramArbiter
4. When granted, receive SRAM data
5. Write data to RfSlice at reg_addr (with mask)
6. Signal done
```

### StoreSimple (RF → SRAM)

Aligned store from register file to cache line.

```
1. Receive instruction with cache_slot, reg_addr, mem_addr, mask
2. Read from RfSlice at reg_addr
3. Compute SRAM address from cache_slot + mem_addr offset
4. Request SRAM write via SramArbiter (with RF data and mask)
5. When granted, signal done
```

### WriteImmBytes (Immediate → SRAM)

Write immediate data to cache line.

```
1. Receive instruction with cache_slot, mem_addr, imm_data, mask
2. Compute SRAM address from cache_slot + mem_addr offset
3. Request SRAM write via SramArbiter (with imm_data and mask)
4. When granted, signal done
```

### ReadByte (SRAM → scalar response)

Read single byte from cache, send response to scalar processor.

```
1. Receive instruction with cache_slot, mem_addr, byte_index
2. Compute SRAM address from cache_slot + mem_addr offset
3. Request SRAM read via SramArbiter
4. When granted, extract byte from SRAM data
5. Build response packet to scalar processor (via Ch0Arbiter?)
6. Signal done
```

Note: Only one jamlet (based on byte position) actually sends the response. Others may
still need to participate or can skip.

### ALU Operations (RF → ALU → RF)

Arithmetic/logic operation on register file values.

```
1. Receive instruction with alu_op, src1_addr, src2_addr, dst_addr
2. Read operand1 from RfSlice at src1_addr
3. Read operand2 from RfSlice at src2_addr (or use immediate)
4. Send to ALU with operation code
5. Receive ALU result
6. Write result to RfSlice at dst_addr
7. Signal done
```

## Pipeline

LocalExec can be pipelined to handle multiple instructions in flight. Suggested stages:

```
S1 (Decode) → S2 (RF Read) → S3 (SRAM/ALU) → S4 (Write Back)
```

| Stage | Description |
|-------|-------------|
| S1 | Decode instruction, determine operation type |
| S2 | RF read (for Store, ALU ops) |
| S3 | SRAM access OR ALU execution |
| S4 | RF write (for Load, ALU ops) OR SRAM write (for Store) |

**Latency**: 4 cycles typical
**Throughput**: 1 instruction per cycle (pipelined)

Note: SRAM access may stall if arbiter is busy with WitemMonitor request.

## Arbitration

LocalExec competes with WitemMonitor for:
- **SramArbiter**: Both need SRAM read/write access
- **RfSlice**: Both need RF read/write access

LocalExec has exclusive access to:
- **ALU**: WitemMonitor does not use the ALU

Priority policy options:
1. Round-robin between LocalExec and WitemMonitor
2. Priority to LocalExec (shorter latency path)
3. Priority to WitemMonitor (avoid stalling protocol operations)

Recommendation: Round-robin or slight priority to LocalExec since Simple ops and ALU ops
are on the critical path for instruction throughput.

## Design Notes

1. **Kamlet sends only when ready**: Simple witems are sent to jamlet only when
   cache_is_avail=true. LocalExec doesn't need to buffer or wait - it executes immediately.

2. **No WitemTable involvement**: Instructions flow directly from kamlet to LocalExec to
   SRAM/RF/ALU. This is the "fast path" for local operations.

3. **Mask support**: Simple load/store operations support byte masks for partial updates.
   The mask comes from the instruction and is applied during SRAM access.

4. **ReadByte coordination**: For ReadByte, multiple jamlets receive the instruction but
   only one sends the response. This is determined by which jamlet owns the target byte.
