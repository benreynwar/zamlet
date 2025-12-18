# Lamlet Top-Level Design

**WARNING: This is a rough sketch. Many details are speculative, incomplete, or wrong.
Do not trust this document - verify everything before relying on it.**

**NOTE TO CLAUDE: Do not remove this warning.**

---

The Lamlet is the scalar-VPU interface and coordination unit. It connects to the scalar core
(Rocket/Shuttle), handles instruction decode, fault checking, disambiguation, and dispatches
kinstrs to the kamlet mesh.

## Pipeline Overview

The IssueUnit contains a 4-stage pipeline:

```
DECODE → ADDR + TLB + FAULT → DISPATCH → BLOCKING
```

- **DECODE**: Parse RISC-V instruction, classify, extract fields
- **ADDR + TLB + FAULT**: Address generation, TLB lookup, fault check (unit stride only)
- **DISPATCH**: Generate kinstr(s), send to mesh. Stalls if store_pending, idents exhausted, etc.
- **BLOCKING**: Most instructions pass through. Strided/indexed wait for FaultChecker result.

For strided/indexed ops, FaultChecker runs in parallel with mesh execution.

## External Interfaces

### VectorCoreIO (from scalar core)

Standard RocketChip interface for vector unit integration. We reuse Saturn's interface.

```
VectorCoreIO
├── status: MStatus                    # Privilege mode, VM settings
│
├── ex (Execute stage - instruction dispatch)
│   ├── IN:  valid                     # Instruction valid
│   ├── IN:  inst[31:0]                # Instruction bits
│   ├── IN:  pc                        # Program counter
│   ├── IN:  vconfig (vtype + vl)      # Current vector config
│   ├── IN:  vstart                    # Starting element
│   ├── IN:  rs1, rs2                  # Scalar register operands
│   └── OUT: ready                     # Can accept instruction
│
├── mem (Memory stage)
│   ├── IN:  frs1                      # FP scalar operand
│   ├── OUT: block_mem                 # Block scalar memory ops
│   └── OUT: block_all                 # Block all scalar ops
│
├── killm: Bool                        # Kill instruction in M stage
│
├── wb (Writeback stage - commit/fault)
│   ├── IN:  store_pending             # Scalar store buffer not empty
│   ├── IN:  vxrm[1:0]                 # Vector fixed-point rounding mode
│   ├── IN:  frm[2:0]                  # FP rounding mode
│   ├── OUT: replay                    # Request instruction replay
│   ├── OUT: retire                    # Instruction retiring
│   ├── OUT: inst[31:0]                # Retiring instruction bits
│   ├── OUT: xcpt                      # Exception
│   ├── OUT: cause                     # Exception cause
│   └── OUT: tval                      # Trap value
│
├── resp (Scalar result from vector op)
│   ├── valid/ready                    # Decoupled
│   ├── fp: Bool                       # Is FP result
│   ├── rd[4:0]                        # Destination register
│   └── data                           # Result data
│
├── set_vstart: Valid[UInt]            # Update vstart CSR
├── set_vxsat: Bool                    # Update vxsat CSR
├── set_vconfig: Valid[VConfig]        # Update vtype/vl CSRs
├── set_fflags: Valid[UInt(5.W)]       # Update FP flags
│
├── trap_check_busy: Bool              # Fault checking in progress
└── backend_busy: Bool                 # Backend has outstanding ops
```

### ScalarCheck (disambiguation for scalar memory)

Physical address from scalar memory ops, checked against pending vector ops.
Directly from Shuttle or via TLB tap for Rocket.

```
ScalarCheck
├── IN:  addr                          # Physical address of scalar mem op
├── IN:  size[1:0]                     # Access size (1/2/4/8 bytes)
├── IN:  store                         # Is this a store?
└── OUT: conflict                      # Conflicts with pending vector op
```

### ScalarVmemPort (scalar accessing vector memory)

When scalar core accesses memlet DRAM. TileLink interface, converted to kinstr internally
via ScalarToKinstr.

```
ScalarVmemPort (TileLink)
├── tl_a.*                             # TileLink request from scalar core
└── tl_d.*                             # TileLink response to scalar core
```

### ScalarMemPort (vector accessing scalar memory)

Vector ops that target scalar-associated memory. TileLink interface, used by VpuToScalarMem.

```
ScalarMemPort (TileLink)
├── tl_a.*                             # TileLink request to scalar memory
└── tl_d.*                             # TileLink response from scalar memory
```

### TLBPort (to scalar core's TLB)

Shared TLB access for address translation.

