# FMVPU Lane Implementation Plan

## Overview
Redesign of the Lane module using Tomasulo approach with single-issue pipeline, packet-based networking, and minimal buffering for quick netlist generation and area analysis.

## Implementation Phases

### Phase 1: Foundation Components
- [x] **Register File and Friends (RFF)** (`rff.txt`)
  - Basic implementation done, logic needs fixing
  - Placeholder test passes (reset + 10 cycles)
  - TODO: Fix instruction processing and PC logic
  - **Area (sky130hd):** 34,363 µm² (4,409 instances)

- [ ] **Instruction Memory (IM)**
  - Simple memory interface for instruction fetch
  - Integration with RFF for PC-based reads

- [x] **Basic ALU** (`alu.txt`)
  - ✅ Support for Add, Sub, Mult, MultAcc operations with proper enum types
  - ✅ Pipeline latency parameter (configurable in LaneParams)
  - ✅ Write-back to register file using WriteResult bundle
  - ✅ Local accumulator for chained MultAcc operations
  - ✅ Unit tests passing (Claude Code generated)
  - **Area (sky130hd):** 22,014 µm² (2,587 instances)

### Phase 2: Reservation Stations
- [ ] **ALU Reservation Station** (`alu_rs.txt`)
  - Out-of-order execution support
  - Dependency resolution via write monitoring
  - Configurable number of slots (N_ALURS_SLOTS)

- [ ] **Load/Store Reservation Station** (`ldst_rs.txt`)
  - Memory operation queueing
  - Base address + offset calculation
  - Load/store dependency management

- [ ] **Packet Reservation Station** (`packet_rs.txt`)
  - Network packet operation management
  - Send/receive/forward instruction handling
  - Channel assignment logic

### Phase 3: Execution Units
- [ ] **Data Memory (DM)**
  - Local memory interface
  - Load/store operation execution
  - Write-back to register file

- [ ] **Packet Interface (PI)** (`packet_interface.txt`)
  - Network packet send/receive logic
  - Command packet processing
  - Buffer management for packet words
  - Forward operation support

### Phase 4: Network Infrastructure
- [ ] **Packet Input Handler** (`packet_in_handler.txt`)
  - Incoming packet reception
  - Header parsing and validation
  - Flow control management

- [ ] **Packet Output Handler** (`packet_out_handler.txt`)
  - Outgoing packet transmission
  - Header generation
  - Channel arbitration

- [ ] **Packet Switch** (`packet_switch.txt`)
  - Integration of input/output handlers
  - Packet routing logic
  - Multi-channel support

- [ ] **Network Node** (`network_node.txt`)
  - Multi-channel packet switching
  - Connection state management
  - Priority-based arbitration

### Phase 5: Integration & Testing
- [ ] **Top-level Lane module** (`lane.txt`)
  - Structural wiring of all components
  - I/O interface implementation
  - Parameter configuration

- [ ] **Unit Testing**
  - Individual component tests
  - Reservation station functionality
  - Network packet flow

- [ ] **Integration Testing**
  - Full Lane module testing
  - Instruction execution flow
  - Network communication

- [ ] **Area Analysis**
  - Netlist generation using existing tools
  - Hardware cost evaluation with DSE
  - Comparison with previous NetworkNode

## Key Design Features

### ISA Support (`isa.txt`)
- **Packet Instructions**: Receive, Forward, Send, Get Word (6 modes)
- **Load/Store Instructions**: Memory operations with base+offset
- **ALU Instructions**: Add, Sub, Mult, MultAcc with immediate variants
- **Loop Instructions**: Start/Size with automatic iteration

### Register File Design
- 8 registers (0-7) with special purposes:
  - Reg 0: Packet word out (write-only)
  - Reg 1: Accumulator
  - Reg 2: Mask
  - Reg 3: Base address
  - Reg 4: Channel
  - Reg 5-7: General purpose

### Network Interface
- 4-direction connectivity (North, South, East, West)
- Multi-channel support per direction
- Packet forwarding and broadcast capabilities
- Command packet support for remote control

### Architecture Decisions
- **Single-issue pipeline** for initial implementation
- **Write identifier renaming** (2^WRITE_IDENT_WIDTH in-flight writes)
- **Minimal buffering** to reduce area overhead
- **Packet-based networking** with no large buffers

## Testing Strategy
1. Component-level unit tests for each module
2. Reservation station dependency resolution tests
3. Network packet flow validation
4. Full instruction execution pipeline tests
5. Multi-lane network communication tests

## Success Criteria
- [ ] All components compile and synthesize
- [ ] Basic instruction execution works
- [ ] Network packet communication functional
- [ ] Area analysis shows improvement over old NetworkNode
- [ ] Test suite passes completely

## Notes
- Prioritize quick netlist generation for area evaluation
- Follow existing codebase patterns and conventions
- Use existing DSE tools for hardware analysis
- Focus on structural implementation initially

## Module Implementation Checklist (for Claude Code)
For each new module, follow this standard workflow:

### 1. Design & Code
- [ ] Read corresponding .txt specification file
- [ ] Create module in `src/main/scala/fmvpu/lane/ModuleName.scala`
- [ ] Use proper enum types from `LaneParams.scala` (ALUModes, LdStModes, PacketModes)
- [ ] Use shared parameter constants (register addresses, etc.) from `LaneParams`
- [ ] Create ModuleNameGenerator object extending `fmvpu.ModuleGenerator`
- [ ] Add case to `src/main/scala/fmvpu/Main.scala` switch statement

### 2. Configuration
- [ ] Add any new parameters to `LaneParams.scala`
- [ ] Update `configs/lane_default.json` with new parameter values
- [ ] Ensure enum types have correct bit widths for instruction encoding

### 3. Testing
- [ ] Create `python/fmvpu/new_lane/test_modulename_basic.py`
- [ ] Add test target to `python/fmvpu/new_lane/BUILD`
- [ ] Run `bazel test //python/fmvpu/new_lane:test_modulename_basic`
- [ ] Add intentional failure test to verify test infrastructure, then remove

### 4. Area Analysis
- [ ] Add study to appropriate section in `dse/BUILD`
- [ ] Add to `ALL_STUDIES` list
- [ ] Handle special cases (external config files, extra parameters)
- [ ] Run `bazel build //dse:ModuleName_default__sky130hd_results`
- [ ] Record area results in implementation plan

### 5. Integration
- [ ] Update any dependent modules to use new module
- [ ] Verify compatibility with existing interfaces
- [ ] Update instruction bundles if needed