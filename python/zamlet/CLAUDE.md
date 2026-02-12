# Claude Code Guidelines for RISC-V Model

## CRITICAL: No Defensive None Checks

**DO NOT add `if x is None` or `if x is not None` checks that silently handle unexpected states.** This is the most common mistake and it hides serious bugs. If a value should never be None at a point in the code, access it directly and let it fail with a clear error if the assumption is wrong.

## CRITICAL: Never Remove Assert Statements

**DO NOT remove assert statements when tidying or refactoring code.** Assert statements are valuable for catching bugs early. When cleaning up code (removing logging, simplifying, etc.), always preserve existing assert statements.

Bad:
```python
miid = lookup.get(key)
if miid is not None:
    self.complete_item(miid)
```

Good:
```python
miid = lookup[key]  # Will raise KeyError if missing - that's a bug we want to see
self.complete_item(miid)
```

The same applies to other defensive patterns. If something should exist, assert it exists or access it directly. Don't silently skip over unexpected states.

## Project Overview
This is a Python project for experimenting with hardware design. It simulates a RISC-V Vector Processing Unit (VPU). Make liberal use of assert statements - failing with good error messages is useful and should not be avoided. Prefer asserting expected conditions over defensive if-checks that silently handle unexpected states. If something is probably true, assert it and reassess if the assertion fails.

## Communication Style
When I ask you to show me something (e.g., grep output, log excerpts), just show it and wait. Don't continue with analysis unless I ask for it. Continuing will hide what I asked for behind walls of other output.

## RISC-V ISA Manual Location
The RISC-V ISA manual is located at `~/Code/riscv-isa-manual`. The vector extension spec is at:
```
~/Code/riscv-isa-manual/src/v-st-ext.adoc
```

## Wrapping up context
When I say "wrap up this context", write a short summary of where we are at to RESTART.md. This will be used to initialize the next session. Follow the guidelines in "Creating summary" below.

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
- **The big picture goal** - What are we ultimately trying to achieve? Reference any PLAN_*.md files. This is the most important part - don't lose sight of why we're doing something.
- Current test status (what passes, what fails)
- The specific failure being investigated (if debugging)
- How to reproduce the failure
- Relevant file paths
- What step of the plan we're on (if following a plan)

The RESTART.md should allow a fresh context to understand both *what* we're doing and *why*. Start with the big picture, then narrow down to the current task.

**Important**: The big picture often already exists in RESTART.md from when the session started. Preserve it - the scope should not narrow from one session to the next. If the session started with a goal like "implement monitoring system", don't reduce it to just "fix this one bug".

## Running Tests
ALWAYS redirect test output to a log file in the current directory, then examine the log. NEVER run a
test without redirecting to a log file - this avoids having to re-run tests to see different parts of
the output:
```bash
python -m pytest kernel_tests/conditional/test_conditional.py -v > test.log 2>&1
```

### Running tests directly (without pytest)
Tests in `tests/` can be run directly with Python. Use `--list-geometries` to see available
configurations. Test names from pytest encode the parameters:

```
# pytest test name: test_strided_store[14_k2x2_j1x2_ew32_vl127_s3657]
# Format: {index}_{geometry}_ew{ew}_vl{vl}_s{stride}
# Decodes to: geometry=k2x2_j1x2, ew=32, vl=127, stride=3657, seed=14
python tests/test_strided_store.py -g k2x2_j1x2 --ew=32 --vl=127 --stride=3657 --seed=14 --dump-spans > tests/log.txt 2>&1
```

## Reading Files
NEVER use `cat` to read files. Always use the Read tool instead.

Tests are organized into:
- `kernel_tests/` - Integration tests running RISC-V binaries through run_lamlet
- `tests/` - Unit/component tests for specific functionality

## Keeping this up-to-date
If you notice this file is not up-to-date, mention that, and suggest changes.

## Bug Investigation
When you find and fix a bug, always search for similar bugs elsewhere in the codebase:
- If the bug is in a pattern (e.g., missing page alignment), grep for similar patterns in other files
- If it's in one of a pair of functions (e.g., load_stride/store_stride), check the counterpart
- If it's in test code, check other test files for the same issue
- Document the search you did and what you found

---

# RISC-V Model Architecture

This document describes the architecture of the RISC-V Vector Processing Unit (VPU) simulator.

## Hierarchy