```
TLBPort
├── req (Decoupled)
│   ├── vaddr                          # Virtual address
│   ├── cmd                            # Load/Store
│   └── size[1:0]                      # Access size
│
└── resp
    ├── paddr                          # Physical address
    ├── miss                           # TLB miss (need page walk)
    └── xcpt                           # Page fault
```

### MeshPort (to kamlet mesh)

Router network connection to the kamlet mesh. Two channels with separate send/receive.

```
MeshPort
├── ch0_send                           # Instructions and responses to mesh
├── ch0_recv                           # Responses from mesh
├── ch1_send                           # Requests to mesh (ordered stores)
└── ch1_recv                           # Requests from mesh (ReadMemWord, WriteMemWord)
```

### SyncPort (to kamlet sync network)

Separate synchronization network for coordinated operations across kamlets.

```
SyncPort
├── sync_out                           # Sync bytes to kamlet network
└── sync_in                            # Sync bytes from kamlet network
```

## Submodules

### IssueUnit

Converts RISC-V vector instructions to 64-bit kinstrs. Contains the 4-stage pipeline
(DECODE → ADDR+TLB+FAULT → DISPATCH → BLOCKING). See `issue-unit.md` for details.

```
IssueUnit
├── IN:  inst[31:0]                    # From VectorCoreIO.ex
├── IN:  vconfig                       # vtype + vl
├── IN:  vstart
├── IN:  rs1, rs2, frs1                # Scalar operands
├── IN:  store_pending                 # From scalar core (stalls DISPATCH)
├── IN:  fault_check_result            # From FaultChecker
├── IN:  ordered_complete              # From OrderedBuffer (release DISPATCH)
├── IN:  ident                         # From IdentTracker
│
├── OUT: kinstr                        # To DispatchQueue
├── OUT: kinstr_valid
├── OUT: ordered_kinstr                # To OrderedBuffer (for ordered indexed ops)
├── OUT: fault_check_req               # To FaultChecker (strided/indexed)
├── OUT: alloc_req                     # To IdentTracker
├── OUT: decode_error                  # Illegal instruction
└── OUT: blocking                      # Waiting for fault check (stalls next instr)
```

### FaultChecker

Runs in parallel with mesh execution for strided/indexed ops. Enumerates pages touched
by the access pattern and checks permissions. IssueUnit's BLOCKING stage waits for result.

For unit-stride ops, IssueUnit checks faults directly (1-2 pages) and doesn't use FaultChecker.

```
FaultChecker
├── IN:  fault_check_req               # From IssueUnit
│        ├── base_addr
│        ├── stride (or index pattern info)
│        ├── vl, eew
│        └── addressing_mode
├── IN:  tlb_resp                      # From TLB
│
├── OUT: tlb_req                       # To TLB
├── OUT: check_complete                # Fault check finished
├── OUT: fault                         # Fault detected
├── OUT: fault_elem                    # First faulting element index
└── OUT: fault_cause                   # Fault cause code
```

**Fault checking strategy by access type:**

| Type | Strategy | Who checks |
|------|----------|------------|
| Unit-stride | Check 1-2 pages upfront | IssueUnit (inline) |
| Strided | Parallel page enumeration | FaultChecker |
| Indexed | Per-element in kamlets | Kamlets (via sync) |
| Bounded | Single region check | FaultChecker |

### TLB

Authoritative TLB for lamlet. Kamlets have TLB caches. Two ports for concurrent access.

```
TLB
├── Port 0 (IssueUnit)
│   ├── IN:  req.{vaddr, cmd, size}
│   └── OUT: resp.{paddr, miss, xcpt, ew, word_order}
│
├── Port 1 (FaultChecker)
│   ├── IN:  req.{vaddr, cmd, size}
│   └── OUT: resp.{paddr, miss, xcpt}

Submodules:
├── AuthoritativeTLB                   # Main TLB array
├── PageTableWalker                    # Handle misses
└── MetadataTable                      # VPU-specific: ew, word_order
```

### IdentTracker

Tracks in-flight instructions via unique identifiers. Manages per-kamlet token counts for
flow control. Generates IdentQuery kinstrs when tokens or idents run low.

```
IdentTracker
├── IN:  alloc_req                     # Request new ident (from IssueUnit)
├── IN:  sync_result                   # From Synchronizer (oldest active ident)
│
├── OUT: allocated_ident               # New ident for kinstr
├── OUT: backend_busy                  # To VectorCoreIO
├── OUT: ident_query_kinstr            # To DispatchQueue (high priority)
├── OUT: ident_query_valid             # IdentQuery ready to dispatch
├── OUT: sync_request                  # To Synchronizer (trigger IdentQuery)

State:
├── available_tokens[k_in_l]           # Per-kamlet instruction queue slots
├── tokens_used_since_query[k_in_l]    # Accumulates until query sent
├── tokens_in_active_query[k_in_l]     # Returned when response arrives
├── next_instr_ident                   # 7-bit wrapping allocator
├── oldest_active_ident                # From last query response
└── ident_query_state                  # DORMANT / READY_TO_SEND / WAITING
```

