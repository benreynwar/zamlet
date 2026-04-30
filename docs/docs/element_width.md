# Element-Width-Aware Physical Layout

The data in the vector registers and in the vector memory are organized in units of **stripes** where a stripe is
a sequence of `n_lanes * word_width` consecutive bytes.  A vector register with LMUL=1 is exactly
one stripe.

Within a stripe how the bytes are ordered depends on the element-width of the instruction that wrote
the data to the stripe.  The first element is always written to lane 0 (either lane 0's cache or
vector register file slice), the second element to lane 1 and so on.

[Diagram of how elements are organized across a stripe show ew=64]
[Diagram of how elements are organized across a stripe show ew=16]
[Diagram of how elements are organized across a stripe show ew=1]

The purpose of this layout is that common vector instructions should be entirely local within a
lane.
 * A stride aligned, EW-matched unit-stride vector load or store should be moving data between a
   lane's local cache and vector register file slice.
 * An EW-matched vector arithmetic instructions should be reading from the local VRF slice and
   writing to the local slice.

If the standard RISC-V byte ordering was used, then every operations that involved operands of two
or more different EW would become a non-local operation.


## EW Tracking

For stripes stored in the vector memory the EW of each stripe is stored in the page table.
For stripes in the cache table, the EW of each stripe section is stored in a separate table in the
kamlet for quick access.  The kamlet also has a table where it tracks the EW of each vector
register.  Every stripe of data in the vector register file has an independent EW. For LMUL>1
the data may be stored in a mixture of different EW, if it was written using instructions
with different EW.

The lamlet independently tracks the EW of each vector register. Because all kamlets are processing
the same stream of kinstructions, the EW of the vector registers are always consistent.

## EW mismatch

The EWRemap kinstruction is used to remap a vector register from one EW to another.  This is
implemented on top of message passing between all the jamlets in the mesh and is an expensive
operation.

If remapping of a stripe in the cache is required then this is done by loading it,
remapping in the vector register file, and then storing back to the cache with the updated EW.

Remappings between mask registers and other registers is treated in the same way, although
mappings to and from EW=1 vector registers are particularly expensive.

## Vector Memory Stripe EW LifeCycle

When a fresh page is allocated the EW of the stripes is initially undefined.  The first read or
write of the page sets the EW.  Note: It is possible that several indexed loads or stores could be
operating in parallel if they are wrapped in a writesetident [see writesetident] custom instruction.
In this case the writesetident instruction itself specifies the EW that should be used for a page
with undefined EW.

When a fresh page is first written to by a scalar instruction, the EW of that scalar instruction is
used to set the EW of the stripe, however it is considered a 'weak EW'. A subsequent vector load or
store with a different EW will cause the stripe to get remapped to the vector instruction's EW.
This is because it's a fairly common pattern for scalar instructions to write a stripe with a
different EW than the vector logic will be using, and we don't want to fix the EW to a
non-optimum value.

There are also other situations where we modify the EW of a stripe in memory.  Anytime we do an
aligned unit-stride vector store to a stripe we update the EW of the stripe to match the vector
operation.  If the store rewrites the entire contents of the stripe we don't need to remap the
contents first, if it is only a partial write we need to remap the contents to the new EW first.

Unaligned, strided or indexed stores don't modify the EW of the destination stripe, with the
exception of if the stripe has EW=1.  If the stripe has EW=1 the access will fault.  The lamlet will
then perform a remapping of the memory stripe into the desired EW, and then reattempt the store.

Similarly if an unaligned, strided or indexed store hits a EW=1 stripe, the access will fault, and
the lamlet lamlet will perform a remapping followed by a reattempt.

## Vector Register Stripe EW LifeCycle

Initially vector registers are set to all 0 with undefined EW. The first read or write sets the EW.
All reads and writes of vector registers require that the EW expected by the kinstruction matches
the EW of the register.  When the lamlet constructs kinstructions it makes sure that this is the
case.  If the EW of the required register does not match then the lamlet will first do a remap onto
a temporary vector register.  Zamlet has 48 logical vector registers, which is an additional 16
beyond the 32 RISC-V vector registers that are available for this purpose.




