# Memory Model

The zamlet VPU and the driving processor both share a single virtual address space (required of RISC-V).
Whether a particular virtual page is mapped to the vector memory or the scalar memory is determined
by which physical address it is mapped to.

The lamlet acts as a bridge between the processor and the rest of the zamlet VPU.  All vector
instructions accessing the scalar memory go via the lamlet, and all scalar instructions accessing
the vector memory make their requests via the lamlet.  Additionally all external requests to read
or write the vector memory go via the lamlet (for DMA the data itself does not pass through the
lamlet but the transfer paramters do).

For vector memory pages there is an additional page table that tracks the EW of every stripe in the
page.

## Lamlet to Kamlet Ordering

The ordering of memory accesses is enforced via the order of kinstructions that are sent from the
lamlet to the kamlets.  Vector instructions, scalar instructions accessing vector memory, and
external reads and writes are all converted to kinstructions and placed in the ordered stream.
External reads and writes are inserted such that they do not break up sequences of kinstructions
representing atomic operations (the lamlet may break up one RISC-V instruction into several
kinstructions which should be considered as an atomic group).

Each kamlet uses the kinstruction order to determine the order that memory accesses should occur
and the reservation station enforces this ordering when considering any reordering of operations.

## Access Paths

* Vector load/store to vector pages: independent of the lamlet unless the lamlet is required
    to enforce ordering (e.g. ordered indexed stores).
* Vector load/store to scalar pages: All requests from jamlets will access the scalar memory
    via the lamlet.
* Scalar load/store to vector page: the lamlet creates a kinstruction to read or write
    the vector memory.
* Scalar load/store to scalar memory: the lamlet lets the processor know if there are any
    in-progress vector instruction that might modify that scalar address.
* External load/store to vector memory: goes via lamlet which inserts it into the kinstruction
stream.
* External load/store to scalar memory: Does not involve zamlet.
* DMA read/write to vector memory: the data goes directly to the kamlets, while the control
    information goes to the lamlet where a kinstruction is created and inserted into the stream.

## Consistency Model

The zamlet supports RISC-V RVWMO ordering.
The lamlet tracks which scalar addresses are being updated and enforces the ordering of
scalar and vector accesses to scalar memory.
This ensures we have ordering consistency.

## Fence

Fence instructions are implemented by draining all active vector instructions.  The vector memory
cache is not flushed.

## Atomic Memory Operations

Atomic operations accessing vector memory can split into multiple kinstructions in the lamlet. The
lamlet prevents any memory access kinstructions (even those representing external memory
accesses) from being inserted between kinstructions representing an atomic operation.
Since the kinstruction ordering is preserved, the operations remain atomic.
