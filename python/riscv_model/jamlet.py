'''
Physical design.

Let's have a register file with `rf_depth` entries (probably about 48)

Have an SRAM with 'sram_depth' entries.  (4096 entries)

Primitives are:

Load
Store

Send
Receive

Register File has 3 read ports and 2 write ports.
Mask Register File with 1 read port and 1 write port.

We want a receive buffer of length 16.

When we send a message we need to check that the slot is available everywhere.
If we build a global circuit to show if slots are available that will be
probably have a latency of 8 cycles or so :(.

Let's group X lanes together
They share an instruction queue.
They share a memory controller.

Each execution unit has an unroller.

We have a scoreboard to see when registers are ready.

Instructions are broadcast in normal packets. (probably change that later)

Opcode = 6 bit

registers can point at the register file, or at received messages

Load             dst (6 bit)    sram (12 bit)  mask (5 bit)  length (3) sp_or_mem (1) = 33 bit  if mem it needs an address too
Store            src (6 bit)    sram (12 bit)  mask (5 bit)  length (3) sp_or_mem (1) = 33 bit  if mem it needs an address too
Read Line        sram (12 bit)  memory (64 memory) length (3)  = 21 + 64 bit
Write Line       sram (12 bit)  memory (64 memory) length (3)  = 21 + 64 bit   + 1 bit for if evicting
Operation        dst (6 bit) src1 (6 bit) src2 (6 bit)  mask (5 bit) (length 3) = 24 bit
Send             src (6 bit)    target (6 bit) mask (5 bit)  length (3)  =  26 bit

We probably want some amount of support for caches built into the lane group.
For the lane group we know for each address in the SRAM which are scratch-pad, which are null, which are cache and which are
modified cache.
This will be useful for scatters and gathers.

The SRAM is dividied into
  - scratch pad
  - globally managed cache
  - locallly managed cache (for scatters and gathers mostly)

Scatter RF       dst (6 bit)    src (6 bit)  addr (6 bit)  mask (5 bit)  src_length (3)  dst_length (3) ew (3)  = 32 or 42
    - This will  send messages that contain the 'word' and the 'register to write'.
    - The same destination may receive many words.
    - For each scatter message received it sends back an acknowledgement.
    - We are compelte when all send messages have been acknowledged.
    - How can it know that it is done. (We can have a 16 bit toggling signal then lets us know when things complete)
           It's toggling speed will be limited by the time to communicate across the grid.
      This will block anything that wants to use those registers that we're writing to.

Scatter SP       dst (6 bit)   src (6 bit)  addr (6 bit)  mask (5 bit)  src_length (3) dst_length (12) ew(3)
    - This will block anything that wants to use the scratchpad.

Scatter Mem
    - If cache lines are present in globally managed cache then write to those.
    - Otherwise write to cache lines in the locally managed cache.
    - Blocks anything that reads from memory until complete.

Gather RF        dst (6 bit)    src (6 bit)  addr (bit) mask (6 bit) src_length (3) dst_length (3) ew(3)
    - We're sending a request for another lane for it to send some data to us.
    - A gather request will send a message asking for some data, and we'll get a reply back.
          - It's really a send of a special message that will automatically get a reponse.

Gather SP
Gather Mem

Rather that just having the address as the only option it might be nice to have some other built-in options.
Use 16 bit for addr instead. Which would bring the total up to 40 or 50.
  a) shift the data left or right
  b) barrel shift the data left or right
  c) stride?

Generalized Load or Store
  

Message Types:
   - Put word in message queue
   - Write to a register. (generates a confirmation message)
   - Write to the scratch pad (generates a confirmation message)
   - Write to the memory.  (generates a confirmation message)
   - Read from a register (generates a response message)
   - Read from the scratchpad (generates a response message)
   - Read from the memory (generates a response message)
   - Adds instructions to the instructions queue.

Should TLB update be a message or an instruction?

Examples of how things might work:
  
  - The core want to load a value from the memory.
    a) It works out what lane it wants it from, then it adds in a Load instruction and a Send instruction that
       are masked for the appropriate lane.
    b) OR it works out what lane it wants it from and sends a 'Read from the memory' message and the gets the
       reply.  This won't have well defined ordering but will slow other stuff down less.

  - We want to load a vector out of memory and it is nicely aligned with the cache-line.
      'Evict Line' if we need to do make room in the cache.
      'Load' (from memory)

  - We want to load a vector from memory and it is not nicely aligned.
      'Evict Line' if we need to do make room in the cache.
      'Read Line' to force bringing in the appropriate cache lines.
      Use a Send or Gather to shift the data

   - Load a vector with a stride.
       Send scalar.
       Multiple index by scalar into a temp reg
       Use temp reg to do a gather from memory.

Synchronizing:
    For instructions that move data around we need a way to make sure everyone has finished that instruction.
    Each node sends signals that say whether everyone in each direction of (NE, NW, SE, SW) has finished.
    When all of those incoming say finished and it is finished then the operation has globally finished.
    We could use this to send signals when instruction are completed in one of the 4 directions.  Each node would
    have a table of partially completed instructions that it updates as it gets messages, and in turn sends messages
    when it has been completed it a given direction.
    Tracking in 8 directions can move us twice as fast is synchronization is time consuming.

    An alternative would be just to send everything to the top and work it out there and then broadcast it back down.

    We can do a similar thing for the receive buffer so we know what is the global maximum number of uncompleted
    send instructions that haven't received a reponse yet.

    Might be good to do the synchronization on a lane group level so that it moves faster.

    We also need something like the synchonrization to determine that we don't have any exceptions in the addresses.
    We will need to distribute TLB for this.

    And also for the amount of room in the instruction queue.

Exceptions:
    We want an efficient way to find out if there was an exception in a page access.
    Each node needs to send out if it had an exception and what it's index is.
    Then we find the minimum value that had an exception.

    Special sync messages: (16 bit wire), 2 wires in each direction (32 bit in each dir)
       - max uncompleted send instructions   4 bits
       - all instruction A completed         4 bits  
       - lowest index of exception is       12 bits
       - all instruction X issued            4 bits

'''

