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

**Cache States**: INVALID, SHARED, MODIFIED, READING, WRITING, WRITING_READING, UNALLOCATED

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

### addresses.py
Address space management and translation chain:
```
GlobalAddress → VPUAddress → LogicalVLineAddress → PhysicalVLineAddress → KMAddr → JSAddr
```

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
