# Zamlet - VLIW SIMT Processor Mesh

A parameterizable open source VLIW SIMT processor designed for mesh accelerators.

![Bamlet Flow](diagrams/bamlet_flow.png)

## Overview

Zamlet is a research processor implementing a **VLIW (Very Long Instruction Word) SIMT (Single Instruction, Multiple Thread)** architecture designed for parallel computation across processing elements in a mesh topology. The project demonstrates advanced microarchitecture concepts including out-of-order execution, register renaming, and mesh networking.

### Key Features

- **VLIW Architecture**: 6 parallel instruction slots per bundle (Control, Predicate, Packet, ALU Lite, Load/Store, ALU)
- **SIMT Execution**: Single instruction stream across multiple processing elements with predication support
- **Out-of-Order Execution**: Reservation stations with operand capture and dependency resolution
- **Register Renaming**: Version-tagged registers for dynamic dependency tracking  
- **Mesh Network**: Lightweight inter-processor communication with X-Y routing
- **Configurable**: Parameterizable grid sizes, register file sizes, and execution unit configurations

## Architecture Hierarchy

**Damlet** (Future) → **Bamlet** (VLIW SIMT Processor) → **Amlet** (Processing Element)

- **Bamlet**: Top-level processor with 2D grid of Amlets, shared instruction memory and control
- **Amlet**: Individual processing element with out-of-order execution pipeline
- **Damlet**: Planned multi-core RISC-V system integrated with Bamlet mesh

## Current Status

✅ **Bamlet Implementation**: Initial implementation complete with basic functionality  
✅ **Testing**: Passing LLM-generated cocotb tests  
✅ **Area Analysis**: ~1.2 mm² in sky130hd (2 Amlets)  
⚠️ **Timing**: Fails timing at 100 MHz with -2ns slack in sky130hd  
🔄 **Verification**: Basic tests passing, serious verification work in progress  
🔄 **Performance**: Writing kernels for performance measurement  

## Quick Numbers

| Metric | Value |
|--------|--------|
| Area (sky130hd) | ~1.2 mm² (2 Amlets) |
| Target Frequency | 100 MHz |
| Current Slack | -2 ns |
| Register Files | 4 types (D/A/P/G registers) |
| Instruction Slots | 6 parallel slots per VLIW bundle |

## Getting Started

1. **[Quick Start Guide](quickstart.md)** - Get up and running with Docker
2. **[Architecture Overview](architecture.md)** - Understand the design
3. **[Instruction Set](instruction-set.md)** - Learn the ISA
4. **[Applications](applications.md)** - See target workloads

## Tools & Technologies

- **RTL**: Written in Chisel (Scala HDL)
- **Testing**: Cocotb (Python testbenches)  
- **Build System**: Bazel with custom rules
- **PPA Analysis**: OpenLane via bazel-orfs
- **Development**: Significant use of Claude Code for development assistance

## Project Goals

This is a **demonstration project** showcasing:
- Advanced computer architecture concepts
- Modern VLSI design flows
- Integration of multiple open-source EDA tools
- AI-assisted hardware development

*Note: Most files are a mix of manually written and LLM-generated content, demonstrating effective human-AI collaboration in hardware design.*