'''
Questions to answer:
    1) Can I run reasonable kernels on this?
       Answer: Make a python model and simulation the kernels.

    2) Is the area sane:
       Answer: Make a chisel implementation and look at the area.
'''

'''
First step is to make a python model.

Levels:

    1) Jamlet (lane)
    2) Kamlet (group)
    3) Lamlet (grid)

    1) Jamlet: This contains:
         - Register File slice
         - SRAM slice.
         - ALU
         - Receive Buffer
         - Router
       Inputs:
         - Data received at the router.
         - global sync info
       Outputs:
         - Data send by the router
         - local sync info

    2) Kamlet: This contains:
         - jamlets_in_kamlet jamlets
         - cache_info
         - synchronization state
         - tlb
       Inputs:
         - Data received at the router.
         - Sync info from different directions
       Outputs:
         - Data send by the router.
         - Sync info to different directions

    3) Lamlet: This contains:
         - cache info
         - local to translate RISCV instructions into Kamlet instructions

'''


from collections import deque
from dataclasses import dataclass
from enums import Enum


class PageInfo:

    def __init__(self, global_address, local_address, is_vpu, element_width):
        # Logical address
        self.global_address = global_address
        self.is_vpu = is_vpu
        # Local address in the scalar or VPU memory
        self.local_address = local_address
        self.element_width = element_width


