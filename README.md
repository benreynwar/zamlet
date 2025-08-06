# Zamlet - VLIW SIMT Processor Mesh

**Instruction Flow in Bamlet (Initial Implementation Done)**
![](docs/diagrams/bamlet_flow.png)

The Bamlet is a parameterizable open source VLIW SIMT Processor.  It is designed to be used
in a mesh as part of a configurable accelerator.

**A multi-core RISC-V System in a mesh of Bamlets (Implementation Not Started Yet) **
![](docs/diagrams/damlet_block.png)

## Tools Used
   * RTL written in chisel
   * Testing done using cocotb
   * Build system is bazel
   * Area and timing estimates using OpenLane (via bazel-orfs)

## Status
   An initial implementation of the Bamlet is there.  It's passing basic
   LLM-generated cocotb tests, but no serious verification work has been done.
   I'm in the process of writing some kernels so that I have a way to measure performance.
   In sky130hd it fails timing at 100 MHz with a negative slack of 2 ns.
   The area of the default implementation (2 Amlets) is roughly 1.2 mm2 in sky130hd.


## Project Structure

```
src/main/scala/zamlet/
├── Main.scala              # RTL generation entry point
├── amlet/                  # Amlet (processing unit)
├── bamlet/                 # Bamlet (VLIW SIMT processor)

python/zamlet/
├── amlet/                 # Python instruction models
├── bamlet/                # Bamlet utilities and interfaces
├── amlet_test/            # Amlet verification tests
├── bamlet_test/           # Bamlet verification tests
├── bamlet_kernels/        # Sample kernels (FFT, etc.)

dse/                        # Design Space Exploration

configs/                    # Hardware configurations
```
