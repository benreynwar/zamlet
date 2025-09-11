# Zamlet - VLIW SIMD Processor Mesh

This is an exploratory project where I'm learning Chisel, playing with LLMs and
trying to make a processor suitable for using in a many-core accelerator.

The initial idea is to have a mesh of simple processors that are available as 
accelerators.  A more complex processor would send a small kernel to a region
of the mesh which would then accelerate that kernel.

The current design tries to:

* Keep kernels short.  The accelerator instructions are VLIW but allow intra-instruction
   dependencies between slots.  There is a built-in loop slot in the instruction so simple
   loops can be expressed in a single instruction.
* Keep utilization of the main ALU high.  Separate ALUs are used for address and predicate
   calculations.  There is sufficient reordering to allow high ALU usage.
* Support both CGRA and VPU configuration models.  The lanes communicate by message passing
   and have instructions to to receive and send packets. Packet data is popped directly to
   registers, or written directly to memory.

The implementation approach is:
* A mesh of SIMD processors.
* SIMD lanes communicate directly with one another using message passing.
* Lanes within a SIMD processor must be roughly synchronized (there is some flexibility
   provided by the depths of the reservation stations).
* SIMD processors support full predication.
  
Problems with this approach:
* The area cost for the register file is very high. Full predication creates several extra register reads.
* The area cost of reordering is very high. Reservation stations that capture operands are expensive even when very shallow. Full register renaming would likely make more sense.
* Compiler development would be very difficult.


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