class KamletTLB:

    def __init__(self, params: LamletParams):
        self.params = params
        self.pages = {}

    def allocate_page(self, global_address, local_address, is_vpu, element_width):
        '''
        Associate a page of the global address space with a page in the local vpu
        address space or a page in the local scalar address space.
        Also associate that page (for vpu pages) with an element_width. This will
        effect how the global page gets arranged inside the local page.
        '''
        assert size % self.params.page_size == 0
        for index in range(size//self.params.page_size):
            logical_page_address = address + index * self.params.page_bytes
            physical_page_address = self.get_lowest_free_page(is_vpu)
            assert logical_page_address not in self.pages
            self.pages[logical_address] = PageInfo(
                global_address=global_address,
                is_vpu=is_vpu,
                local_address=local_address,
                element_width=element_width
                )

    def release_page(self, local_address):
        assert local_address in pages
        del self.pages[local_address]

    def get_page_info(self, address):
        assert address % self.params.page_bytes == 0
        return self.pages[address]


class MessageType(Enum):
    SEND = 0
    INSTRUCTIONS = 1

    WRITE_REG_REQ = 8
    WRITE_SP_REQ = 9
    WRITE_MEM_REQ = 10

    WRITE_REG_RESP = 12
    WRITE_SP_RESP = 13
    WRITE_MEM_RESP = 14

    READ_REG_REQ = 16
    READ_SP_REQ = 17
    READ_MEM_REQ = 18

    READ_REG_RESP = 20 
    READ_SP_RESP = 21
    READ_MEM_RESP = 22


@dataclass
class Header:
    target_x: int    # 7: 0
    target_y: int    # 15: 8
    source_x: int    # 23: 16
    source_y: int    # 32: 24 
    length: int    # 35: 32
    message_type: MessageType  # 43: 36
    address: int   # 63: 48


class Direction(Enum):
    N = 0
    S = 1
    E = 2
    W = 3
    H = 4


directions = (Direction.N, Direction.S, Direction.E, Direction.W, Direction.H)


@dataclass
class OutputConnection:
    remaining: int
    source: Direction


class Router:

    def __init__(self, x: int, y: int, params: LamletParams):
        self.params = params
        self.input_buffers = {'N': deque(), 'S': deque(), 'E': deque(), 'W': deque(), 'H': deque()}
        self.output_buffers = {'N': deque(), 'S': deque(), 'E': deque(), 'W': deque(), 'H': deque()}
        self.output_connections = {}
        self.priority = list(directions)

    def get_output_direction(self, header):
        if header.x > self.x:
            return Direction.E
        elif header.x < self.x:
            return Direction.W
        elif header.y > self.y:
            return Direction.N
        elif header.y < self.y:
            return Direction.S
        else:
            return Direction.H

    def step(self):
        self.priority = self.priority[1:] + self.priority[0]
        for output_direction in self.directions:
            if output_direction not in self.output_connections:
                # Try to make a new connection 
                for input_direction in self.priority:
                    if self.input_buffers[input_direction]:
                        if isinstance(self.input_buffers[input_direction][0], Header):
                            header = self.input_buffers[input_direction][0]
                            output_direction = self.get_output_direction(header)
                            self.output_connections[output_direction] = OutputConnection(header.length+1, input_direction)
                            break
            # If there is a connection see if we can send a word
            if output_direction in self.output_connections:
                conn = self.output_connections[output_direction]
                if self.input_buffers[conn.source] and self.output_buffers[output_direction] < self.params.router_output_buffer_length:
                    word = self.input_buffers[conn.source].popleft()
                    self.output_buffers[output_direction].append(word)
                    conn.remaining -= 1
                    if conn.remaining == 0:
                        del self.output_connections[output_direction]


class Jamlet:

    def __init__(self, x: int, y: int, params: LamletParams):
        self.params = params
        self.x = x
        self.y = y

        rf_slice_size = params.maxvl_bytes // params.n_jamlets * params.n_vregs
        self.rf_slice = bytes([0] * rf_slice_bytes)

        sram_size = params.sram_bytes // params.n_jamlets
        self.sram = bytes([0] * sram_size)

        self.receive_buffer = [None] * params.receive_buffer_depth

        self.router = Router(x, y, params)

    def step(self):
        self.router.step()


class CacheState(Enum):
    I = 0
    S = 1
    M = 2

@dataclass
class KamletCacheLineInfo:
    # What is the base address of this cache line
    # in the local memory
    local_address: int
    # M: modified (we're written but not updated memory)
    # S: shared (it's a copy of memory)
    # I: it's invalid data
    cache_state: CacheState
    # Can we make local changes to the cache state or is
    # it globally managed.
    locally_managed: bool


class Kamlet:

    def __init__(self, min_x: int, min_y: int, params: LamletParams):
        self.params = params
        self.n_columns = params.n_columns_in_kamlet
        self.n_rows = params.n_rows_in_kamlet
        self.n_jamlets = self.n_columns * self.n_rows
        
        self.jamlets = [Jamlet(index % self.n_columns, index//self.n_columns, params)
                        for index in range(self.n_jamlets)]

        self.cache_info = [
            KamletCacheLineInfo(None, CacheState.I, False) for i in range(params.sram_bytes//params.cache_line_bytes//params.n_kamlets)]

        self.tlb = KamletTLB(params)