```
Zamlet (top-level VPU)
├── TLB (address translation)
├── Monitor (distributed tracing)
├── Kamlet[k_in_l] (tile clusters)
│   ├── CacheTable (cache management + waiting items)
│   ├── KamletRegisterFile (RF tracking)
│   ├── Synchronizer (cross-kamlet sync)
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
- Router management for NoC communication
- Message dispatch via `MESSAGE_HANDLERS` registry from `transactions/`

Note: Protocol functions have been moved to the `transactions/` package.

### cache_table.py
Cache management and waiting item coordination. Key concepts:

**Cache States**: INVALID, SHARED, MODIFIED, READING, WRITING, WRITING_READING, UNALLOCATED, OLD_MODIFIED (dirty data for previous address being written back)

**Protocol States**: Track multi-message protocols via `SendState` and `ReceiveState`:
- `SendState`: NEED_TO_SEND → WAITING_FOR_RESPONSE → COMPLETE
- `ReceiveState`: WAITING_FOR_REQUEST → NEED_TO_ASK_FOR_RESEND → COMPLETE

**Waiting Items**: Most waiting items are now in the `transactions/` package (see below).
`cache_table.py` still contains:
- `WaitingFuture` - for awaiting async responses
- `WaitingStoreJ2JWords` - J2J store operations
- `LoadProtocolState` / `StoreProtocolState` - protocol state tracking

### transactions/ (package)
Transaction logic has been refactored into separate modules for better organization:

- `load_simple.py` - `WaitingLoadSimple`, aligned loads from cache to RF
- `store_simple.py` - `WaitingStoreSimple`, aligned stores from RF to cache
- `load_j2j_words.py` - `WaitingLoadJ2JWords`, unaligned J2J loads
- `store_j2j_words.py` - J2J store message handlers
- `load_word.py` - `WaitingLoadWordSrc`, `WaitingLoadWordDst`, partial word loads
- `store_word.py` - `WaitingStoreWordSrc`, `WaitingStoreWordDst`, partial word stores
- `load_stride.py` - `WaitingLoadStride`, strided loads with arbitrary stride
- `store_stride.py` - `WaitingStoreStride`, strided stores with arbitrary stride
- `write_imm_bytes.py` - `WaitingWriteImmBytes`, immediate byte writes
- `read_byte.py` - `WaitingReadByte`, single byte reads
- `read_mem_word.py` - `WaitingReadMemWord`, memory word read operations
- `write_mem_word.py` - `WaitingWriteMemWord`, memory word write operations
- `ident_query.py` - `WaitingIdentQuery`, instruction identifier flow control
- `j2j_mapping.py` - `RegMemMapping`, element width conversion helpers
- `helpers.py` - Shared utility functions

Each transaction module registers its message handlers via `@register_handler` decorator.

### synchronization.py
Lamlet-wide synchronization network for tracking when events have occurred across all kamlets.
Uses a separate 9-bit wide bus network (not the main router) with direct neighbor connections
(N, S, E, W, NE, NW, SE, SW). Supports optional minimum value aggregation.

**Bus Format**: `[8]=last_byte, [7:0]=data`
**Packet Format**: `Byte 0: sync_ident, Bytes 1+: value (1-4 bytes, little-endian)`

Used by:
- `LoadStride` / `StoreStride`: Wait for all tags to complete
- `IdentQuery`: Find minimum oldest active ident across kamlets

### monitor.py
Distributed tracing system based on spans. See "Monitoring System" section below for details.

### ew_convert.py
Element width conversion and data mapping between different ew-mapped vectors.
See the module docstring for detailed documentation on tags, coordinates, and mapping concepts.

**Important naming convention**: "src" and "dst" refer to the data flow direction:
- For **Store**: `src` = register, `dst` = memory (data flows register → memory)
- For **Load**: `src` = memory, `dst` = register (data flows memory → register)

Coordinates use **physical** element positions (distributed across jamlets).
See addresses.py for logical vs physical coordinate conversion.

Note: Some mapping functionality has moved to `transactions/j2j_mapping.py` which provides
`RegMemMapping` dataclass and `get_mapping_from_reg()` / `get_mapping_from_mem()` functions.

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
- `Load` / `Store` - vector load/store with ordering, mask, writeset_ident support
- `LoadStride` / `StoreStride` - strided vector load/store (arbitrary stride)
- `LoadWord` / `StoreWord` - single word operations for unaligned accesses
- `LoadImmByte` / `LoadImmWord` - immediate value loads
- `WriteImmBytes` / `ReadByte` - memory initialization and byte reads
- `ZeroLines` / `DiscardLines` - cache line management
- `IdentQuery` - instruction identifier flow control query
- Arithmetic: `VArithVvOp`, `VArithVxOp` (add, mul, macc)
- Mask: `VmsleViOp`, `VmnandMmOp`
- Move: `VBroadcastOp`, `VmvVvOp`
- Reduction: `VreductionVsOp`
- Scalar read: `ReadRegElement`

All KInstr classes implement `create_span(monitor, parent_span_id)` for monitoring integration.

### memlet.py
Memory interface to off-chip DRAM. Handles `READ_LINE` and `WRITE_LINE` requests from jamlets.

### message.py
Message protocol definitions for inter-component communication.

Key message types:
- `LOAD_J2J_WORDS_REQ/RESP/DROP/RETRY` - jamlet-to-jamlet load protocol
- `STORE_J2J_WORDS_REQ/RESP/DROP/RETRY` - jamlet-to-jamlet store protocol
- `LOAD_WORD_REQ/RESP/DROP` - LoadWord protocol for unaligned word loads
- `STORE_WORD_REQ/RESP/DROP/RETRY` - StoreWord protocol for unaligned word stores
- `READ_MEM_WORD_REQ/RESP/DROP` - Memory word read protocol
- `WRITE_MEM_WORD_REQ/RESP/DROP/RETRY` - Memory word write protocol
- `READ_LINE/WRITE_LINE/WRITE_LINE_READ_LINE` - memory to/from cache
- `WRITE_LINE_READ_LINE_DROP` - flow control for memory operations
- `IDENT_QUERY_RESULT` - instruction identifier query response

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
1. Kamlet creates `WaitingLoadJ2JWords` (from `transactions/load_j2j_words.py`) with protocol states
2. `WaitingLoadJ2JWords.monitor_jamlet()` sends `LOAD_J2J_WORDS_REQ` when cache is ready
3. Destination jamlet receives via registered handler, shifts/masks data, writes to rf_slice
4. Destination sends `LOAD_J2J_WORDS_RESP` (or `DROP` if not ready)
5. When all protocol states complete, `finalize()` releases RF locks

### Store follows similar patterns but data flows rf_slice → SRAM

### Unaligned Word Load (LoadWord Path)
1. Lamlet detects partial element at cache line boundary, creates `LoadWord` instruction
2. Each kamlet (SRC with cache, DST with register) receives instruction
3. Creates `WaitingLoadWordSrc` or `WaitingLoadWordDst` (from `transactions/load_word.py`)
4. SRC waits for cache, then sends `LOAD_WORD_REQ` to DST
5. DST applies byte mask, merges with existing register data
6. DST sends `LOAD_WORD_RESP`, both sides mark COMPLETE
7. If DST not ready, sends `DROP`, SRC retries

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

# Monitoring System

The simulator uses a distributed tracing system based on spans (`monitor.py`). This replaces the
previous logging approach and provides structured performance analysis.

## Core Concepts

### Spans
Everything in the simulator is tracked as a span:
- `span_id`: Unique identifier
- `span_type`: Type of operation (RISCV_INSTR, KINSTR, KINSTR_EXEC, WITEM, MESSAGE, etc.)
- `created_cycle` / `completed_cycle`: Timing information
- `component`: Where it executes ("lamlet", "kamlet(x,y)", "jamlet(x,y)")
- `parent/children`: Spawning relationships
- `depends_on`: Blocking relationships (what this span waits on)
- `details`: Type-specific metadata

### Span Types
- `RISCV_INSTR` - A RISC-V instruction being executed
- `KINSTR` - A kamlet-level instruction (Load, Store, etc.)
- `KINSTR_EXEC` - A kinstr executing on a specific kamlet
- `WITEM` - A waiting item tracking async work
- `MESSAGE` - A message sent between components
- `CACHE_REQUEST` - A cache line request to memory
- `TRANSACTION` - Sub-transaction (e.g., WriteMemWord)
- `RESOURCE_EXHAUSTED` - Resource table full (witem slots, cache requests, etc.)

### Completion Types
- `TRACKED`: Creator knows when done (has real completed_cycle)
- `FIRE_AND_FORGET`: Creator dispatches but doesn't wait; completes when all children complete

### External Observability Principle
Span IDs are NOT passed through the system. Instead, the monitor maintains lookup tables mapping
observable properties to span IDs:
- `_kinstr_by_ident`: instr_ident → span_id
- `_kinstr_exec_by_key`: (instr_ident, kamlet_x, kamlet_y) → span_id
- `_witem_by_key`: (instr_ident, kamlet_x, kamlet_y, [source_x, source_y]) → span_id
- `_transaction_by_key`: (ident, tag, src_x, src_y, dst_x, dst_y) → span_id

This design enables future RTL simulation compatibility.

## Resource Types Tracked
- `WITEM_TABLE` - Waiting item slots in kamlet
- `CACHE_REQUEST_TABLE` - Cache request slots in kamlet
- `INSTR_IDENT` - Instruction identifier pool in lamlet
- `INSTR_BUFFER_TOKENS` - Instruction buffer tokens per kamlet

## Using the Monitor

### Creating Spans
```python
# KInstructions create their own spans via create_span()
span_id = kinstr.create_span(monitor, parent_span_id)

