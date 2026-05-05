# Lamlet

The microarchitecture of the lamlet is less well though through than the kamlet mesh.  Because it
will be a small fraction of the area it's less critical it is well-optimized and just needs to be
feasible.  Performance of the frontend is important since it works in lock-step with the processor,
while performance of the backend is less important since latency will be dominated by the kamlet
mesh.

## Lamlet Frontend

### Pipelined Fault Checker (PFC)

Works out which pages the vector instructions access and faults.  This section runs in lock-step
with the processor pipeline.  I'm hoping I can reuse the implementation from the Saturn VPU from
UCB.  There will be some vector instructions where it is not possible to determine whether the
instruction results in a page fault in the frontend.  These instructions will be passed to the
backend and the pipeline will be stalled until it is known whether there is a fault.  This is
different from the saturn VPU implementation which had an iterative fault checker in the frontend to
handle these cases.

### Scalar Checker

This module is responsible for keeping track of which scalar memory pages the vector processor has
in-flight reads or writes to.  If the scalar processor tried to make a conflicting read or write
then the **Scalar Checker** will stall the processor until the VPU has finished accessing the scalar
memory.

![Lamlet Diagram](images/lamlet.png)

## Lamlet Backend

### Cracker

The **Cracker** breaks the sequence of vector instructions from the frontend into a sequence of kamlet instructions
to broadcast to the mesh of kamlets (we abbreviate kamlet instructions as kinstructions).  The module will
know the lane order and element width of all the vector registers and pages, and will insert additional
kinstructions to perform remappings of registers to compatible orderings when necessary.  It will also split
complex instructions, such as a reduction, into a sequence of simple kinstructions.

During this cracking additional temp vector registers will often be required to store intermediate
results.  Zamlet has 48 logical registers: the 32 architectural vector registers and an additional
16 temp vector registers.  Because the number of physical registers is limited (probably 48-64) the
**Cracker** add kinstructions that free the temp registers once it is done with them, allowing the
slots to be available during renaming.

One the kinstructions are created they for sent to one or more of the following:

* 1) Kamlet Router
* 2) Waiting Table
* 3) Ordered Window

The *Cracker** also keeps track of available space in kamlets instruction buffers, available
kinstruction identifiers and available synchronization identifiers.  This is all done by the
insertion of **IdentQuery** kinstructions into the stream, and the processing of the 
synchonization responses. [link to IdentQuery]

### Kamlet Router

The kamlet router connections to the kamlet mesh network.  This is used to broadcast the kinstructions
to the kamlet mesh.

### Lamlet Waiting Table

Some kinstructions require the lamlet to be involved in the processing.  If the kinstruction writes
to a scalar register the lamlet needs to store the kinstruction until the response comes back from
the kamlet mesh.  Relevant packets from the mesh are received by the **Jamlet Router** and these are
combined with the **Waiting Table** state to create scalar register writebacks that are then sent to
the processor.

### Ordered Window

The **Ordered Window** module is responsible for handling ordered loads and stores where page
faults, or memory conflicts cannot be calculated in advance.

The ordered window can work on two ordered instructions in parallel, and have up to 16 elements
in flight for each instruction at a time.

#### Loads

First the **Ordered Window** waits for a synchronziation point to be reached.  This indicates that
the ordered load kinstruction has arrived at all kamlets and is active.  This is necessary to ensure
correct memory ordering.  The **Ordered Window** module kicks off 16 load element messages in
parallel.  Accesses to the vector memory are handled directly by the jamlets, and the jamlets
respond as soon as they have determined there is no page fault.  If access is required to scalar
memory the jamlets will respond to the lamlet requesting the scalar data.  The lamlet submits these
requests of scalar data in order to the processor, and then once it receives the response, forwards
the data on to the jamlets.  As elements are completed, the slots become available and the
**Ordered Window** can being working on the subsequent elements.

Note: Currently all ordered loads use the Ordered Window , but it probably makes sense to do a
unordered load first but fault on an access to non-idempotent memory and only attempt an ordered
load after that.


###  Stores

For stores the ordering is more important since two elements can be written to conflicting
addresses.  Similarly to loads the **Ordered Window** first waits for a synchonization point to be
reached.  The **Ordered Window** module gives off 16 store element messages in parallel.  The
jamlets will respond with messages that tell the lamlet the address, the data, the mask bit and
any faults.  The lamlet will then send messages to write the memory in the correct order itself.

| Element Index | Note           | State           | 
| ------------- | -------------- | --------------- |
| 48            |                | GETTING ADDRESS | 
| 49            | Most Recent    | NOT STARTED     | 
| 34            | Oldest         | WRITING DATA    |
| 34            |                | COMPLETE        |
| 35            |                | COMPLETE        |
| 36            |                | WRITING DATA    |
| 37            |                | WRITING DATA    |
| 38            |                | GETTING ADDRESS |
| 40            |                | WAITING         |
| 41            |                | WAITING         |
| 42            |                | PAGE FAULT      |
| 43            |                | QUIT            |
| 44            |                | QUIT            |
| 45            |                | GETTING ADDRESS |
| 46            |                | GETTING ADDRESS |
| 47            |                | GETTING ADDRESS |

The diagram above shows an example of a **Ordered Window** instruction state. The 16 in-flight
elements are tracked.  The two oldest elements with indices of 34 and 35 have been completed.
Elements 36 and 37 have submitted writes to memory, but no write completed response
received yet.  Element 38 is still in the process of getting its addresses and
data from the relevant jamlet.  Elements 39 and 40 have received their addresses and data but
have not submitted writes since they are waiting to see whether element 38 has a page fault
or an conflicting address.  Element 42 has already received a Page Fault response back
from its jamlet. Elements 43 and 44 have terminated since we received the address, but don't
want to do the write when an earlier element has a page fault.  Elements 45 to 48 are still
getting addresses from the jamlets, and element 49 hasn't yet started.

## Scalar Memory Interface

This module is the bridge that enables the vector processor to read and write to the scalar memory.
It receives requests from the **Jamlet Router** (jamlets can send messages directly requesting reads
or writes to the scalar memory), and the **Ordered Window**.  Loads are directly forward to the 
memory system.  For Stores it first waits for the processor store buffer to empty.  Here I'm just
doing why the saturn VPU does.  I don't understand how this guaranteeds correct order, but assume
that if I'm interfacing with shuttle in the same way then it will be correct.

## Jamlet Router

The jamlet router connections to the jamlet mesh network.  The enables jamlets to communicate with
the **Scalar Memory Interface**, the **Waiting Table** and the **Ordered Window**.

## Synchronizer

A synchonronizer connects the lamlet to the synchronization network [Link to Synchronization].  This is used by the **Waiting
Table** and the **Ordered Window** to reach synchronization points where all kamlets are guaranteed
to have processed a kinstruction.  It is also used by the **Cracker** to receive IdentQuery
responses [link to IdentQuery].

