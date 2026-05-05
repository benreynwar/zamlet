# RVV

## Local Elementwise

About 70% of the RVV ISA is ALU-type operations.

Max number of vector register reads is 4 (3 operands for MAC plus the mask).
Max number of scalar register reads is 1.

### Cracking

* If an operand register EW does not match the EW expected by the instruction then the cracker will
insert an additional kinstruction to remap the register into a temporary register first.

* It's possible we'll split the MAC operations into two kinstructions to limit the number of
register reads, but probably not.

* For instructions that are using large scalar values that cannot fit in the kinstruction itself
a 'WriteParam' kinstruction is inserted that writes the scalar value to a parameter register first
that the following kinstruction can then reference.

### Execution

Most of these instructions use vl, vstart and the mask in standard ways with a few exceptions
that the hardware needs to handle.

* 1) carry, borrow and vmerge use the mask as an operand rather than as a mask

* 2) the mask logical operations, vid, broadcast and whole register moves are all unmasked

fflags and vxsat are stored locally in each lane.  Requests for fflags or vxsat result
in a VPU wide reduction of the flags.  Currently the vector interface that saturn uses
(and which we're planning to copy) only supports pushing fflags, rather than the pulling that
we want.  Pushing would require using the sync network for every FP operation which seems
like overkill.  It's likely worth adding to the vector interface to allow us visibility into
reads to fflags and vxsat.

## Configuration Distribution

Writes to `frm`, `vxrm` are handled by the scalar processor.
`vsetvli`, `vsetivli`, `vsetvl` instructions are handled by the scalar processor

## Cross-Lane Reduction Tree

min, max, minu, maxu, and, or: These operations can make use of the synchronization network for reduction.

sum: Must use an explicit reduction tree implemented with kinstructions.

Note: I'm not sure if it will be worth supporting min and max for FP in the synchronizer.
      If that is not supported we'll need to use the synchronization network for that too.

### Cracking for Reduction Tree

The reduction instructions are cracked into a sequence of data movement and
ALU kinstructions implementing a reduction tree.

* 1) Reduce the values in each jamlet.

* 2) Do a slide operation to bring pairs of operands together.

* 3) Do another operation.  Go back to (2) and repeat until we have a single result.

* 4) Write that value to element 0.

### Cracking for Synchronization Network Use

The reduction instructions are cracked into a sequence of data movement and
ALU kinstructions implementing a reduction tree.

* 1) Reduce the values in each jamlet.

* 2) Use a synchronization event to reduce the values

* 3) Write that value to element 0.

### Special Cases

**vcpop** is a special case in that we need to first sum the bits up in each local word.
We add a specific kinstruction for this purpose.

**vfirst** requires that each lane determines their local minimum element index before that
element index is reduced to find the global one.  We add a specific kinstruction to find
the minimum active element index in a mask.

Note: `vmsbf.m`, `vmsif.m`, `vmsof.m` are considered local element-wise operations.

**vfredosum, vfwredosum** require that the sum is done in order.  This is implemented using
the **Ordered Window** in the lamlet, which gathers the values in order and then adds them
using either a dedicated FP adder, or using one of the lanes.

## Cross-Lane Prefix Sum

`viota` is the only prefix sum operation.

### Cracking

Similar to the reduction trees, the prefix is done in stages of moves followed by sums.

I won't describe the actual ways in which the masks and indices are calculated since
that's not really necessary here.

* 1) First create X temporary registers, widen the bits to the SEW and place in the temporary
registers.  X is chosen anywhere from 1 to LMUL. Larger is better but we might choose a
smaller value to reduce temporary register pressure.  We will label this set of temporary
registers `A`.

* 2) Do a vector register gather where the indices of the gather are a function of the
     `element_index` and the stage index.

* 3) Perform `A = A + B` with a mask (also a function of the `element_index` and stage).
     Go back to 2 and repeat until each element is the sum of itself and all preceding values.

* 4) Repeat 1 to 3 until we've covered all of LMUL.  We will need to extract the final value
     from the previous loop and add that to the final vector too.

* 5) Deduct the initial value of the bit for each element so that we have the sum of the
     preceding elements (not including this one).

## Cross-Lane Data Movement

These instructions are all implemented on top of RegGather kinstruction.

### Cracking

This kinstruction can only handle LMUL=1 for the destination register so it is cracked into a
sequence of kinstructions that satisfy this. Having large LMUL for the source register is fine.

If the index register uses a different EW than is expected by the instruction, then the
Cracker will insert a kinstruction to remap the index register into a temporary register first.

It is not necessary that the source vector registers have a matching EW.  The hardware can
determine where to retrieve the bytes from a vector register with a different lane order or
element width.  Source vector registers with EW=1 (masks) are an exception to this.  The cracker
will insert a kinstruction to remap these.

Note: This operation is also used to remap registers from one lane-order or element-width to
another.

For slide instructions I expect we will crack into a kinstruction that generates the
index vector followed by a RegGather, but it may make sense to have a baked in
Slide kinstruction.

### Implementation

* 1) The kinstruction is processed by the Kamlet Transfer Engine.  In each jamlet the 
     Transfer Generator reads the necessary indices from the local register file slice
     and determines where the bytes are located.  For each continuous segment a message
     is generated and sent to that jamlet.

* 2) The request is processed by that jamlet's Transfer Server which reads the requested
     bytes from the register file, and generates and sends a response message.  The 
     Server also checks whether the instruction identifier is active in the local kamlet.
     If it is not active it will send a 'drop and retry' response, since it cannot
     guarantee that the registers are in the correct state.