# For kinstr_exec (kinstr executing on specific kamlet)
span_id = monitor.record_kinstr_exec_created(instr, kamlet_x, kamlet_y)

# For waiting items
span_id = monitor.record_witem_created(
    instr_ident, kamlet_x, kamlet_y, 'WaitingLoadSimple',
    finalize=True  # Set False if more witems will be added
)

# For transactions (e.g., WriteMemWord)
span_id = monitor.create_transaction(
    'WriteMemWord', ident, src_x, src_y, dst_x, dst_y, parent_span_id=witem_span_id, tag=tag
)

# For messages
span_id = monitor.record_message_sent(
    transaction_span_id, 'WRITE_MEM_WORD_REQ',
    ident, tag, src_x, src_y, dst_x, dst_y
)
```

### Completing Spans
```python
# Complete a span directly
monitor.complete_span(span_id)

# Complete via lookup (for witems)
monitor.complete_witem(instr_ident, kamlet_x, kamlet_y)

# Finalize kinstr_exec (auto-completes when all children complete, or immediately if no children)
monitor.finalize_kinstr_exec(instr_ident, kamlet_x, kamlet_y)

# For FIRE_AND_FORGET spans, finalize children when done creating them
monitor.finalize_children(span_id)
```

### Recording Dependencies (for critical path analysis)
```python
# When a span discovers it's blocked on another span
monitor.add_dependency(blocked_span_id, blocking_span_id, "waiting_for_rf")
```

### Resource Exhaustion Tracking
```python
# When a resource becomes exhausted
monitor.record_resource_exhausted(ResourceType.WITEM_TABLE, kamlet_x, kamlet_y)

