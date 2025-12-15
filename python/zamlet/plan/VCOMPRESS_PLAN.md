# vcompress.vm Implementation Plan

## Overview

Implement the RISC-V vector compress instruction `vcompress.vm vd, vs2, vs1` which packs elements from `vs2` where the corresponding mask bit in `vs1` is 1, placing them contiguously at the start of `vd`.

## Algorithm

Two phases:
1. **Prefix sum**: Compute destination position for each element (popcount of mask bits before it)
2. **Data movement**: Move each enabled element to its computed destination

### Prefix Sum Algorithm (log2(n) rounds)

The lamlet allocates a physical vector register to serve as the accumulator. This register is specified in the kinstrs and each jamlet operates on its portion. For viota.m, this is the destination register directly; for vcompress, it's an internal register.

```
Round k (k = 0, 1, 2, ...):
  - Sender: jamlet i where (i % 2^(k+1)) == 2^k - 1
  - Receivers: next 2^k jamlets (i+1 through i+2^k)
  - Action: receivers add sender's value to their portion of the accumulator register
```

After all rounds, each jamlet's portion of the accumulator = inclusive prefix sum (sum of mask bits from element 0 through its last element).

For exclusive prefix (needed for destination position), shift by one or adjust computation.

## Implementation Components

### 1. Internal Accumulator Registers

The prefix sum uses two internal physical registers (not mapped to v0-v31) for ping-ponging. The lamlet allocates these before the operation and frees them after.

```python
reg_a = lamlet.alloc_internal_reg()  # e.g., returns 32
reg_b = lamlet.alloc_internal_reg()  # e.g., returns 33
```

This reuses existing RF infrastructure - data is naturally distributed across jamlets, locking works normally.

### 2. New KInstr: `PrefixSumRound`

**File**: `python/zamlet/kinstructions.py`

```python
@dataclass
class PrefixSumRound(KInstr):
    round_k: int           # Which round (0, 1, 2, ...)
    src_reg: int           # Read from here (can be mask register for round 0)
    dst_reg: int           # Write updated accumulator here
    src_ew: int            # Element width for source (1 for mask bits)
    dst_ew: int            # Element width for destination
```

**Kamlet behavior**:
1. **Sync barrier**: All jamlets synchronize (using existing sync network) before sending
2. **Sender**: read from src_reg at src_ew, broadcast value to next 2^k jamlets
3. **Receiver**: read from src_reg at src_ew, add received value, write to dst_reg at dst_ew
4. **Non-participants**: copy src_reg to dst_reg (with ew conversion if needed)
5. Use existing `SendType.BROADCAST` in router

**Sync-before-send**: The barrier ensures all receivers are ready, so broadcasts are never dropped. No DROP/RETRY protocol needed - simpler than other J2J transactions.

**Key insight**: No separate init instruction needed. Round 0 reads directly from the mask register with `src_ew=1` (mask bits are 1-bit). Subsequent rounds ping-pong between internal registers.

**Ping-pong approach**: Avoids read-after-write hazards within a round. Element width can grow as values accumulate (start at 1-bit mask, widen to 8/16-bit as sums grow).

### 3. New KInstr: `RegReformat`

**File**: `python/zamlet/kinstructions.py`

Changes the formatting element width of a vector register. The logical data is unchanged, but the physical distribution across jamlets changes.

```python
@dataclass
class RegReformat(KInstr):
    src_reg: int           # Source register
    dst_reg: int           # Destination register
    src_ew: int            # Current formatting ew of src_reg
    dst_ew: int            # Desired formatting ew for dst_reg
```

**Why needed**: Each register has a formatting ew that determines how data is physically distributed across jamlets. If a register was written at ew=8 but the current SEW is 32, the register needs reformatting before operations that expect ew=32 layout.

**Kamlet behavior**:
- Determine which bytes need to move between jamlets
- Use J2J-style messaging to redistribute data
- Sync barrier before/after to ensure consistency

**Usage in vcompress**: If vs2 (source data) was written at a different ew than current SEW, reformat it first.

### 4. New KInstr: `RegScatter`

**File**: `python/zamlet/kinstructions.py`

A general register-to-register scatter primitive. Each source element is written to a destination position specified by an index register.