* 3) The response is received by the Transfer Receiver and used to update the register
     file.  The Transfer Receiver notifies the Jamlet Transfer Engine, which once
     all responses are received will notify the Kamlet Transfer Engine.

* 4) When the Kamlet Transfer Engine sees that all jamlets are complete it initiates a
     synchronization event.  Once that event completes the kamlets remove the 
     kinstruction from the Kamlet Transfer Engine and release any locks on the
     register file.
     
### Special Cases

`vcompress.vm` is implemented by a `viota` instruction followed by a RegGather.


## Scalar Vector Access

The scalar-to-vector are just kinstructions that only update element 0.
The vector-to-scalar kinstructions return a message to the lamlet which
writes a scalar register.

`vmv.x.s`, `vmv.s.x`, `vfmv.f.s`, `vfmv.s.f`


## Memory: Unit-Stride, Small Stride, Segment Unit-Stride, Segment Small Stride, Bounded Access

See [Transfer System](transfer_system.md) for examples.

See [Custom Instructions](custom_instructions.md) for bounded access.

### Cracking

* The cracker uses the page information extracted by the PFC to break up the
instruction into a sequence of kinstructions that each access a single zamlet
cache line (i.e. access the same cache line in each kamlet), and have a single
source ordering (i.e. they don't span two stripes with different element-width).

* If we are not stripe aligned it is possible that an element may lie across a cache-line boundary,
or an ordering boundary. In this case special kinstructions are generated for each half of the
split element.

* For store instructions with a source register with a mismatched EW the cracker will
introduce a kinstruction to remap the register EW.

* If the stripe in memory has an EW=1 then the cracker will first load it into a temporary register
and remap it into a matching element width there before writing it back to the memory.  If the
stripe will be completely overwritten (i.e. it's a store with no mask and the full stripe is covered) then
this will be skipped.


### Implementation

* For kinstructions that are unit-stride stripe-aligned and have matching ordering the operations
will be purely local and fast for cache hits.  For unaligned or mismatched operations the operation
will be non-local and will involve the non-local Transfer System. 

* There are cases where an EW change combined with a strided access means that the operation
is local. The implementation does not take advantage of that.

* Transfers that are unit-stride use the direct Transfer Requester to Transfer Receiver, since
the source can easily calculate who it needs to send data to.

* Strided and Segment transfers use the Transfer Server approach so that the source does not
need to calculate what data to send itself.

* These operations will all naturally be ordered since accesses to the scalar memory will be
sequenced during cracking.  If we are using a strided access with a bound range that wraps [See
custom instructions], we make sure that we crack at least once before we store to the same
address.

* Currently EW=1,8,16,32,64 are supported. To take better advantage of strided operations it may
be useful to support EW=128, 256, 512.  The hardware cost of this wouldn't be too bad, but it's 
conceptually complicated and I'd rather avoid it if we can.

## Memory: Large Stride, Indexed, Segment Large Stride, Segment Indexed: (excludes Ordered Indexed Stores)

* For these instructions we cannot use the PFC to determine whether they page fault.  That checking
is done by the backend.  This means that one of these instructions will stall all subsequent
instructions until we determine there was no page fault.

### Cracking

* We crack these instructions into kinstructions with max LMUL of 1.

* The index vector register must have a matching EW and a remapping kinstruction will be produced
by the cracker if that is not the case.

* For store instructions with a source register with a mismatched EW the cracker will
introduce a kinstruction to remap the register EW.

### Implementation

* Each kamlet gets the page information using its TLB.  Once a kamlet has completed all of
its non-idempotent accesses it will use the synchronization network to get the lowest element index
that causes a page fault.

* Using this it will complete all of the non-idempotent accesses with element index lower than the
faulting element index.

* Memory stripes with EW=1 are also treated as a fault. These faults are handled by the lamlet which
remaps the offending stripe and then restarts from the failing element index.

* Once all elements are completed the kamlet will trigger a completion sync. Once the sync is
complete the kinstruction is removed from the Transfer Engine and the locks on memory and registers
are released.

## Memory: Ordered Indexed Stores (normal and segment)

Ordered operations are cracked in the same manner as unordered instructions, however rather than
broadcasting them to the kamlet mesh, they are handled by the **Ordered Window** in the lamlet.

This module explicitly serializes the accesses. This is necessary since two elements may write to
the same address and we need to make sure that this happens in the correct order.

The module contains a buffer with 16 (probably) slots. For each slot we:

* 1) Retrieve the index and data from the jamlet
* 2) Use the TLB to get the page information.
* 3) Send messages to write the memory in the vector memory, or write the scalar memory over the
Scalar Memory Interface.
* 4) Free the slot

Write messages can be sent as long as there is no earlier memory conflict.  As soon as the oldest
slot frees we populate it with the next element.

## Memory: Fault-Only-First

These are treated the same, but the lamlet suppresses page faults of element index greater than 0
and sets the value of vl.

## Remapping of EW=1 stripes

The remapping of EW=1 stripes doesn't directly correspond to a RISC-V vector instruction but is
required for implementing them.

Remapping is done with a stage of message passing, a transpose stage, and another message passing
stage.

A custom kinstruction is used for the transpose stage.  It takes 8 vector registers and considers
the lowest byte in each word.  It treats the combined 8 lowest bytes as a 8x8 bit matrix. It takes
the transpose and writes the result into 8 vector registers.  
