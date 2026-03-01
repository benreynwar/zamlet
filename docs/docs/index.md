# Zamlet

A scalable RISCV Vector Processing Unit

## Summary

This is an exploratory project investigating using message passing between
lanes to implement a vector processing unit that scales to large numbers of lanes.

These docs are all human written.  Much of the code is LLM generated with manual revisions.

## Design Goals

* 1) It should scale to large numbers of lanes (1024 or so).
* 2) Should run riscv binaries using the vector extension.
* 3) It should be possible to create extremely performant programs.

These goals are often at cross purposes.  We require that arbitrary programs should
run but do not require they are performant. To get high performance it will be necessary to use
extension instructions, specific memory layout and compiler modifications.

The VPU should be able to pretend to be a standard RISCV VPU, but to actually take advantage of it properly it will
need to be treated quite differently.

## Approach

![Top-Level Diagram](images/oamlet.png)

### Lanes are arranged in a grid.
If we want the design to scale to large numbers of lanes, we don't really have any other choices.


### The lanes are connected with a mesh network.

The standard approach for connecting the lanes would be with a crossbar. This works really well for small numbers of lanes, but becomes impractical as the number of lanes becomes large, both because of the crossbar itself and because of the buffers necessary to keep everything synchronous. A mesh network is an alternative that will work nicely as long as most of the data movement is fairly local.

### An additional layer of hierarchy is introduced between the lane and the processor.

As our number of lanes grows large it becomes useful to add another layer of hierarchy into the design. A grouping of lanes share an instruction buffer and other logic that is useful to keep fairly close to the lanes, but is too expensive to replicate in each lane.


### Keep data local where possible, message passing between lanes when that is not possible.

Common operations should result in minimal data movement. We want to minimize the movement of data in and out of the lanes. We distribute both the cache SRAM and the vector register file throughout the lanes, and ideally instructions should just be moving data between this cache SRAM, the vector register file slice and the lane's ALU. For instructions that do need to move data between lanes, this is done by message passing. This should be reasonably efficient when the data is moving between lanes close to one another. It will be inefficient when we are moving data large distances (both latency and throughput).

### Vector memory pages and vector registers have a physical byte ordering that is configurable

Each vector memory page and each vector register has an 'element-width'. This determines the order in which bytes are stored in the physical memory. The is configured on the fly depending on what data it contains.  If this 'element-width' configuration matches the actual element width of the data then this will help keep the data local when vectors with different element widths interact. The 'element-width' of the pages is stored in a supplemental page table.

### Custom hardware to synchronize the lane groupings.

Because of the message passing approach, the lane groupings can often be out of sync with one another. Rather than building synchronization out of the network-based message passing we add specialized hardware for synchronizing between the lane groupings when this is required.

![Lane Grouping Diagram](images/kamlet_jamlet.png)

## Status

There is a python model that captures roughly cycle-accurate behavior which a focus on modelling the message passing aspects, since that is where the highest risk is.  A subset of the riscv vector extension is supported by this model, and some custom extensions are added to improve performance.  My impression so far is that the approach is practical.

There is a start on implementing the design in Chisel and some initial area results have been obtained using the skywater130 PDK.  I was most concerned that the area cost for producing, receiving and keep track of message states would be prohibitive, but the initial results suggest that while these costs are significant they are not prohibitive.

My current focus is on improving the documentation (i.e. writing this) so I can get some feedback, and on continuing to work on the RTL implmentation.  I would like to get to a point where I can run simple kernels that use a subset of the vector extension on an FPGA by the northern summer of 2026.  Fully supporting the riscv vector extension will be substantial work and will happen much later.
