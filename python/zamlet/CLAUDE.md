# Claude Code Guidelines for RISC-V Model

## Wrapping up context
When I say "wrap up this context", do the following:
1. Read this CLAUDE.md file and check if anything needs to be improved or corrected based on what you learned during this session. Make those changes.
2. Write a short summary of where we are at to RESTART.md. This will be used to initialize the next session. Follow the guidelines in "Creating summary" below.

## Creating summary
When cache is running out, I'll ask you to create a summary to restart from.
The purpose of this summary is so that you can continue to work on resolving the problem.
What you have already done is irrelevant. What is important is what is left to do.
Don't be confident about the reasons for things when debugging. You're often wrong and we don't want
to bias the fresh context.

DO NOT include:
- Recent fixes or changes made during this session
- Explanations of bugs that were found and fixed
- Code snippets of changes

DO include:
- Current test status (what passes, what fails)
- The specific failure being investigated
- How to reproduce the failure
- Relevant file paths

## Running Tests
Always redirect test output to a log file in the current directory, then examine the log. This allows
you to search for specific log labels (see Logging Guide below) without re-running the test:
```bash
python tests/conditional/test_conditional_kamlet.py --vector-length 32 > test.log 2>&1
grep "RF_WRITE" test.log
```

## Keeping this up-to-date
If you notice this file is not up-to-date, mention that, and suggest changes.

---

# RISC-V Model Architecture

This document describes the architecture of the RISC-V Vector Processing Unit (VPU) simulator.

## Hierarchy

```
Lamlet (top-level VPU)
├── TLB (address translation)
├── Kamlet[k_in_l] (tile clusters)
│   ├── CacheTable (cache management)
│   ├── KamletRegisterFile (RF tracking)
│   └── Jamlet[j_in_k] (lanes)
│       ├── rf_slice (register file portion)
│       ├── sram (local cache memory)
│       └── routers (message passing)
└── Memlet[k_in_l] (DRAM interfaces)
```

## Key Components

### lamlet.py
Top-level VPU state manager. Entry point for vector load/store operations (`vload()`, `vstore()`). Handles three memory access cases:
- VPU memory aligned (fastest path)
- VPU memory unaligned (requires cross-jamlet data movement)
- Scalar memory (element-by-element transfer)

### kamlet.py
Manages a collection of jamlets (lanes). Responsibilities:
- Instruction queue management
- Cache coordination via CacheTable
- Register file availability tracking
- Dispatching load/store instructions based on alignment:
  - `handle_load_instr_simple()` / `handle_store_instr_simple()` - aligned, matching ew
  - `handle_load_instr_notsimple()` / `handle_store_instr_notsimple()` - unaligned or different ew
  - `handle_load_word_instr()` - unaligned partial word loads crossing cache lines

### jamlet.py
Single lane processor. Handles:
- Local SRAM ↔ register file transfers
- Jamlet-to-jamlet (J2J) message passing for cross-lane data movement
- Router management for NoC communication

Key protocol functions:
- `send_load_j2j_words_req()` / `handle_load_j2j_words_req()` - J2J loads
- `send_store_j2j_words_req()` / `handle_store_j2j_words_req()` - J2J stores
- `send_load_word_req()` / `handle_load_word_req()` - LoadWord unaligned transfers
- `init_load_word_state()` - determines SRC/DST roles for each jamlet

### cache_table.py
Cache management and waiting item coordination. Key concepts:

**Cache States**: INVALID, SHARED, MODIFIED, READING, WRITING, WRITING_READING, UNALLOCATED, OLD_MODIFIED (dirty data for previous address being written back)

**Waiting Items**: Operations blocked on cache or protocol completion
- `WaitingLoadSimple` / `WaitingStoreSimple` - aligned operations
- `WaitingLoadJ2JWords` / `WaitingStoreJ2JWords` - complex J2J transfers
- `WaitingLoadWord` - partial word load crossing cache line boundaries (unaligned)

**Protocol States**: Track multi-message protocols
- `LoadSrcState` / `LoadDstState`
- `StoreSrcState` / `StoreDstState`

States: NEED_TO_SEND → WAITING_FOR_RESPONSE → COMPLETE

### ew_convert.py
Element width conversion and data mapping between different ew-mapped vectors.

Key functions:
- `get_mapping_for_src()` / `get_mapping_for_dst()` - map src/dst data positions
- `get_mapping_from_large_tag()` / `get_mapping_from_small_tag()` - handle ew ratio differences

