# Zamlet - VLIW SIMT Processor Mesh

**Instruction Flow in Bamlet (Initial Implementation Done)**
![](docs/diagrams/bamlet_flow.png)

The Bamlet is a parameterizable open source VLIW SIMT Processor.  It is designed to be used
in a mesh as part of a configurable accelerator.

**A multi-core RISC-V System in a mesh of Bamlets (Implementation Not Started Yet)**
![](docs/diagrams/damlet_block.png)

## Tools Used
   * RTL written in chisel
   * Testing done using cocotb
   * Build system is bazel
   * Area and timing estimates using OpenLane (via bazel-orfs)
   * Claude code was used quite a bit.  Most files (including this one) are a mix of manually written
       and LLM-generated content.

## Status
   An initial implementation of the Bamlet is there.  It's passing basic
   LLM-generated cocotb tests, but no serious verification work has been done.
   I'm in the process of writing some kernels so that I have a way to measure performance.
   In sky130hd it fails timing at 100 MHz with a negative slack of 2 ns.
   The area of the default implementation (2 Amlets) is roughly 1.2 mm2 in sky130hd.

## Setup
   This project uses bazel as a build system, but it cheats alot since it uses lots of
   third-party tools, and that's difficult in bazel, and I'm not very good with bazel.
   The way I run this project is to use the Dockerfile to create a Docker container with
   all the required tools, and then run bazel within that container.  It also uses the
   bazel-orfs flow which will create another Docker container for those tools!

   The following is the commands I use to set things up.
```
# You may need to make edits to the docker-compose.yml to get it to work on your
# system.
docker-compose up -d

# And then enter the container with
docker-compose exec zamlet bash
```

   Once inside the container we can use bazel to run things.
```
# Generate the Bamlet verilog using the default parameters.
# The default parameters can be edited in configs/bamlet_default.json
bazel build //dse/bamlet:Bamlet_default_verilog

# Run some cocotb tests
bazel test //python/zamlet/bamlet_test:all --test_output=streamed

# Get the area using sky130hd
bazel build //dse/bamlet:Bamlet_default__sky130hd_results

# Get the post-synthesis timing results
bazel build //dse/bamlet:Bamlet_default__sky130hd_timing_floorplan

# Get the post-route timing results
bazel build //dse/bamlet:Bamlet_default__sky130hd_timing_route
```


## Project Structure

```
src/main/scala/zamlet/
├── Main.scala              # RTL generation entry point
├── amlet/                  # Amlet (processing unit)
├── bamlet/                 # Bamlet (VLIW SIMT processor)

python/zamlet/
├── amlet/                 # Python instruction models
├── bamlet/                # Bamlet utilities and interfaces
├── amlet_test/            # Amlet verification tests
├── bamlet_test/           # Bamlet verification tests
├── bamlet_kernels/        # Sample kernels (FFT, etc.)

dse/                        # Design Space Exploration

configs/                    # Hardware configurations
```

## Instruction Set Architecture

The Zamlet architecture implements a VLIW (Very Long Instruction Word)
SIMT (Single Instruction, Multiple Thread) ISA designed for parallel computation
across processing elements in a mesh topology.

### Instruction Bundle Format

Each VLIW instruction bundle contains six parallel instruction slots:

- **Control**: Loop management and program flow control
- **Predicate**: Conditional execution mask generation
- **Packet**: Inter-processor communication operations
- **ALU Lite**: Lightweight arithmetic operations (default is 16-bit address path)  
- **Load/Store**: Memory access operations
- **ALU**: Arithmetic/logic operations (default is 32-bit data path)

### Register Files

The architecture provides multiple register file types:

- **D-registers**: Data registers for ALU operations (16 32-bit registers by default)
- **A-registers**: Address registers for lightweight compute (16 16-bit registers by default)
- **P-registers**: Predicate registers for conditional execution (16 1-bit registers by default)
- **G-registers**: Global registers shared across Bamlet-level operations (16 16-bit registers by default)

### Instruction Types

#### ALU Instructions

Typical arithmetic and logic operations on data words (default 32-bit).
Reads from D-registers and writes to A- or D-registers.

See `src/main/scala/zamlet/amlet/ALUInstruction.scala` and `python/zamlet/amlet/alu_instruction.py`.

#### ALU Lite Instructions

Typical arithmetic and logic operations on address words (default 16-bit).
Reads from A-registers and writes to A- or D-registers.

See `src/main/scala/zamlet/amlet/ALULiteInstruction.scala` and `python/zamlet/amlet/alulite_instruction.py`.

#### ALU Predicate Instructions  

Generate conditional execution masks.  Takes three inputs src1, src2 and base predicate.
A typical operation is like `new_predicate = (src1 < src2) && base_predicate`.
lte, lt, gte, gt, eq and neq operations are supported.

src2 is an A-register, however src1 is limited to be either an immediate, a loop index, or
a global register.  Writes to P-registers.

See `src/main/scala/zamlet/amlet/PredicateInstruction.scala` and `python/zamlet/amlet/predicate_instruction.py`.

#### Control Instructions