**IdentQuery trigger conditions:**
- Any kamlet has `available_tokens < threshold`
- Idents running low (`next_instr_ident` approaching `oldest_active_ident`)

### Synchronizer

Lamlet endpoint of the synchronization network. Provides primitive sync operations
(MIN, OR aggregation) across all kamlets. Used by other modules for coordinated operations.

```
Synchronizer
├── IN:  sync_request                  # From IssueUnit or other modules
│        ├── sync_ident
│        └── aggregation_type          # MIN or OR
├── IN:  sync_network_in               # From kamlet sync network
│
├── OUT: sync_network_out              # To kamlet sync network
├── OUT: sync_complete                 # Sync finished
├── OUT: sync_result                   # Aggregated value (min ident, OR'd flags, etc.)
```

**Used by:**
- IdentTracker: MIN aggregation to find oldest active ident
- FlagCollector: OR aggregation for vxsat, fflags
- FaultChecker: MIN aggregation for first faulting element

### FlagCollector

Collects vxsat and fflags from kamlets via sync network OR aggregation. Reports to
scalar core via VectorCoreIO.

```
FlagCollector
├── IN:  collect_request               # Trigger collection (from IssueUnit on sync instr)
├── IN:  sync_result                   # From Synchronizer (OR'd flags)
│
├── OUT: sync_request                  # To Synchronizer
├── OUT: set_vxsat                     # To VectorCoreIO
├── OUT: set_fflags                    # To VectorCoreIO
```

### Disambiguator

Blocks scalar memory ops that conflict with pending vector memory ops targeting scalar memory.
Vector→scalar ops (via VpuToScalarMem) always proceed without blocking.

```
Disambiguator
├── IN:  scalar_check.{addr, size, store}  # From scalar core
├── IN:  vector_mem_dispatch               # From DispatchQueue (addr range of dispatched op)
├── IN:  vector_mem_complete               # From Ch0Receiver (op completed)
│
├── OUT: scalar_check.conflict             # Block scalar mem op (causes replay)
```

**State:**
- PendingRangeCAM: tracks address ranges of in-flight vector ops targeting scalar memory

**Rules:**
- Scalar mem op conflicts with entry in CAM → set `conflict`, scalar replays

### VpuToScalarMem

Bridges mesh messages to scalar memory via TileLink. When kamlets need to access scalar
memory (e.g., indexed ops hitting scalar addresses), they send ReadMemWord/WriteMemWord
messages to the lamlet. This module converts them to TileLink requests and routes responses
back.

```
VpuToScalarMem
├── IN:  mesh_packet                   # ReadMemWord/WriteMemWord from Ch1Receiver
├── IN:  tl_d.*                        # TileLink response from scalar memory
│
├── OUT: tl_a.*                        # TileLink request to scalar memory
├── OUT: resp_packet                   # Response packet back to mesh (resp or DROP)
```

**State:**
- Request table: tracks in-flight TileLink requests (maps TL source → mesh packet header)

**Flow control:**
- If request table full, send DROP response immediately (kamlet will retry)

### ScalarToKinstr

Bridges TileLink requests from the scalar core (for VPU memory addresses) into the
IssueUnit pipeline. See `scalar-to-kinstr.md` for details.

```
ScalarToKinstr
├── IN:  tl_a.*                        # TileLink request from scalar core
├── IN:  resp (from Ch0Receiver)       # Response from mesh
│        ├── ident
│        └── data
│
├── OUT: scalar_req (to IssueUnit)     # Request info
│        ├── addr, size, is_store, data
├── IN:  scalar_req.ident              # Allocated ident from IssueUnit
│
└── OUT: tl_d.*                        # TileLink response to scalar core
```

### Ch0Receiver

Receives channel 0 packets from mesh (responses). Must consume immediately - no backpressure.

```
Ch0Receiver
├── IN:  router_ch0_packet             # From router network
│
├── OUT: to_scalar_to_kinstr           # Scalar load responses
├── OUT: to_ordered_buffer             # Element completions (LOAD/STORE_INDEXED_ELEMENT_RESP)
├── OUT: to_disambiguator              # Instruction completions (for CAM removal)
```