The `MemMapping` dataclass describes how data maps between src and dst vectors with different element widths.

**Important naming convention**: In `MemMapping`, "src" and "dst" refer to the data flow direction:
- For **Store**: `src` = register, `dst` = memory (data flows register → memory)
- For **Load**: `src` = memory, `dst` = register (data flows memory → register)

The `src_ve`/`dst_ve` fields use **physical** element coordinates. See the "Logical vs Physical Element Coordinates" section in addresses.py below for conversion formulas.

### addresses.py
Address space management and translation chain. See the module docstring in `addresses.py` for detailed documentation on:
- Address translation chain (GlobalAddress → VPUAddress → ... → JSAddr)
- Word ordering (`Ordering.word_order`) and how jamlet (x, y) maps to vw_index
- Logical vs physical element coordinates and conversion formulas

Key types:
- `KMAddr` - Kamlet memory address
- `JSAddr` - Jamlet SRAM address
- `RegAddr` - Vector register byte address

### kinstructions.py
Kamlet-level instruction definitions:
- `Load` / `Store` - vector load/store with ordering, mask, writeset_ident
- `LoadByte`, `LoadWord`, `StoreByte`, `StoreWord` - single element operations
- Arithmetic operations: `VArith`, `VArithImm`, `VDotProduct`

### memlet.py
Memory interface to off-chip DRAM. Handles `READ_LINE` and `WRITE_LINE` requests from jamlets.

### message.py
Message protocol definitions for inter-component communication.

Key message types:
- `LOAD_J2J_WORDS_REQ/RESP/DROP` - jamlet-to-jamlet load protocol
- `STORE_J2J_WORDS_REQ/RESP/DROP/RETRY` - jamlet-to-jamlet store protocol
- `LOAD_WORD_REQ/RESP/DROP/RETRY` - LoadWord protocol for unaligned word loads
- `READ_LINE/WRITE_LINE` - memory to/from cache

Two channels: Channel 0 for always-consumable responses, Channel 1 for requests.

### params.py
System configuration parameters:
- Grid dimensions: `k_cols`, `k_rows`, `j_cols`, `j_rows`
- Memory: `cache_line_bytes`, `vline_bytes`, `page_bytes`, `jamlet_sram_bytes`
- `word_bytes`: 8

**Important**: `cache_line_bytes` is the cache line size for a single kamlet. When working at the lamlet level (e.g., calculating how many elements fit in a cache line for a vector operation), you must multiply by `k_in_l` to get the lamlet-wide cache line size:
```python
lamlet_cache_line_bytes = params.cache_line_bytes * params.k_in_l
```

## Data Flow

### Aligned Load (Simple Path)
1. Kamlet receives Load instruction
2. Check if data in cache (`can_read`)
3. If not, create `WaitingLoadSimple`, request cache line from memory
4. When cache ready, each jamlet copies from SRAM to rf_slice

### Unaligned Load (J2J Path)
1. Kamlet creates `WaitingLoadJ2JWords` with protocol states for each tag
2. Each jamlet sends `LOAD_J2J_WORDS_REQ` with data from cache
3. Destination jamlet receives, shifts/masks data, writes to rf_slice
4. Destination sends `LOAD_J2J_WORDS_RESP` (or `DROP` if not ready)
5. When all protocol states complete, operation finishes

### Store follows similar patterns but data flows rf_slice → SRAM

### Unaligned Word Load (LoadWord Path)
1. Lamlet detects partial element at cache line boundary, creates `LoadWord` instruction
2. Each kamlet (SRC with cache, DST with register) receives instruction, creates `WaitingLoadWord`
3. SRC kamlet waits for cache, sets `src_state=NEED_TO_SEND`
4. DST kamlet sets `dst_state=WAITING_FOR_REQUEST`, waits for data
5. SRC jamlet sends `LOAD_WORD_REQ` with word data to DST jamlet (using absolute coordinates via `k_indices_to_j_coords`)
6. DST jamlet applies byte mask, merges with existing register data
7. DST sends `LOAD_WORD_RESP`, both sides mark COMPLETE
8. If DST not ready, sends `DROP`, SRC retries

## Key Calculations

### Response Tag
```python
response_tag = j_in_k_index * instr.n_tags() + tag
```
Indexes into `protocol_states` array to track each jamlet's progress on each tag.

### Element Width Mapping
When src_ew ≠ dst_ew, data must be remapped between jamlets. The `ew_convert` module calculates which bits from which src jamlet map to which dst jamlet, with appropriate shifts and masks.