Control instructions are `LoopImmediate`, `LoopLocal`, `LoopGlobal`, and `Halt`.  The `Halt`
instruction terminates execution, while the three loop instructions provide hardware support
for executing loops.  The loop instructions provide the length of the loop's body as well as
the number of iterations.  The number of iterations is an immediate, a global register, or
can be an amlet-local A-register.  If a amlet-local A-register is used then the loop iterations
will be **at least** the maximum value of that amlet-local A-register across all amlets.
Predicates must be used to ensure that the contents of the loop body are executed the correct
number of times on each amlet.

See `src/main/scala/zamlet/amlet/ControlInstruction.scala` and `python/zamlet/amlet/control_instruction.py`.

#### Load/Store Instructions

Aligned memory-access instructions.
Reads data from A- or D-registers.  Reads address from A-registers.  Writes to A- or D-registers.

See `src/main/scala/zamlet/amlet/LoadStoreInstruction.scala` and `python/zamlet/amlet/loadstore_instruction.py`.

#### Packet Instructions

Inter-processor communication in mesh topology.
The network has a number of independent channels.  The channel is specified as an immediate in
all instructions that send data.  Instructions the receive data do not specify the channel
(although I should probably add that).

- **Receive**: Start receiving a packet.
   + The packet length is written to an A or D-register.
- **GetWord**: Retrieve a word from a packet.
   + The retrieved word is written to an A or D-register.
- **ReceiveAndForward**: Starting receiving a packet, while also forwarding it to another destination.
   + The destination is read from an A-register.
   + The packet length is written to an A or D-register.
- **ReceiveForwardAndAppend**: Starting receiving a packet, while also forwarding it to another destination and append additional words to the end of the packet.
   + The destination is read from an A-register.
   + The number of appended words is an immediate.
   + The packet length is written to an A or D-register.
- **ForwardAndAppend**: Forward a packet to another destination and append words to the end.
   + The destination is read from an A-register.
   + The number of appended words is an immediate.
- **Send**: Send a packet.
   + The length is read from an A-register.
   + The destination is read from an A-register.
- **Broadcast**: Send a packet to all destinations within a region.
   + The length is read from an A-register.
   + The destination is read from an A-register.  All locations in the rectangle spanned by our current
       location and the destination receive the packet.

All write operations to D-register 0 are treated as adding that word to the packet being sent,
or are appended to a packet being forwarded.  So if we wanted to send a packet of length 2 we would
need a Send instruction followed by two instructions that wrote to D-register 0.

See `src/main/scala/zamlet/amlet/PacketInstruction.scala` and `python/zamlet/amlet/packet_instruction.py`.

## Microarchitecture

The Zamlet architecture implements a hierarchical VLIW SIMT processor with three main levels:

### Bamlet (VLIW SIMT Processor)

The Bamlet is the top-level processor containing a 2D grid of Amlets with shared control and instruction dispatch. Key components:

- **Instruction Memory**: Stores VLIW instruction bundles
- **Control Unit**: Manages program flow, loop control, and instruction dispatch to all Amlets
- **Dependency Tracker**: Ensures VLIW instruction slots have no complex dependencies. 
  All reads occur before writes, and no more than one slot may write to a given register.
  Performs minor reordering to enforce these constraints.
- **2D Amlet Grid**: Configurable array of processing elements with internal mesh connectivity

The Bamlet implements SIMT execution where all Amlets execute the same instruction stream but can be predicated for conditional execution. Loop control is centralized with support for nested loops and both local and global iteration resolution.  The amlets are not guaranteed to execute exactly in sync due to non-determinism from the interaction of the amlets with the network.

### Amlet (Processing Element)

Each Amlet implements out-of-order execution through reservation stations. Architecture includes:

**Pipeline Stages:**
- **Register File and Rename**: Handles register dependency tracking with register version tags
- **Reservation Stations**: Capture operands from the result bus that were not retrieved from
     the register file.
- **Execution Units**: Parallel functional units for computation
- **Result Bus**: Writeback and dependency resolution network

There is no stage where results are commited since the Bamlet has no loop predication or exceptions.
Programs are expected to terminate with a HALT instruction.

### Register Rename and Dependency Resolution

Dependency resolution is handled by tagging register reads and writes with a register
version tag.  Instruction dispatch is stalled when the rename tags are exhausted.
The physical register file only writes a value when there are no more recently issued
pending writes.  If it is not written then all uses of the register version are
captured by instructions waiting in their reservation stations.

### Reservation Station Microarchitecture

Reservation stations capture operands from the result bus.  The current
defaults are very shallow, ranging from depth of 1 to 4, so they can only do light out-or-order
scheduling.  At this depth operand capturing reservation stations are probably more efficient
than full register renaming (I'm planning on checking this quantitatively in the future).

### Network Architecture

The mesh network provides inter-processor communication and is light-weight with minimal
buffering.  I expect once I start running real workloads on this I'll hit congestion
and deadlocks, but I'm not going to optimize for that until I see the problems.

Routing is X-Y routing.  Each NetworkNode has 5 output handlers per channel and
5 input handlers per channel, representing the 4 directions as well as local use.
Each output handler connects to a single input handler when routing a packet, and will
not connect to another input handler until that packet is fully routed.

Packets include headers with destination coordinates and length. The network supports 
broadcast operations within coordinate rectangles and multiple independent channels.


### Memory Hierarchy

All memory is explicitly managed with no caches.  The instruction memory is expected to be
written using Command Packets over the network and is shared by amlets within a bamlet.  
Each amlet has it's own Data Memory.
