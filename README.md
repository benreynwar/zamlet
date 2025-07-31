# FMVPU - Flexible Multi-Vector Processing Unit

The project is currently a playground for exploring a few things:

- Looking at a hybrid CGRA (coarse-grained reconfigurable array) vector-based processing architecture.  The basic idea is that we have a mesh of
   small compute units, with occasional more powerful processors mixed in.  The processors can gather a region of compute units into a vector processor.
   It's likely not practical but is a fun idea to explore.
- Using Chisel to design hardware and combining with cocotb verification.
- Seeing how LLM can assist with hardware development
- Using OpenROAD, OpenRAM and Bazel for design space exploration.

**Note**: This project is in the early stages of development.

## Build system
   Currently it's using a mix of docker and bazel.  This is the first time I've used bazel and it seems nice but often it's diffcult to
   get dependencies working.  I'm mostly getting the dependencies working in a Docker container, and then running bazel in that
   container for the build.

## RTL Development

Current implementation includes Amlet (processing units) and Bamlet (2D grids) architectures with:
- Multiple execution units: ALU, ALU-Lite, Load/Store, Packet handling
- Reservation stations for out-of-order execution
- Register files with renaming
- Network packet communication
- VLIW instruction support
- The instruction memory is at the Bamlet level, and Amlets run in SIMT fashion making use of 
  predicates.
- There has been no work yet on timing.  Pipelining work is needed.

## Project Structure

```
src/main/scala/fmvpu/
├── Main.scala              # RTL generation entry point
├── ModuleGenerator.scala   # Module generation interface
├── amlet/                  # Amlet (processing unit) architecture
│   ├── Amlet.scala        # Main Amlet module
│   ├── ALU*.scala         # Arithmetic Logic Units
│   ├── LoadStore*.scala   # Memory operations
│   ├── Packet*.scala      # Network packet handling
│   ├── RegisterFile*.scala # Register management
│   └── ReservationStation.scala # Out-of-order execution
├── bamlet/                 # Bamlet (grid) architecture
│   ├── Bamlet.scala       # 2D grid of Amlets
│   ├── Control.scala      # Instruction dispatch
│   └── InstructionMemory.scala # Program storage
└── utils/                  # Shared utilities
    ├── Fifo.scala         # FIFO implementations
    └── *Buffer.scala      # Various buffer types

python/fmvpu/
├── amlet/                  # Python instruction models
├── bamlet/                 # Bamlet utilities and interfaces
├── amlet_test/            # Amlet verification tests
├── bamlet_test/           # Bamlet verification tests
├── bamlet_kernels/        # Sample kernels (FFT, etc.)
└── utils.py               # Common test utilities

dse/                        # Design Space Exploration
├── amlet/BUILD            # Amlet synthesis configs
├── bamlet/BUILD           # Bamlet synthesis configs
├── scripts/               # Analysis tools
└── openram_scripts/       # Memory compiler integration

configs/                    # Hardware configurations
├── amlet_default.json     # Default Amlet parameters
└── bamlet_default.json    # Default Bamlet parameters

docs/                       # Documentation
├── api/                   # Generated Scaladoc
└── architecture/          # Design documentation
```

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
