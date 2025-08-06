# Architecture Overview

Zamlet implements a hierarchical VLIW SIMT processor designed for parallel computation across processing elements in a mesh topology.

## Design Philosophy

The architecture targets workloads that benefit from:
- **SIMT execution**: Same instruction stream across multiple data
- **Explicit parallelism**: VLIW bundles expose instruction-level parallelism  
- **Lightweight communication**: Mesh network for inter-processor data exchange
- **Predictable performance**: No caches, explicit memory management

## Hierarchy

![Damlet Block Diagram](diagrams/damlet_block.png)

### Damlet (Future)
Multi-core RISC-V system integrated with Bamlet mesh for heterogeneous acceleration.

### Bamlet (VLIW SIMT Processor)
![Bamlet Architecture](diagrams/bamlet_architecture.png)

The Bamlet is the main processor containing:

- **Instruction Memory**: Stores VLIW instruction bundles, shared across Amlets
- **Control Unit**: Manages program flow, loop control, and SIMT dispatch  
- **Dependency Tracker**: Ensures VLIW slots have no hazardous dependencies
- **2D Amlet Grid**: Configurable array of processing elements

**Key Features:**
- SIMT execution where all Amlets execute the same instruction stream
- Predicated execution for conditional control flow
- Centralized loop control with nested loop support
- Non-deterministic timing due to network interactions

### Amlet (Processing Element)  
![Amlet Architecture](diagrams/amlet_architecture.png)
![Amlet Block Diagram](diagrams/amlet_block.png)

Each Amlet implements out-of-order execution:

**Pipeline Stages:**
- **Register File and Rename**: Version-tagged dependency tracking
- **Reservation Stations**: Capture operands from result bus  
- **Execution Units**: Parallel functional units
- **Result Bus**: Writeback and dependency resolution

**No Commit Stage**: Programs expected to terminate cleanly with HALT instruction.

## VLIW Instruction Format

Each VLIW bundle contains 6 parallel instruction slots:

| Slot | Purpose | Default Width | Register Files |
|------|---------|---------------|----------------|  
| **Control** | Loop management, program flow | - | - |
| **Predicate** | Conditional execution masks | - | A→P, G→P |
| **Packet** | Inter-processor communication | - | A,D |
| **ALU Lite** | Address arithmetic | 16-bit | A→A,D |
| **Load/Store** | Memory access | - | A,D→A,D |
| **ALU** | Data arithmetic | 32-bit | D→A,D |

## Register Files

Four register file types provide specialized storage:

| Type | Purpose | Default Size | Width |
|------|---------|--------------|-------|
| **D-registers** | Data values for ALU ops | 16 × 32-bit | 32-bit |
| **A-registers** | Addresses, lightweight compute | 16 × 16-bit | 16-bit |  
| **P-registers** | Predicate masks | 16 × 1-bit | 1-bit |
| **G-registers** | Global shared values | 16 × 16-bit | 16-bit |

## Dependency Resolution

### Register Renaming
- Instructions tagged with register version numbers
- Physical register file only writes when no newer pending writes exist
- Stalls when rename tags exhausted

### Reservation Stations
- Capture operands from result bus when not available from register file
- Shallow depths (1-4 entries) for light out-of-order scheduling  
- More efficient than full register renaming at these depths

## Network Architecture

### Topology
- 2D mesh with X-Y routing
- Multiple independent channels per direction
- Minimal buffering for lightweight operation

### Packet Structure  
- Headers contain destination coordinates and length
- Support for broadcast within coordinate rectangles
- Forwarding and appending operations for complex communication patterns

### Flow Control
- Output handlers connect to single input handler per packet
- No new connections until packet fully routed
- Expected congestion/deadlock issues to be addressed when running real workloads

## Memory Hierarchy

**Explicit Management**: No caches - all memory explicitly managed

- **Instruction Memory**: Shared per Bamlet, loaded via Command Packets
- **Data Memory**: Private per Amlet
- **Network Programming**: Instructions loaded over network for flexibility

## Key Design Decisions

### Why VLIW?
- Exposes instruction-level parallelism explicitly
- Compiler-controlled scheduling reduces hardware complexity
- Good fit for regular, parallel workloads

### Why SIMT?
- Natural fit for data-parallel algorithms
- Amortizes control overhead across processing elements
- Predication handles divergent control flow

### Why Out-of-Order Amlets?
- Hides memory and network latency
- Allows independent progress despite SIMT synchronization
- Reservation stations simpler than full register renaming

### Why Mesh Network?
- Scalable communication for 2D processor arrays
- Matches spatial locality in many algorithms
- Simple routing and deadlock analysis

## Performance Characteristics

**Current Status (sky130hd, 2 Amlets):**
- Area: ~1.2 mm²
- Target: 100 MHz  
- Actual: Fails timing by 2ns
- Critical paths likely in dependency resolution logic

**Scaling Expectations:**
- Linear area scaling with Amlet count
- Network congestion may limit performance scaling
- Memory bandwidth becomes bottleneck for larger configurations

## Implementation Files

Key source locations:
- Bamlet: [`src/main/scala/zamlet/bamlet/`](../src/main/scala/zamlet/bamlet/)
- Amlet: [`src/main/scala/zamlet/amlet/`](../src/main/scala/zamlet/amlet/)  
- Network: [`src/main/scala/zamlet/network/`](../src/main/scala/zamlet/network/)
- Tests: [`python/zamlet/bamlet_test/`](../python/zamlet/bamlet_test/)

The architecture demonstrates modern processor design concepts while remaining tractable for research and educational purposes.