# Zamlet - A RISC-V vector processing unit

This is an exploratory project where I'm trying to create a vector processing unit for
a RISC-V core that scales to very large numbers of lanes.

It may be useful for applications that operate on large vectors, with the control flow
relatively independent of the vector data.  Applications such as Fully Homomorphic Encryption and
Machine Learning often fit into this category. 

## Approach

Lanes are arranged in a grid.
: If we want the design to scale to large numbers of lanes, we don't really have any other choices.

The lanes are connected with a mesh network
: The standard approach for connecting the lanes would be with a crossbar.  This works really well
  for small numbers of lanes, but becomes impractical as the number of lanes becomes large, both because of
  the crossbar itself and because of the buffers necessary to keep everything synchronous.  A mesh
  network is an alternative that will work nicely as long as most of the data movement is fairly local.

An additional layer of hierarchy is introduced between the lane and the processor
: As our number of lanes grows large it becomes useful to add another layer of hierarchy into the design.
  A grouping of lanes share an instruction buffer and other logic that is useful to keep fairly close to
  the lanes, but is too expensive to replicate in each lane.

Keep data local where possible, message passing between lanes when that is not possible
: Common operations should result in minimal data movement. We want to minimize the movement of data
  in and out of the lanes.  We distribute both the cache SRAM and the vector register file throughout the
  lanes, and ideally instructions should just be moving data between this cache SRAM, the vector register
  file slice and the lane's ALU.  For instructions that do need to move data between jamlets, this is done by
  message passing. This should be reasonably efficient when the data is moving between jamlets close to one
  another. It will be inefficient when we are moving data large distances (both latency and throughput).

Vector memory pages and vector registers have a physical byte ordering that is controlled by an element-width setting
: Each vector memory page and each vector register has an 'element-width'. This determines the order in which bytes are stored in the physical memory. If this 'element-width' matches the actual element width of the data then this will help keep the data local when vectors with different element-widths interact.  The 'element-width' of the pages is stored in a supplemental page table.

Custom hardware to synchronize the lane groupings
: Because of the message passing approach, the lane groupings can often be out of sync with one another.
  Rather than building synchronization out of the network-based message passing we add specialized hardware
  for synchronizing between the lane groupings when this is required.

## Hierarchy

We use jamlet/kamlet/lamlet/memlet to refer to modules in the zamlet processor.

1. Lane (jamlet)
   * ALU
   * SRAM (for the distributed cache table)
   * Vector Register Slice
   * Pending Instruction Memory
     : We need a memory to keep track of instructions that involve message passing.  Here
       we keep track of the state while we're waiting for the protocol to complete.

2. Lane Grouping (kamlet)
   * The jamlets within the group.
   * A buffer for microinstructions that have arrived.
   * Pending Instruction Memory
     : Similar to the memory in the jamlet. It is useful to have this memory at both levels of
       the hierarchy. Data that is shared among the jamlets is stored here.
   * Synchronization Module
   * TLB

3. Processor (zamlet)
   * A mesh of kamlets
   * A Scalar Processor to Mesh Bridge (lamlet)
       - This module acts as a bridge between the scalar processor (we use the shuttle processor from ucb-bar)
         and the grid of kamlets.
       - Converts the riscv vector instructions from shuttle into microoperations to send to the kamlets.
       - Bridges memory access from the scalar processor to the vector memory, and from the vector processor unit
         to the scalar memory.
   * Interface modules between the kamlet mesh and the vector data memory (memlet)
     
## Current State

* Basic modelling in python.  The approach seems practical, but I don't yet have quantitative performance numbers, and many of the vector instructions don't yet have defined mappings into the hardware.

* Some initial work implementing the design in Chisel. This is what I'm primarily working on at the moment.  I think the biggest risk at the moment is that the area cost of dealing with the message passing will be too high.
