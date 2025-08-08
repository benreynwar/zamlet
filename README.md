# Zamlet - VLIW SIMT Processor Mesh

A parameterizable open source VLIW SIMT processor designed for mesh accelerators.

![Bamlet Flow](docs/diagrams/bamlet_flow.png)

## Quick Start

Ideally you should just be able to install bazel and then build
this project, but I wouldn't bet a whole lot of money on it working.
It works for me though!

```bash
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

Largely LLM generated but I've edited it so that it's not obviously wrong and probably helpful.

- **[Quick Start Guide](docs/quickstart.md)** - Setup and first examples
- **[Architecture Overview](docs/architecture.md)** - Design and microarchitecture
- **[Instruction Set](docs/instruction-set.md)** - Complete ISA reference
- **[Applications](docs/applications.md)** - Target workloads and kernels

## Tools

- **RTL**: Chisel (Scala HDL)
- **Testing**: Cocotb (Python testbenches)
- **Build**: Bazel
- **PPA**: OpenLane via bazel-orfs
