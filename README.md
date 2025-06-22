# FMVPU - Flexible Multi-Vector Processing Unit

A research project exploring mesh-based vector processing architectures using Chisel for hardware generation and Cocotb for verification.

This project investigates hybrid CGRA-vector processing architectures, specifically exploring CGRAs that can be dynamically partitioned into independent vector processing units. It also serves as a testbed for Chisel development workflows and LLM-assisted hardware design.

**Note**: This project is currently in the early stages of development.

## Project Overview

FMVPU implements a 2D mesh of processing lanes, each containing:
- **ALU**: Arithmetic and logic processing unit (planned)
- **Network Node**: Configurable router enabling inter-lane communication
- **Distributed Memory**: Register file (DRF) and data memory (DDM) with multi-banked access patterns

## Key Features

- **Parameterizable Architecture**: Grid dimensions, memory configurations, and network topology defined via JSON
- **Hybrid Network Modes**: Dynamic packet-switched routing with optional circuit-switched overlays
- **Multi-banked Memory System**: Concurrent access patterns with automatic conflict resolution

## Quick Start

### Prerequisites
- [Mill](https://mill-build.com/) build tool
- Scala 2.13.16
- Python 3.8+ with `pytest` and `cocotb`
- Chisel 7.0.0-RC1

### Building and Testing

```bash
# Generate Verilog RTL for the LaneGrid module
mill fmvpu.runMain fmvpu.Main out/rtl LaneGrid test/main/python/fmvpu/params/default.json

# Run all Python/Cocotb verification tests
mill pythonTest

# Run both Scala and Python tests
mill testAll
```

## Project Structure

```
src/main/scala/fmvpu/
├── core/           # Processing lanes and ALU components
├── memory/         # Register files, data memory, and memory controllers
├── network/        # Network routers, switches, and interconnect
└── utils/          # Utility modules (delays, FIFOs, arbiters)

test/main/python/fmvpu/
├── test_*.py       # Cocotb-based verification testbenches
├── params/         # JSON configuration files for different architectures
└── *.py            # Test utilities and Verilog generation scripts
```

## Documentation

Additional documentation available in `docs/`:
- [Project Overview](docs/project-overview.md) - Research goals, motivation, and development status
- [Architecture](docs/architecture/) - Detailed technical design documentation
- [Development Notes](docs/decisions/) - Design decisions and implementation rationales

## License

MIT

## Development Plans
   Most of the documentation was written by Claude Code, and then edited a bit by me.
   This I'm going to write myself. It's ok if it sounds a bit crap.
   This will be very incomplete, but will be somewhere for me to collect my thoughts so I
   don't get too offtrack.

### Add a network configuration Memory
   The NetworkNode will contain a small memory (of configurable depth with expected values of
   8 or 16 or so).  It will be possible to load data from the DDM into this configurable memory.
   There will add a new instruction that loads data from the DDM into this memory.
   When a permutation instruction is submitted it will reference this memory and the data from that
   address will be read and interpreted as a NetworkControl instance.

   Status - Not started

### Implement a basic ALU for the Lane.
   Initially let's support addition and multiplication.

   Status - Not started

### Add a processor on the north side of the grid.

   We'll add a RISCV processor to the north side of the grid.
   We need to work out how to drive the VLIW instructions to the grid.
   As possible approach is that the processor will queue up a bunch of instructions and
   then submit them to run in a loop for a fixed number of iterations, so that it can be working
   on something else while that loop runs.  We'll likely explore a few different approaches.

   Status - Not started

### Create a grid with multiple processors embedded
   Processors can enlist of a number of Lanes to make a dynamic vector processing unit.
   Not sure if this is actually useful, but it sounds cool.
   The hardware shouldn't be that hard.  It's just instruction routing.
   Making this useable for software will be a pain.

   Status - Not started

## Power and Area
   Get a reliable way to measure area and power.  I'd love for this to be using open-source tools
   so that the CI can be repeatable.  It would also be nice to get numbers for the closed tools.

   Status - Not started

## Workloads
   Get some meaningful software running on the hardware.
   At the moment I'm thinking of getting a software-defined radio application, a cryptography
   application, and a LLM running on the hardware.  Probably using different parameterizations of
   the hardware for each application.

### LLM workload
   I'm expecting this design to be suited to run a section of an LLM that fits in SRAM (i.e. as
   part of a very large cluster).  I'd like to have a see the performance of different sections
   of an LLM running on the hardware.

   - Not started

### Software Defined Radio
   I'm planning on initially getting a FFT running on the hardware.  This will be interesting
   since it has non-trivial data movement patterns.

   - Not started

### Cryptography
   I'm not sure what a good starting kernel would be for this.

   - Not started
