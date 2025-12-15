# Zamlet - A RISC-V vector processing unit

This is an exploratory project where I'm trying to create a vector processing unit for
a RISC-V core that scales to very large numbers of lanes.

The lanes are arranged in a grid, and connected with a mesh network.

Because we have a large number of lanes, we also need multiple connections to memory.
We assume we have a memory for the scalar processor, and several memories connected to
the vector processing unit.

We use a three layer hierarchy:

1. Lane (jamlet)
2. Lane Grouping (kamlet)
   This is a collection of lanes that share
   * an instruction queue
   * a cache table
   * a connection to memory
   * a translation lookaside buffer
3. Processor (lamlet)
   Includes both the front-end scalar processor as well as the
   grid of kamlets.

One of the goals is to minimize data movement as much as possible. When vector loads and stores
are continuous and aligned then data should simply travel between the memory and the appropriate
jamlets.

This is tricky with the RISC-V vector extension since element 3 of a vector with element width
8 is located in a different location in the vector register than element 3 of a vector with
element width 16.  To mitigate this problem we specify the element width used for a vector
register, and we arrange the data in the vector register such that element 3 is located
on the 3rd jamlet.

Similarly we let each page in the vector processing unit associated memory have an element width
and the data is arranged in memory to be optimized for accessing with that element width.
When a page of memory is allocated the element width is specified, and it will be efficient to
load and store vectors with that element width into that location in memory.

The current state is that I'm modeling these ideas in python to get a feel of whether it's practical
and I haven't started any RTL implementation yet.

All the rest of the stuff in this README is way out of date, and relates to a previous iteration of
those project which has very little in common with it's current incarnation.  But I'm not going to delete
it yet, since it's still a useful (maybe) example of using the open-source HW tools.


EVERYTHING BELOW HERE IS OUT OF DATE AND BASICALLY A TOTALLY DIFFERENT PROJECT.


![Bamlet Flow](docs/diagrams/bamlet_flow.png)

## Quick Start

Install bazel, docker and java. Then you should be able to use bazel to build.
It will pull in about 30GB of tools.

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
- **Area**: ~1.4 mm² cell area in sky130hd (2 Amlets)
- **P&R**: Currently working on getting amlet components through P&R and passing timing at 100 MHz.
- **Verification**: No real verification yet
- **Applications**: Started working on some kernels but not done yet

## Documentation

The documentation is largely LLM generated but I've edited it so that it's not obviously wrong and probably helpful.

- **[Quick Start Guide](docs/quickstart.md)** - Setup and first examples
- **[Architecture Overview](docs/architecture.md)** - Design and microarchitecture
- **[Instruction Set](docs/instruction-set.md)** - Complete ISA reference
- **[Applications](docs/applications.md)** - Target workloads and kernels

## Tools

- **RTL**: Chisel (Scala HDL)
- **Testing**: Cocotb (Python testbenches)
- **Build**: Bazel
- **PPA**: OpenROAD-flow-scripts via bazel-orfs