### Address Translation
```python
vw_index = addresses.j_coords_to_vw_index(params, word_order, x, y)
k_index, j_in_k_index = addresses.vw_index_to_k_indices(params, word_order, vw_index)
j_x, j_y = addresses.k_indices_to_j_coords(params, k_index, j_in_k_index)
```
The `k_indices_to_j_coords()` function converts kamlet and jamlet indices to absolute jamlet coordinates, used by LoadWord to route messages to the correct DST jamlet.

---

# Logging Guide

This document lists all the logging labels used in the RISC-V VPU simulator and how to grep for them.

## Memory Allocation and Address Translation

### PAGE_ALLOC
**Location**: addresses.py - Page table allocations mapping global to physical addresses
**Format**: `PAGE_ALLOC: global=0x{start:x}-0x{end:x} -> physical=0x{phys:x} memory_loc=0x{start:x}-0x{end:x} is_vpu={bool}`
**Grep**: `grep "PAGE_ALLOC" <logfile>`
**Purpose**: Shows how global address ranges map to physical memory and memory_loc values in kamlets. The memory_loc range indicates which cache lines across all kamlets correspond to this page.
**Example**:
```
PAGE_ALLOC: global=0x20000000-0x200003ff -> physical=0x0 memory_loc=0x0-0x1f is_vpu=True
```

### CACHE_LINE_ALLOC
**Location**: cache_table.py - Cache line allocations in kamlet cache tables
**Format**: `{cycle}: CACHE_LINE_ALLOC: CacheTable ({x}, {y}) slot={slot} memory_loc=0x{loc:x}`
**Grep**: `grep "CACHE_LINE_ALLOC" <logfile>`
**Purpose**: Shows which cache slot in a specific kamlet is allocated for a given memory_loc. Combine with PAGE_ALLOC to trace from global addresses to cache slots.
**Example**:
```
7: CACHE_LINE_ALLOC: CacheTable (0, 0) slot=0 memory_loc=0x0
```

### LOAD_CACHE_CHECK
**Location**: kamlet.py - Cache hit/miss check during load operations
**Format**: `{cycle}: LOAD_CACHE_CHECK: kamlet ({x},{y}) k_maddr.addr=0x{addr:x} memory_loc=0x{loc:x} slot={slot} slot_mem_loc=0x{actual:x} can_read={bool} {HIT|MISS}`
**Grep**: `grep "LOAD_CACHE_CHECK" <logfile>`
**Purpose**: Shows whether a load found its data in cache. Displays the requested memory_loc vs what's actually in the cache slot. Critical for debugging address translation and cache correctness.
**Example**:
```
15546: LOAD_CACHE_CHECK: kamlet (0,0) k_maddr.addr=0x28 memory_loc=0x2 slot=3 slot_mem_loc=0x0 can_read=True HIT
```
Note: If memory_loc != slot_mem_loc but can_read=True, this indicates the cache lookup found the wrong data.

## Memory Operations

### MEM_WRITE
**Location**: memlet.py - Memory writes to off-chip DRAM
**Format**: `MEM_WRITE: kamlet(x,y) addr=0x{address:08x} index={index} data={hex}`
**Grep**: `grep "MEM_WRITE" <logfile>`
**Example**:
```
123: MEM_WRITE: kamlet(0,0) addr=0x00000000 index=0 data=0001010809060103
```

### MEM_READ
**Location**: memlet.py - Memory reads from off-chip DRAM
**Format**: `MEM_READ: kamlet(x,y) addr=0x{address:08x} index={index} data={hex} [(UNINITIALIZED - random)]`
**Grep**: `grep "MEM_READ" <logfile>`
**Example**:
```
456: MEM_READ: kamlet(0,0) addr=0x00000000 index=0 data=0001010809060103
```

## Cache Operations

### CACHE_WRITE READ_LINE_RESP
**Location**: jamlet.py - Cache line fills from memory
**Format**: `CACHE_WRITE READ_LINE_RESP: jamlet (x,y) sram[addr] old={hex} new={hex}`
**Grep**: `grep "CACHE_WRITE READ_LINE_RESP" <logfile>`
**Example**:
```
789: CACHE_WRITE READ_LINE_RESP: jamlet (0,0) sram[0] old=0000000000000000 new=0001010809060103
```

