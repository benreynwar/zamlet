# Example of a Gather Instruction

This document goes though what the VPU does to implement an unordered gather instruction.

1. **Lamlet**: A gather instruction arrives at the lamlet.

2. **Lamlet**: The lamlet splits the gather instruction into a sequence of gather kinstructions.
   Each kinstruction gathers one element to each lane.
   The kinstructions are put in a network packet and broadcase to all the kamlets.

3. **Every Kamlet**: Each kamlet receives the kinstrucion packet and places them in the instruction buffer.

4. **Every Kamlet**: Each kamlet pops one of the kinstructions from the instruction buffer.  If the required
   registers are available it is placed in the pending instruction table on this kamlet
   and on all it's jamlets.

5. **Every Jamlet**: Each jamlet sees the new kinstruction in the pending instruction table and reads the
   gather index from it's local register slice. From this it work's out what address it
   needs to gather data from, and works out which lane is responsible for caching that
   address.  The jamlet sends a message to that jamlet requesting the data.

6. **Target Jamlets**: Jamlets receive messages requesting data. If the message maps to an active kinstruction
   in their pending instruction data they process the message. If it doesn't they send
   a response that they dropped the message.

7. **Target Jamlets**: If the required memory address is in the cache they response with a message containing
   the requested data.

8. **Target Jamlets/Kamlets**: If the required memory address is not in the cache, they let the kamlet know that we
   need to request that cache line.  The kamlet will send a message to it's corresponding
   memlet requesting that cache line.

9. **Target Memlets**: The memlet will respond with messages to all the jamlets in that kamlet 

10. **Target Jamlets**: The jamlets update their cache lines and let the kamlet know.

11. **Target Jamlets**: The jamlets send response messages with the data to the requesting jamlets.

12. **Every Jamlet**: Every jamlet receives a response message.  It updates the register file slice with the
    received data.  It let's the kamlet know that it has completed.

13. **Every Kamlet**: Once all of the component jamlets have completed it triggers a synchronization.

14. **Every Kamlet**: Once all kamlets have reached the synchronization point the kinstruction is removed from the
    pending instruction tables.
