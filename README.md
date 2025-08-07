# Zamlet - VLIW SIMT Processor Mesh

A parameterizable open source VLIW SIMT processor designed for mesh accelerators.

![Bamlet Flow](docs/diagrams/bamlet_flow.png)

## Quick Start

This project uses Bazel as a build system, but it cheats a lot since it uses lots of 
third-party tools, and that's difficult in Bazel, and I'm not very good with Bazel.
The way I run this project is to use Docker to create a container with all the required 
tools, then run Bazel within that container. It also uses the bazel-orfs flow which 
creates another Docker container for those tools!

```bash
# You may need to edit docker-compose.yml for your system
docker-compose up -d
docker-compose exec zamlet bash

# Generate Verilog and run tests
bazel build //dse/bamlet:Bamlet_default_verilog
bazel test //python/zamlet/bamlet_test:all --test_output=streamed

# Get area and timing results
bazel build //dse/bamlet:Bamlet_default__sky130hd_results
```

## Current Status

- **Implementation**: Basic Bamlet processor complete
- **Testing**: LLM-generated cocotb tests passing
- **Area**: ~1.4 mm² in sky130hd (2 Amlets)
- **Timing**: Fails at 100 MHz by 2ns in sky130hd post-synthesis
- **Routing**: Haven't managed to route it in sky130hd yet
- **Verification**: No real verification yet
- **Applications**: Starting working on some kernels but not done yet

## Documentation

- **[Quick Start Guide](docs/quickstart.md)** - Setup and first examples
- **[Architecture Overview](docs/architecture.md)** - Design and microarchitecture
- **[Instruction Set](docs/instruction-set.md)** - Complete ISA reference
- **[Applications](docs/applications.md)** - Target workloads and kernels

## Tools

- **RTL**: Chisel (Scala HDL)
- **Testing**: Cocotb (Python testbenches)
- **Build**: Bazel
- **PPA**: OpenLane via bazel-orfs