### CACHE_WRITE STORE_SIMPLE
**Location**: jamlet.py - Vector stores to local cache
**Format**: `CACHE_WRITE STORE_SIMPLE: jamlet (x,y) sram[addr] old={hex} new={hex} from rf[reg] mask=0x{mask:016x}`
**Grep**: `grep "CACHE_WRITE STORE_SIMPLE" <logfile>`
**Example**:
```
1003: CACHE_WRITE STORE_SIMPLE: jamlet (0,0) sram[0] old=beab05f1c379b963 new=6400000000000000 from rf[2] mask=0xffffffffffffffff
```

### CACHE_WRITE STORE_J2J
**Location**: jamlet.py - Jamlet-to-jamlet stores
**Format**: `CACHE_WRITE STORE_J2J: jamlet (x,y) sram[addr] old={hex} new={hex}`
**Grep**: `grep "CACHE_WRITE STORE_J2J" <logfile>`
**Example**:
```
1013: CACHE_WRITE STORE_J2J: jamlet (0,0) sram[8] old=728ae4360abd2222 new=0200000000000000
```

### CACHE_WRITE STORE_WORD
**Location**: jamlet.py - Single word stores
**Format**: `CACHE_WRITE STORE_WORD: jamlet (x,y) sram[addr] old={hex} new={hex}`
**Grep**: `grep "CACHE_WRITE STORE_WORD" <logfile>`

### CACHE_WRITE WRITE_IMM_BYTES
**Location**: kamlet.py - Immediate byte writes to cache (used during initialization)
**Format**: `CACHE_WRITE WRITE_IMM_BYTES: jamlet (x,y) sram[start:end] old={hex} new={hex}`
**Grep**: `grep "CACHE_WRITE WRITE_IMM_BYTES" <logfile>`
**Example**:
```
30: CACHE_WRITE WRITE_IMM_BYTES: jamlet (0,0) sram[0:1] old=6e new=00
```

## Register File Operations

### RF_WRITE LOAD_SIMPLE
**Location**: jamlet.py - Simple loads to register file
**Format**: `RF_WRITE LOAD_SIMPLE: jamlet (x,y) rf[reg] old={hex} new={hex} instr_ident={id} mask=0x{mask:016x}`
**Grep**: `grep "RF_WRITE LOAD_SIMPLE" <logfile>`
**Example**:
```
15547: RF_WRITE LOAD_SIMPLE: jamlet (0,0) rf[0] old=0000000000000000 new=0001010809060103 instr_ident=0 mask=0xffffffffffffffff
```

### RF_WRITE LOAD_J2J
**Location**: jamlet.py - Jamlet-to-jamlet loads to register file
**Format**: `RF_WRITE LOAD_J2J: jamlet (x,y) rf[reg] old={hex} new={hex}`
**Grep**: `grep "RF_WRITE LOAD_J2J" <logfile>`

### RF_WRITE VmsleViOp
**Location**: kinstructions.py - Vector mask set-less-than-or-equal-immediate writes
**Format**: `RF_WRITE VmsleViOp: jamlet (x,y) rf[reg] old={hex} new={hex}`
**Grep**: `grep "RF_WRITE VmsleViOp" <logfile>`
**Example**:
```
982: RF_WRITE VmsleViOp: jamlet (0,0) rf[0] old=08 new=08
```

### RF_WRITE VmnandMmOp
**Location**: kinstructions.py - Vector mask NAND writes
**Format**: `RF_WRITE VmnandMmOp: jamlet (x,y) rf[reg] old={hex} new={hex}`
**Grep**: `grep "RF_WRITE VmnandMmOp" <logfile>`

### RF_WRITE VBroadcastOp
**Location**: kinstructions.py - Vector broadcast writes
**Format**: `RF_WRITE VBroadcastOp: jamlet (x,y) rf[reg] old={hex} new={hex}`
**Grep**: `grep "RF_WRITE VBroadcastOp" <logfile>`

### RF_WRITE VmvVvOp
**Location**: kinstructions.py - Vector move writes
**Format**: `RF_WRITE VmvVvOp: jamlet (x,y) rf[reg] old={hex} new={hex}`
**Grep**: `grep "RF_WRITE VmvVvOp" <logfile>`

### RF_WRITE VArithVvOp
**Location**: kinstructions.py - Vector arithmetic writes
**Format**: `RF_WRITE VArithVvOp({operation}): jamlet (x,y) rf[reg] old={hex} new={hex}`
**Grep**: `grep "RF_WRITE VArithVvOp" <logfile>`

