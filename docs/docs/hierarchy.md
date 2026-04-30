# Hierarchy

At the top level we have a processor, and the zamlet vector processing unit.  We are planning to integrate zamlet initially with the Shuttle processor from UCB.

[top-level diagram]

## Zamlet

Internally the zamlet is composed of a 'lamlet' (which acts as the interface to the processor), a mesh of lane-groups (kamlets), two columns
of memory interfaces (memlets), and two rows of network interfaces (nemlets).

### Lamlet

The lamlet receives riscv instructions from the processor, and breaks them down into microoperations (kinstructions, for kamlet instructions) which it then
sends to the mesh of kamlets.

### Kamlet

The body of the vector processing unit is a mesh of kamlets.  Each kamlet is a grouping of lanes (jamlets) that share:

* An **instruction buffer**.
* A **reservation station** for instruction reordering.
* A **shared waiting table** for storing meta data about in-process kinstructions that require non-local data movement.
* A **cache meta data table** for keeping track of the cache lines stored in the jamlets' SRAM.
* A **synchronizer** for synchronizing between the kamlets and the lamlet.  For example it is used for making sure all kamlets have finished non-local reads before marking that instruction as complete.

[diagram of a kamlet]

#### Jamlet

Each jamlet contains:

* SRAM for storing the jamlet's share of the kamlet's cached data (will likely also be used as a scratch pad).
* An ALU.
* A slice of the vector register file.
* A **waiting table** for storing meta data about in-process kinstructions that require non-local data movement.  The jamlet-specific
    data is stored in this table, while the rest of the data is stored in the **shared waiting table**.
* A **router** supporting two channels for sending and receiving packets between jamlets.  One channel is used for sending requests
    and the other for returning responses.
* A placeholder **systolic array** that will be used for supporting future risc-v matrix extensions.

### Memlet

Each kamlet has its own memory interface (memlet).  Memlets are organized in two columns, one east of the kamlet mesh, and one to the west.  Each memlet contains a memory controller
and communicates with a dedicated memory.

### Nemlet
Each kamlet has a network inteface (nemlet). Nemlets are organized in two rows, one north of the kamlet mesh, and one to the south.  Each nemlet communicates independently
over the network with other chips.
(The nemlet is a placeholder. No thought has been put into it yet).
