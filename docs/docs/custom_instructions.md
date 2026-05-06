# Custom Instructions

The custom instructions so far are all added for the purpose of speeding up indexed memory accesses.

## Set Index Bound Bits

A problem with indexed loads and stores is that any address can be accessed and so it is
impossible for the lamlet to determine whether there will be any page faults.

We add an additional setting `INDEX_BOUND_BITS` that specifies that only this many of the offset
bits are used in indexed loads and stores. Custom instructions are added to adjust this setting.  A
value of 0 means that the number of bits is not limited.  In this way the range of possible
addresses is limited and the lamlet can check for page faults before broadcasting to the kamlet
mesh.

This setting also affects strided operations so that the offset is
`stride*element_index % pow(2, index_bound_bits)`.

## Write Sets

Another factor that limits the throughput of vector loads and stores is that it is hard for the
hardware to ensure reads and writes don't conflict.  We use the term **Write Set** to mean
a sequence of memory accesses that are guaranteed not to conflict.  Custom instructions are added
to begin a **write set** and to end a **write set**.  This means that the vector processor
can run these instructions in parallel without having to ensure that there are no conflicts.

Effectively it is like the RISC-V 'unordered' instructions, but extends it so that we can have a
sequence of memory access instructions that are all explicitly unordered with respect to each other.

## Set Lane Order

This sets the lane order for subsequent vector operations.  This only effects the order in which
they write their outputs.  If their inputs were written in a different order, then they will first
be remapped into temporary registers using the new order before they are used.  This instruction
does not itself initiate any remapping.