### RF START / RF FINISH
**Location**: register_file_slot.py - Register file locking for hazard tracking
**Format**: `kamlet(x,y) RF START token={id} read_regs=[...] write_regs=[...]`
**Format**: `kamlet(x,y) RF FINISH token={id} read_regs=[...] write_regs=[...]`
**Grep**: `grep "RF START\|RF FINISH" <logfile>`
**Purpose**: Shows when instructions acquire and release locks on register file slots. Critical for debugging WAR/RAW hazards. The token identifies the instruction, read_regs shows registers being read, write_regs shows registers being written.
**Example**:
```
kamlet(0,0) RF START token=5 read_regs=[1, 2] write_regs=[]
kamlet(0,0) RF FINISH token=5 read_regs=[1, 2] write_regs=[]
```

## Common Grep Patterns

### Find all writes to a specific register at a specific jamlet
```bash
grep "RF_WRITE.*jamlet (0,0).*rf\[2\]" <logfile>
```

### Find all writes to a specific cache address at a specific jamlet
```bash
grep "CACHE_WRITE.*jamlet (0,0).*sram\[0\]" <logfile>
```

### Find all memory operations for a specific kamlet
```bash
grep "MEM_.*kamlet(0,0)" <logfile>
```

### Track data flow for a global address
```bash
# Example: Tracing global address 0x20000050

# 1. Find which page and memory_loc range this address belongs to
grep "PAGE_ALLOC.*global=0x20000000" <logfile>
# Output: PAGE_ALLOC: global=0x20000000-0x200003ff -> physical=0x0 memory_loc=0x0-0x1f is_vpu=True

# 2. Find which cache slots are allocated for those memory_locs
grep "CACHE_LINE_ALLOC.*memory_loc=0x[01]" <logfile>
# Output: CACHE_LINE_ALLOC: CacheTable (0, 0) slot=0 memory_loc=0x0

# 3. Find cache writes during initialization
grep "CACHE_WRITE WRITE_IMM_BYTES.*jamlet (0,0)" <logfile>

# 4. Find cache line loads from memory
grep "CACHE_WRITE READ_LINE_RESP.*jamlet (0,0)" <logfile>

# 5. Find register file loads
grep "RF_WRITE LOAD_SIMPLE.*jamlet (0,0)" <logfile>
```

### Find all operations in a cycle range
```bash
grep "^2025.*15[45][0-9][0-9]:" <logfile>
```

---

# Comparing Test Execution with Logs

This document contains techniques and examples for verifying that the simulator is correctly executing tests by comparing expected behavior with log output.

## Verifying Memory Initialization

### Using objdump to get expected data

First, examine the test binary to see what data should be in memory:

```bash
# Show section headers
riscv64-unknown-elf-objdump -h tests/conditional/vec-conditional.riscv

# Dump contents of a specific section
riscv64-unknown-elf-objdump -s -j .data.vpu8 tests/conditional/vec-conditional.riscv | grep "20000000"
```

Example output:
```
20000000 00030103 01010802 09050600 01060307  ................
```

This shows that at global address 0x20000000, the bytes should be:
`00 03 01 03 01 01 08 02 09 05 06 00 01 06 03 07`

### Tracing initialization in logs

Use the PAGE_ALLOC and CACHE_WRITE logs to verify initialization:

```bash
# Step 1: Find which page the address belongs to
grep "PAGE_ALLOC.*global=0x20000000" <logfile>
# Output: PAGE_ALLOC: global=0x20000000-0x200003ff -> physical=0x0 memory_loc=0x0-0x1f is_vpu=True

# Step 2: Check what bytes were written during initialization
grep "Writing  byte 0x2000000[0-9a-f] " <logfile> | head -16

# Step 3: Look at cache writes during initialization
grep "CACHE_WRITE WRITE_IMM_BYTES" <logfile> | head -30
```

### Understanding data distribution across jamlets

**Key insight**: Data is distributed element-by-element across jamlets.

With 2 jamlets (k_in_l=2, j_in_k=1), consecutive elements alternate between jamlets. In this example with 8-bit elements (ew=8), each element is 1 byte:
- Element 0 (byte 0) → jamlet (0,0) sram[0]
- Element 1 (byte 1) → jamlet (1,0) sram[0]
- Element 2 (byte 2) → jamlet (0,0) sram[1]
- Element 3 (byte 3) → jamlet (1,0) sram[1]
- ...

For wider elements (e.g., ew=16 or ew=32), the same pattern applies but each element is multiple bytes.

Example verification for address 0x20000000:

