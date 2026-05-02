# Instruction Flow

## Lamlet: RISC-V Instruction -> KInstruction

![Lamlet](images/lamlet.png)

**1)** The decoded RISCV-V vector instruction enters the lamlet frontend from the host processor.

**2)** In enters a **Pipeline Fault Checker (PFC)** which determines which pages the instruction will
   access.  It informs the **Scalar Checker** if it access any scalar memory pages, so that it can
   prevent memory clashes with the scalar processor.  If the **PFC** determines that there are no
   page faults then the RISC-V vector instruction is delivered to the lamlet backend. If page
   faults are found that that is handled by the processor.  If the **PFC** cannot determine whether
   or not there is a page fault, then the instruction is passed to the lamlet backend but the
   further processing in the lamlet frontend is stalled until the the backend can determine
   whether or not there was a fault.

**3)** In the lamlet back end the vector instruction is processed by the **Cracker**. This splits
   the RISC-V vector instruction into a sequence of kamlet instructions (kinstructions).  Splitting is
   done based on page accesses (there is a preference for each kinstruction only accessing one page)
   and to convert a complex instruction into a sequence of simpler kinstructions (e.g. reduction
   instructions are broken down into several data movement and aggregation kinstructions).
   The **Cracker** also knows the EW configuration for each vector register, and will insert EW
   remapping operations where required.  During the cracking, additional working vector registers
   may be required. There are a total of 48 logical registers, 32 of which map to the RISC-V'
   architectural registers, and 16 of which are available as working regs for the **Cracker**.

**4)** In the **Local Execution** module the kinstructions are either broadcast to the kamlet mesh
   over the kamlet network, or they are send to the **Ordered Window** module.  Some kinstructions
   require later actions by the lamlet.  These are also sent to the **Waiting Table** where the
   necessary state is stored.  For example some kinstructions will return values to the lamlet over
   the synchronization network, or the jamlet network, and state required to process these
   responses is stored in the **Waiting Table**.

**5)** If the kinstruction is sent to the **Ordered Window** module, then this module will initiate
   a series of interactions directly with the jamlets to process the operations in the correct order.
   This is described in [Add a link to how ordered operations are handled here]


## Kamlet

![Lamlet](images/kamlet.png)

**6)** Kinstructions arriving at the kamlet are placed into the **Instruction Buffer** (probably 64
kinstructions depth).

**7)** When there is space av available in the **Reservation Station**, kinstructions are popped
from the **Instruction Buffer** and the registers are renamed and mapped to the 48 physical
registers.  There are 48 logical registers and 48 physical registers, however 16 of the logical
registers are only used for temporary variables and are explicitly freed when not in use. 
After the registers have been renamed the kinstruction is placed in the **Reservation Station**.

**8)** The **Reservation Station** tracks which physical registers, cache lines and resources (e.g
divider hardware) each kinstruction requires.  Each cycle it issues the oldest kinstruction that
is ready to execute.  KInstructions are divided into 'Local Kinstructions' and 'Non-Local
Kinstructions', depending on whether they require any out-of-lane communication.  'Local
Kinstructions' are issued directly to the jamlets which immediately execute them with deterministic
latency.  'Non-Local Kinstructions' are placed in the 'Shared Waiting Table' as well have having
state in each of the jamlets 'Waiting Tables'.

**9)** Various state machines in the jamlets and kamlet interact with the state in the **Jamlet
Waiting Tables** and **Kamlet Shared Waiting Table** while sending and receiving messages to other
jamlets, and while using the **Synchronization Network** to synchonrizer with other kamlets.  The
details of these state machines are described later.
