# Instruction Flow

## Instructions From Processor

The zamlet receives up-to one RISC-V instruction from the processor per cycle.  These instructions
are placed in a FIFO, and back pressure can be applied to the processor.

## Lamlet: RISC-V Instruction -> KInstruction

The lamlet is responsible for converting this stream of instructions into a stream of micro-ops
(kinstructions: kamlet instructions) to send to the kamlets in the kamlet mesh.  The kinstructions
are sent in-order and all kamlets receive the same stream of kinstructions.
vl, vtype and vstart state are stored in the lamlet. This is used when converting the RISC-V
instructions into kinstructions which bake in this information and scalar registers into the
kinstruction.

Some RISC-V instructions map 1:1 to kinstructions, but some map to a sequence of kinstructions.
For example reduction operations map to a sequence of masked vector permutations and
arithmetic operations, and EW-mismatched operations [link to stripe] require an additional permutation.

Zamlet has 48 logical vector registers, which is an additional 16 beyond the 32 RISC-V vector registers
that are available as intermediates in these expansions.

## Lamlet: Initial Page Table Check

Before submitting kinstructions into the mesh the lamlet will check relevant page table entries to
determine if there will be faults, and whether they touch scalar memory.  If it is not possible to
determine in advance which pages will be touched then the lamlet will block processing further
instructions until the memory accesses have completed. This is necessary since the lamlet will not
know whether the kinstruction will fault until it has completed, and so cannot continue with other
kinstructions without the ability to roll them back.

In section [link here] we propose various custom instructions to minimize the number of instructions
requiring this serialization.

## Kamlet: Instruction Buffer

Kinstructions are broadcast from the lamlet to all kamlets where they are placed in the kamlets'
instruction buffers (probably 64 kinstructions depth). This occurs at a maximum rate of one kinstruction per cycle. The backpressure
from the buffers to the lamlet is handled via **Ident Queries** [link for ident query doc] which
take care of this back pressure, as well as tracking what kinstructions and synchronization slots
are in-use and which can be reused.

## Kamlet: Renaming and Reservation Station

Each kamlet contains a reservation station (probably 16 kinstructions depth).  When a spot opens in the reservation station a
kinstruction is popped from the buffer, the vector register references are renamed to physical
vector register references and the kinstruction is placed in the reservation station.  This renaming
increases the reordering that the reservation station is able to do.  Mask registers are treated
identically to any other vector register. The renaming and reservation
station live at the kamlet level rather than in the lamlet because freeing a physical register
requires knowing when every jamlet slice of that register has completed its reads and writes.  The
non-determinism of non-local operations makes this impractical.

The reservation station tracks which physical vector registers, memory, and resources (e.g. FPU) are
required by each kinstruction, and will emit the oldest kinstruction that is ready to be executed.

Memory accesses must be tracked in this manner since accessing non-local caches has
non-deterministic ordering.  For the hardware to operate efficiently it must know which sets of
kinstructions can be guaranteed not to have memory conflicts with one another, and this information
is passed as extension instructions.  The reservation station considers this information when
determining which kinstructions can be released.

When a kinstruction is released from the reservation station it is either directly executed by the
jamlets or goes into the waiting item table (see below) depending on whether it is a local or non-local
operation.

## Kamlet/Jamlet: Local and Non-Local Execution

Kinstructions are divided into those that can be locally executed (i.e. they just move data between
the local cache, local register slice and execution units), and those that involve data
movement beyond their jamlet such as register-register permutations, non-aligned loads and stores,
or loads and stores that require access to cache-lines that are not already present in the
cache.

Local kinstructions are sent to all the jamlets where they are immediately executed.  The jamlets
process the same kinstructions directly, and do not have a separate tier of instructions.  They just
apply the kinstruction to their local piece of the vector register file slice and cache.

Non-local kinstructions are placed in the kamlet's **shared waiting item table** (likely 16
kinstruction depth), as well as sent to all jamlets where entries are created in each
jamlet's **waiting item table**.  In each jamlet there are several state machines that consider the
contents of the table.  One state machine is used to send request messages to other jamlets and
memlets, another state machine is used to process their responses and update the table's state.  A
third state machine receives requests from other jamlets and generates responses to send to them.
Items in the table also use the synchronization network [link to sync network] to ensure that a kinstruction is retired
from all kamlets' **shared waiting item table**s at the same time when this is necessary, for
example when a kinstruction needs to access other kamlet's cache or vector register file slices.

For cache misses the kamlet will request the relevant cache line from its memlet. The memlet will
send response packets to all the jamlets which will update their local cache contents, and their
**waiting item table** to indicate that the cache line is now available.  [link to distributed
cache]

## Lamlet: Waiting Item Table

Some kinstructions require the active involvement of the lamlet such as reading or writing scalar
memory.  For these operations the lamlet has a **waiting item table** where it keeps track of which
pending kinstructions it is involved in.  For ordered loads and stores, an additional
sliding-window buffer tracks the elements currently in flight so that the lamlet can retire them
in element order. [link to host-memory interaction]


## Scalar Results and Host Synchronization

Zamlet expects the processor to track scalar destinations of vector instructions. The zamlet is
responsible for responding on a writeback interface once the data is available. This applies both
to short latency instructions that don't leave the lamlet (vsetvl), and for long latency instructions
that must traverse the mesh (vmv.x.s, vfirst.m, vcpop.m).

When an instruction requires writing to the scalar register file, the lamlet creates an entry in the
lamlet waiting item table.  As the kinstruction is processed in the kamlets a response will make
its way back to the lamlet, either via a message sent over the mesh network from a jamlet, or via
the synchronization network.  A state machine is monitoring the lamlet waiting item table and when the
state indicates that the data is ready, it will perform the write into the scalar register file.


## VAdd Instruction Example

* The VAdd instruction is translated directly into a VAdd kinstruction and broadcast to all kamlets.

* In each kamlet the kinstruction goes into the instruction buffer, and then into the reservation station.
  When the two src vector registers (and potentially the mask register) are available the kinstruction is popped
  from the reservation and broadcast to all the kamlet's jamlets.

* Each jamlet immediately executes the kinstruction in lock-step on the local operands and updates the local slice of
  the vector register file.


## Vector Permute Instruction Example

* The vrgather.vv is translated into a RegGather kinstruction and broadcast to all kamlets.

* The kinstruction goes through the instruction buffer and reservation station and is then placed in the kamlet's
  shared waiting item table, as well as creating an entry in each jamlet's waiting item table.

* In each jamlet the indices for the permutation are read from the local vector register slice, and then the jamlet
  determines on which remote jamlet the requested data is located.

* Each jamlet sends a request message to that remote jamlet asking for the required data. The remote jamlet
  responds with a response message returning that data.  The jamlet then uses this to update its local
  vector register file slice.

* Once the jamlet has completed its share of the RegGather operation, the jamlet notifies the kamlet that it
  is complete.

* Once all jamlets in the kamlet have completed, the kamlet uses the synchronization network to synchronize between
  all kamlets. Once all kamlets have completed, the entry is removed from the waiting item table.