Expected bytes from objdump: `00 03 01 03 01 01 08 02 09 05 06 00 01 06 03 07`

From logs:
- Jamlet (0,0): sram[0]=0x00, sram[1]=0x01, sram[2]=0x01, sram[3]=0x08, sram[4]=0x09, sram[5]=0x06, sram[6]=0x01, sram[7]=0x03
- Jamlet (1,0): sram[0]=0x03, sram[1]=0x03, sram[2]=0x01, sram[3]=0x02, sram[4]=0x05, sram[5]=0x00, sram[6]=0x06, sram[7]=0x07

Interleaving: `00 03 01 03 01 01 08 02 09 05 06 00 01 06 03 07` ✓ Match!

### Creating a summary table

Use this script to create a comparison table:

```bash
#!/bin/bash
echo "EXPECTED (from objdump):"
riscv64-unknown-elf-objdump -s -j .data.vpu8 <binary> | grep "20000000" | head -1

echo ""
echo "ACTUAL (from logs):"
echo "=========================================================================="
printf "%-10s %-12s %-15s %-15s\n" "Cycle" "Jamlet" "SRAM" "Value"
echo "--------------------------------------------------------------------------"
grep "CACHE_WRITE WRITE_IMM_BYTES: jamlet" <logfile> | head -30 | while read line; do
    cycle=$(echo "$line" | grep -oP '- \K\d+')
    jamlet=$(echo "$line" | grep -oP 'jamlet \K\([0-9,]+\)')
    sram=$(echo "$line" | grep -oP 'sram\K\[[0-9:]+\]')
    newval=$(echo "$line" | grep -oP 'new=\K[0-9a-f]+')
    printf "%-10s %-12s %-15s %-15s\n" "$cycle" "$jamlet" "$sram" "0x$newval"
done
```

## Verifying Vector Loads

### Check what instruction loaded the data

```bash
# Find the vector load instruction
grep "VLE8.V: vd=v0, addr=0x20000050" <logfile>
# Output: 15546: VLE8.V: vd=v0, addr=0x20000050, vl=16, masked=False, mask_reg=None
```

### Verify data was loaded correctly into register file

```bash
# Find register file writes after the load
grep "15547: RF_WRITE LOAD_SIMPLE" <logfile>
```

Example output:
```
15547: RF_WRITE LOAD_SIMPLE: jamlet (0,0) rf[0] old=0000000000000000 new=0001010809060103
15549: RF_WRITE LOAD_SIMPLE: jamlet (1,0) rf[0] old=0000000000000000 new=0303010205000607
```

The register values are in little-endian format (bytes reversed in each word).

To verify, convert to byte arrays:
- jamlet (0,0) rf[0] = 0x0001010809060103 → bytes: `03 01 06 09 08 01 01 00`
- jamlet (1,0) rf[0] = 0x0303010205000607 → bytes: `07 06 00 05 02 01 03 03`

Interleaved: `03 07 01 06 06 00 09 05 08 02 01 01 01 03 00 03` (alternating bytes from each jamlet)

Compare with objdump at the load address to verify correctness.

## Common Pitfalls

### Timing delays
The "Writing byte" log at cycle N does not mean the cache write happens at cycle N. There's a delay while the instruction propagates through the system. Look for CACHE_WRITE logs at later cycles.

### Little-endian byte order
Register file values in logs are shown as hex numbers in little-endian format. The least significant byte is the first byte in memory.

Example: `0x0001010809060103` in register = bytes `03 01 06 09 08 01 01 00` in memory order

### Cache eviction
Cache slots can be evicted and reallocated. A CACHE_LINE_ALLOC for the same slot number may happen multiple times. The second allocation overwrites the first.

### Multiple operations per cycle
Multiple cache writes or other operations can happen in the same cycle. Don't assume one log line per cycle.

## Quick Reference Commands

```bash
# Verify initialization of first 16 bytes at address 0x20000000
riscv64-unknown-elf-objdump -s -j .data.vpu8 <binary> | grep "20000000"
grep "CACHE_WRITE WRITE_IMM_BYTES" <logfile> | head -30

# Trace a specific global address through the system
addr=0x20000050
grep "PAGE_ALLOC.*global=0x20000000" <logfile>
grep "Writing  byte $addr" <logfile>
grep "VLE.*addr=$addr" <logfile>

# Check register file state after a load
grep "RF_WRITE LOAD_SIMPLE.*jamlet (0,0).*rf\[0\]" <logfile>
```
