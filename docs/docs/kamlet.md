


## Kamlet: Renaming and Reservation Station

Each kamlet contains a reservation station (probably 16 kinstructions depth).  When a spot opens in
the reservation station a kinstruction is popped from the buffer, the vector register references are
renamed to physical vector register references and the kinstruction is placed in the reservation
station.  This renaming increases the reordering that the reservation station is able to do.  Mask
registers are treated identically to any other vector register. The renaming and reservation station
live at the kamlet level rather than in the lamlet because freeing a physical register requires
knowing when every jamlet slice of that register has completed its reads and writes.  The
non-determinism of non-local operations makes this impractical above the kamlet level.

Although the number of logical and physical registers are the same (48), renaming is still possible
since 16 of the 48 registers are used for temporary variables and are explicitly freed.  This means
there are typically only slightly more than 32 live registers allowing effective reordering.

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