**Message types handled:**
- READ_BYTE_RESP, READ_WORDS_RESP
- LOAD_INDEXED_ELEMENT_RESP, STORE_INDEXED_ELEMENT_RESP
- WRITE_MEM_WORD_RESP, WRITE_MEM_WORD_DROP, WRITE_MEM_WORD_RETRY

### Ch1Receiver

Receives channel 1+ packets from mesh (requests). Can apply backpressure.

```
Ch1Receiver
├── IN:  router_ch1_packet             # From router network
│
├── OUT: to_vpu_to_scalar_mem          # ReadMemWord/WriteMemWord requests
```

**Message types handled:**
- READ_MEM_WORD_REQ
- WRITE_MEM_WORD_REQ

### Ch0Sender

Sends channel 0 packets to mesh (instructions and responses).

```
Ch0Sender
├── IN:  from_dispatch_queue           # Instruction packets
├── IN:  from_vpu_to_scalar_mem        # READ_MEM_WORD_RESP
├── IN:  from_ordered_buffer           # WRITE_MEM_WORD_RESP
│
├── OUT: router_ch0_packet             # To router network
```

**Message types sent:**
- INSTRUCTIONS
- READ_MEM_WORD_RESP
- WRITE_MEM_WORD_RESP

### Ch1Sender

Sends channel 1+ packets to mesh (requests).

```
Ch1Sender
├── IN:  from_ordered_buffer           # WRITE_MEM_WORD_REQ (ordered stores to VPU mem)
│
├── OUT: router_ch1_packet             # To router network
```

**Message types sent:**
- WRITE_MEM_WORD_REQ

### OrderedBuffer

For ordered indexed operations that require element-by-element ordering. IssueUnit holds
the instruction in DISPATCH while OrderedBuffer processes elements.

```
OrderedBuffer
├── IN:  ordered_kinstr                # Ordered indexed op (from IssueUnit)
├── IN:  element_completions           # Per-element completions (from Ch0Receiver)
│
├── OUT: element_kinstr                # Dispatch elements in order (to DispatchQueue)
├── OUT: op_complete                   # All elements done (to IssueUnit - release DISPATCH)
└── OUT: write_mem_req                 # Ordered store requests (to Ch1Sender)
```

### DispatchQueue

Queues kinstrs for dispatch to mesh. Handles arbitration between multiple sources with
different priorities. Enforces token-based flow control.

```
DispatchQueue
├── IN:  ident_query_kinstr            # From IdentTracker (high priority)
├── IN:  ident_query_valid
├── IN:  ordered_kinstr                # From OrderedBuffer (medium priority)
├── IN:  ordered_valid
├── IN:  issuer_kinstr                 # From IssueUnit (normal priority)
├── IN:  issuer_valid
├── IN:  available_tokens[k_in_l]      # From IdentTracker
│
├── OUT: mesh_kinstr                   # To Ch0Sender
├── OUT: mesh_valid
├── OUT: ident_query_ready             # Backpressure to IdentTracker
├── OUT: ordered_ready                 # Backpressure to OrderedBuffer
├── OUT: issuer_ready                  # Backpressure to IssueUnit
├── OUT: token_used[k_in_l]            # To IdentTracker (decrement tokens)
```

**Priority arbitration:**
1. IdentQuery (high) - uses reserved token, must not starve
2. OrderedBuffer (medium) - time-sensitive in-order processing
3. IssueUnit (normal) - regular instruction flow

**Token rules:**
- Regular kinstrs require `available_tokens[k] > 1` (reserve last token for IdentQuery)
- IdentQuery only requires `available_tokens[k] > 0`
- Broadcast kinstrs check all kamlets

## Key Design Decisions

1. **Post-commit execution**: Like Saturn, kinstrs dispatched to mesh are committed from
   scalar core's perspective. Simplifies disambiguation.

2. **Distributed fault checking**: Unlike Saturn's centralized IFC, faults for indexed ops
   are checked in kamlets. Idempotent memory allows stores past fault point.

3. **Bounded instructions**: New `vluxei_bounded`, `vlse_bounded` variants allow fast
   parallel region checking instead of per-element.

4. **Scalar→vmem via kinstr**: Scalar accesses to vector memory become kinstrs in the
   queue (via ScalarToKinstr), naturally ordered with vector ops.

5. **Vector→scalar via TileLink**: VpuToScalarMem bridges mesh requests to scalar memory.
   No blocking - DROP and retry if request table full.

6. **IssueUnit handles stalling**: store_pending stalling is handled in IssueUnit's
   DISPATCH stage, not DispatchQueue.