# When it becomes available again
monitor.record_resource_available(ResourceType.WITEM_TABLE, kamlet_x, kamlet_y)

# Link a witem to the resource blocking it
monitor.record_witem_blocked_by_resource(
    witem_instr_ident, kamlet_x, kamlet_y, ResourceType.WITEM_TABLE
)
```

### Analysis
```python
# Print comprehensive summary with latency stats
monitor.print_summary()

# Get statistics programmatically
stats = monitor.get_stats()

# Print hierarchical view of a span and descendants
monitor.print_span_tree(span_id)

# Export to JSON for external analysis
monitor.dump_to_file('trace.json')
```

## Instruction Identifier Flow Control

The `IdentQuery` mechanism prevents `instr_ident` wraparound collisions (idents wrap at 128):

1. Lamlet sends `IdentQuery` instruction when running low on idents
2. Each kamlet computes distance from baseline to its oldest active ident
3. Uses synchronization network with MIN aggregation to find global oldest
4. Kamlet (0,0) sends result back to lamlet
5. Lamlet can safely allocate idents ahead of the oldest active one

---

# Strided Memory Operations

## LoadStride / StoreStride

Handles strided loads/stores where elements are separated by a configurable stride in bytes
(not just sequential). Each element can come from a different page with different element widths.

**Key features**:
- `stride_bytes`: Byte stride between elements (None = unit stride = ew/8 bytes)
- Limited to `j_in_l` elements per instruction
- Uses synchronization network to coordinate completion across kamlets
- `reads_all_memory` / `writes_all_memory` flags prevent conflicts with other operations

**Note**: Unlike simple loads/stores which operate on contiguous cache lines, strided operations
may access arbitrary memory locations, requiring different coordination mechanisms.
