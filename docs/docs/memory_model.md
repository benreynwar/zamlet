# Memory Model

The zamlet VPU and the driving processor both share a single virtual address space (required of RISC-V).
Whether a particular virtual page is mapped to the vector memory or the scalar memory is determined
by which physical address it is mapped to.

The lamlet acts as a bridge between the processor and the rest of the zamlet VPU.  All vector
instructions accessing the scalar memory go via the lamlet, and all scalar instructions accessing
the vector memory make their requests via the lamlet.  Additionally all external requests to read
or write the vector memory go via the lamlet (for DMA the data itself does not pass through the
lamlet but the transfer parameters do).

For vector memory pages there is an additional array-like structure stored in the scalar memory that
tracks the EW of every stripe in the vector memory.


## CPU Accessing Scalar Memory

The VPU keeps a table of all its in-flight reads or writes to the scalar memory.  The VPU
also observes the read and write addresses of the CPU pipeline.  If it sees that the processor
is accessing an address that is in-use by the vector processor, then it will stall the CPU pipeline.

## CPU Accessing Vector Memory

The vector memory is treated as non-cacheable by the processor.  All processor memory accesses
are visible to the VPU at commit. When the VPU sees an access to vector memory, a kinstruction
for the read or write is inserted into the stream of vector kinstructions.  When the actual
request comes over the memory link that request is associated with the kinstruction.  If it was
a read request then the response is returned over the memory link when the read kinstruction
responds.

## VPU Accessing Scalar Memory

The VPU will always wait for the CPU Store buffer to flush before accessing the scalar memory
(I don't really understand this aspect, and am just copying what the Saturn VPU does,
presumably it will become clearer once I get to the implementation, and better understand
how the saturn VPU and the shuttle CPU interact.)

## VPU Accessing the Vector Memory

All other accesses go through the lamlet and ordering is controlled there.

## External Request to the Vector Memory

All external requests to the Vector Memory go through the lamlet which enforces a consistent
ordering with respect to that seen by the CPU and VPU.

## Atomic Operations

Atomic operations are supported with the concept of an atomic sequence of
kinstructions.  When the lamlet is interleaving vector kinstructions,
kinstructions from CPU memory accesses, and kinstructions for external
memory accesses it does not break up atomic sequences of kinstructions.

## Fences

Fence instructions are implemented by draining all active vector instructions.  The vector memory
cache is not flushed.