```python
@dataclass
class RegScatter(KInstr):
    src_reg: int           # Source register
    dst_reg: int           # Destination register
    index_reg: int         # Where each element goes (dst[index[i]] = src[i])
    mask_reg: int | None   # Optional mask (only scatter where mask=1)
    data_ew: int           # Element width for src and dst
    index_ew: int          # Element width for indices
```

For vcompress, `data_ew = index_ew = ew` (prefix sum elements match data).
For future vrgatherei16, `data_ew = SEW`, `index_ew = 16`.

**Kamlet behavior**:
- For each element i (where mask[i]=1 if masked):
  - Read `src[i]` from src_reg
  - Read `index[i]` from index_reg to get destination position
  - Send element to destination jamlet (may be different jamlet)
  - Write to `dst[index[i]]`

This is the inverse of vrgather:
- **vrgather** = RF-to-RF gather: `dst[i] = src[index[i]]` (read from index positions)
- **RegScatter** = RF-to-RF scatter: `dst[index[i]] = src[i]` (write to index positions)

For vcompress, the index_reg is the prefix sum result, so each enabled element scatters to its computed destination.

### 5. New Transaction: `WaitingPrefixSumRound`

**File**: `python/zamlet/transactions/prefix_sum.py`

Handles the prefix sum round messaging:
- Sender side: broadcast accumulator value
- Receiver side: receive and accumulate
- Completion tracking per round

### 6. New Transaction: `WaitingRegScatter`

**File**: `python/zamlet/transactions/reg_scatter.py`

Handles RF-to-RF scatter data movement:
- Read source element and index from local rf_slice
- Route to destination jamlet (determined by index value)
- Write to destination register at indexed position
- Similar structure to `WaitingLoadJ2JWords` but RF-to-RF

### 7. Lamlet Orchestration

**File**: `python/zamlet/lamlet/lamlet.py`

```python
def vcompress(self, vd: int, vs2: int, vs1: int, ew: int):
    reg_a = self.alloc_internal_reg()
    reg_b = self.alloc_internal_reg()

    # Reformat vs2 if its formatting ew doesn't match current SEW
    src_data = vs2
    if self.get_reg_format_ew(vs2) != ew:
        src_data = self.alloc_internal_reg()
        instr = RegReformat(src_reg=vs2, dst_reg=src_data,
                            src_ew=self.get_reg_format_ew(vs2), dst_ew=ew)
        self.dispatch_to_all_kamlets(instr)
        self.wait_for_completion(instr)

    # Prefix sum rounds (ping-pong, round 0 reads from mask register)
    n_rounds = (self.params.j_in_l - 1).bit_length()  # log2 ceiling
    src, dst = vs1, reg_a  # Round 0 reads mask bits directly
    current_ew = 1         # Mask bits are 1-bit

    for round_k in range(n_rounds):
        next_ew = 8  # Widen to hold sums (or compute dynamically)
        instr = PrefixSumRound(round_k=round_k, src_reg=src, dst_reg=dst,
                               src_ew=current_ew, dst_ew=next_ew)
        self.dispatch_to_all_kamlets(instr)
        self.wait_for_completion(instr)
        # Swap for next round (alternate between reg_a and reg_b)
        src = dst
        dst = reg_b if src == reg_a else reg_a
        current_ew = next_ew

    prefix_reg = src  # Final result is in last written register

    # Data movement via scatter (index_reg = prefix sum result)
    instr = RegScatter(src_reg=src_data, dst_reg=vd, index_reg=prefix_reg,
                       mask_reg=vs1, data_ew=ew, index_ew=current_ew)
    self.dispatch_to_all_kamlets(instr)
    self.wait_for_completion(instr)

    self.free_internal_reg(reg_a)
    self.free_internal_reg(reg_b)
    if src_data != vs2:
        self.free_internal_reg(src_data)
```

### 8. Decoder Addition

**File**: `python/zamlet/instructions/vector.py`

```python
class Vcompress(VectorInstr):
    """vcompress.vm vd, vs2, vs1"""
    vd: int
    vs2: int
    vs1: int  # mask register
```

**File**: `python/zamlet/decode.py`

Add decoder entry for vcompress.vm opcode.

### 9. Message Types

**File**: `python/zamlet/message.py`

```python
PREFIX_SUM_BROADCAST = auto()    # Carries accumulator value
REG_SCATTER_REQ = auto()         # Element data to destination
REG_SCATTER_RESP = auto()        # Acknowledgment
REG_SCATTER_DROP = auto()        # Flow control
```

## Key Files to Modify

| File | Changes |
|------|---------|
| `kinstructions.py` | Add `PrefixSumRound`, `RegReformat`, `RegScatter` |
| `message.py` | Add new message types |
| `transactions/prefix_sum.py` | New file for prefix sum logic |
| `transactions/reg_reformat.py` | New file for ew reformatting |
| `transactions/reg_scatter.py` | New file for RF-to-RF scatter |
| `transactions/__init__.py` | Register new handlers |
| `kamlet/kamlet.py` | Handle new kinstrs |
| `lamlet/lamlet.py` | Add `viota()`, `vcompress()` orchestration, internal reg allocation |
| `instructions/vector.py` | Add `Viota`, `Vcompress` instruction classes |
| `decode.py` | Add decoder for viota.m, vcompress.vm |

## Grid Topology Consideration

Jamlets are in a 2D grid but the prefix sum algorithm assumes linear ordering. Use existing `word_order` / `vw_index` mapping:

```python
# Convert grid (x, y) to linear index for prefix algorithm
linear_idx = addresses.j_coords_to_vw_index(params, word_order, x, y)
```

The broadcast routing needs to handle 2D coordinates - sender at linear index i broadcasts to linear indices i+1 through i+2^k, each converted back to (x, y) for routing.

## Testing

1. **Unit test**: Prefix sum algorithm correctness (various mask patterns)
2. **Unit test**: Compress move data correctness
3. **Integration test**: Full vcompress with RISC-V binary
4. **Edge cases**:
   - All mask bits 0 (no output)
   - All mask bits 1 (identity copy)
   - Single element enabled
   - Mask patterns that cluster output

## Future Reuse

Once implemented, the prefix sum infrastructure enables:
- `viota.m` - literally just the prefix sum result written to a register
- `vcpop.m` - final value of prefix sum (total popcount)
- Other prefix-based algorithms

The `RegScatter` primitive enables:
- `vcompress` - scatter using prefix sum indices
- Future RF-to-RF scatter operations

A corresponding `RegGather` (inverse of RegScatter) would enable:
- `vrgather` - gather from arbitrary register positions

## Implementation Order

1. Internal register allocation in lamlet
2. Message types and basic structures
3. `PrefixSumRound` kinstr + transaction with broadcast
4. Lamlet prefix orchestration (test prefix sum correctness)
5. **`viota.m` implementation** - prefix sum directly to vd (first complete instruction!)
6. `RegReformat` kinstr + transaction (ew reformatting)
7. `RegScatter` kinstr + transaction (general RF-to-RF scatter)
8. Full `vcompress` orchestration (prefix sum + optional reformat + RegScatter)
9. Decoder integration for both instructions
10. End-to-end testing

### viota.m Early Implementation

`viota.m vd, vs2` writes `popcount(vs2[0:i-1])` to each element `vd[i]`.

This is exactly the prefix sum result. For viota.m, the output must be at SEW per the RISC-V spec, so the final round widens to SEW. We can use vd as one of the ping-pong registers:

```python
def viota(self, vd: int, vs2: int, ew: int):
    reg_tmp = self.alloc_internal_reg()

    # Prefix sum rounds (round 0 reads mask bits, final round writes to vd at SEW)
    n_rounds = (self.params.j_in_l - 1).bit_length()
    src, dst = vs2, reg_tmp  # Round 0 reads mask bits
    current_ew = 1

    for round_k in range(n_rounds):
        is_last = (round_k == n_rounds - 1)
        next_ew = ew if is_last else 8  # Widen to SEW on last round
        # On last round, write to vd instead of reg_tmp
        actual_dst = vd if is_last else dst
        instr = PrefixSumRound(round_k=round_k, src_reg=src, dst_reg=actual_dst,
                               src_ew=current_ew, dst_ew=next_ew)
        self.dispatch_to_all_kamlets(instr)
        self.wait_for_completion(instr)
        src = actual_dst
        dst = reg_tmp if src == vd else vd  # Alternate
        current_ew = next_ew

    self.free_internal_reg(reg_tmp)
```

This gives us a complete, testable instruction after step 4.
