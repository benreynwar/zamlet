# Saturn Analysis: Implications for Zamlet Design

## Saturn's Precise Fault Mechanism

### Why Precise Faults Must Be Checked Ahead of Commit

RVV mandates precise faults for vector memory operations:
- Faulting loads/stores must execute up until the element that causes the fault
- Must report the precise element index that generated the fault
- Must block commit of any younger scalar or vector instructions

If you only check faults at commit time, you'd interlock scalar and vector pipelines waiting
for vtype/vl to commit before checking faults. This severely degrades performance.

### Saturn's Solution: PFC + IFC

Saturn uses a two-tier fault checking system in the Vector Frontend (VFU):

**Pipelined Fault Checker (PFC)** - handles common cases at 1 IPC:
- Stage VF0: Categorize instruction (non-memory, single-page, page-crossing, iterative)
- Stage VF1: Check accessed page via TLB
- Stage VF2: Handle TLB response - miss causes replay, fault forwards to IFC

Single-page instructions flow through without stalls. Page-crossing instructions get cracked
into single-page operations via scalar replay (updating vstart, replaying at same PC).

**Iterative Fault Checker (IFC)** - handles complex cases element-by-element:
- Indexed, masked, strided accesses that might touch many pages
- Generates unique address for each element, checks TLB per element
- Fetches index/mask values from VRF for indexed/masked operations
- Dispatches elements to backend only if no fault found
- Upon fault, precise element index is known

### Key Insight: Post-Commit Execution

Saturn executes ALL vector instructions post-commit in VU and VLSU:
- VU and VLSU only receive committed, fault-checked instructions
- Physical addresses passed from VFU to VLSU
- VLSU will never fault on memory accesses
- This greatly simplifies backend microarchitecture - all ops are non-speculative

## Implications for Zamlet Design

### Architectural Differences

| Aspect | Saturn | Zamlet |
|--------|--------|--------|
| Backend structure | Single VU + VLSU | Mesh of kamlets, jamlets, memlets |
| Execution model | Sequencers iterate elements | Region-level fission, kamlets iterate |
| Memory access | VLSU with address sequencers | Memlets with dedicated DRAM interface |
| Register file | Centralized VRF | Distributed across kamlets |

### Fault Checking in Lamlet

We should adopt Saturn's core principle: **check faults ahead of commit, dispatch only
fault-free operations to the backend**.

**Proposed lamlet frontend fault checking:**

1. **Fast Path (PFC-equivalent):**
   - Unit-stride single-page accesses: check 1 TLB entry, proceed
   - Use region bounds + vl to determine if access is single-page
   - Crack page-crossing accesses into single-page ops (similar vstart/replay mechanism)

2. **Slow Path (IFC-equivalent):**
   - Indexed, masked, strided accesses
   - Must iterate element-by-element
   - Need to fetch index values from kamlet VRFs

3. **TLB Architecture:**
   - Lamlet: authoritative TLB + page table walker
   - Kamlet: TLB caches for fast hits during execution
   - Fault checking uses lamlet TLB (before dispatch)

### Challenge: Index/Mask Fetch for IFC

Saturn's IFC can access the VRF through the VU because it's a single unit. For us:
- Indices might be in different kamlets (distributed VRF)
- Need mechanism for lamlet to fetch index values from specific kamlet

Options:
1. **Centralized index buffer in lamlet:** Copy index registers to lamlet before fault check
2. **Request-response from kamlets:** Lamlet requests index elements, kamlet responds
3. **Two-phase execution:** Pre-execute index generation in kamlets, then fault-check in lamlet

Option 2 seems cleanest - matches our existing IdentQuery flow control pattern.

### vtype/vl Handling

Saturn emphasizes: vtype and vl must be available at fault-check time, not just at commit.
- Scalar core should bypass/forward vtype/vl updates to early pipeline stages
- Our lamlet decoder needs current vtype/vl to determine fault check category

### Post-Commit Dispatch to Mesh

Following Saturn's pattern:
- Lamlet frontend performs all fault checking
- Only dispatch fault-free kinstrs to kamlets/jamlets/memlets
- Physical addresses (not virtual) passed to mesh components
- Memlets never fault - they receive pre-validated physical addresses

This simplifies kamlet/jamlet/memlet design significantly - no need to handle faults or
speculation in the distributed mesh.

### Page-Crossing Strategy

Saturn's approach: crack page-crossing accesses via replay mechanism:
- Compute elements in first page
- Set vstart, request replay at same PC
- Repeated until all pages checked

For zamlet:
- Similar approach in lamlet frontend
- Dispatch separate kinstrs for each page's elements
- Each kinstr is single-page, fault-checked

### Memory Disambiguation

Saturn also handles scalar-vector memory disambiguation in VFU:
- Younger scalar loads/stores replayed if conflict with pending vector ops
- Vector ops stall until scalar store buffer empty

For zamlet:
- Need similar disambiguation in lamlet
- Track pending vector ops in lamlet instruction queues
- Check scalar accesses against pending vector address ranges

## Scalability Concerns with Saturn's Approach

Saturn's centralized IFC doesn't scale well to many-lane designs like zamlet:
- Gathering indices from distributed kamlet VRFs to lamlet: network latency
- Sequential TLB checking in lamlet: O(elements) time
- Dispatching back to kamlets: more latency
- Total overhead ≈ just executing the indexed op directly

Long-vector machines (Ara, Hwacha, NEC Aurora) use **distributed fault checking** with per-lane
TLBs and memory ports instead.

## Zamlet Fault Checking Strategy

### Key Insight: Idempotent Memory

For idempotent memory (regular DRAM), RVV allows stores past the faulting element. Software
can restart from `vstart` and redo them. This means:
- Execute speculatively across all kamlets/memlets
- If any element faults, report precise element index
- Some stores past fault point may have happened - that's fine
- No rollback needed

Only non-idempotent memory (MMIO, device registers) requires strict ordering.

### Fault Checking by Access Type

| Type | Strategy | Blocking Behavior |
|------|----------|-------------------|
| Unit-stride | Check 1-2 pages upfront | Unblock after page check (fast) |
| Strided | Execute + parallel page check | Unblock when page check completes |
| Strided bounded | Execute + parallel region check | Unblock when region check completes |
| Indexed bounded | Execute + parallel region check | Unblock when region check completes |
| Indexed unbounded | Execute speculatively | Unblock immediately (idempotent) or on completion (non-idempotent) |

### Bounded Memory Operations

New instruction variants that bound indices/addresses to a region, enabling fast frontend
fault checking in parallel with execution.

**Indexed Bounded**: `vluxei_bounded`, `vsuxei_bounded`
- Instruction specifies `base`, `indices`, and `range`
- Hardware computes: `base + (index % range) * element_size`
- Frontend checks: is region `[base, base + range * element_size)` valid?
- Check is O(pages in range), not O(elements)

**Strided Bounded**: `vlse_bounded`, `vsse_bounded`
- Instruction specifies `base`, `stride`, and `range`
- Hardware computes: `base + (i * stride) % range`
- Frontend checks: is region `[base, base + range)` valid?
- Useful for circular buffers with strided access

Benefits:
1. **Fast fault check**: Verify bounded region, not per-element
2. **Semantically useful**: Circular buffers, hash tables, modular indexing, ring buffers
3. **Bounds safety**: Hardware enforces indices stay in range (prevents buffer overflows)
4. **Performance**: Frontend check races with execution, unblocks early in common case

Encoding options:
- New instruction variants with range in scalar register
- Reuse segment field (nf) for log2(range) for power-of-2 ranges
- CSR that sets active range for subsequent indexed/strided ops

### Distributed Fault Checking Flow

For unbounded indexed operations:
1. Lamlet dispatches indexed kinstr to kamlets/memlets
2. Each kamlet generates addresses locally, checks local TLB cache
3. On TLB miss: request translation from lamlet
4. On fault: report element index back to lamlet
5. Lamlet sets `vstart`, signals fault to scalar core
6. For idempotent memory: no rollback needed, some elements past fault may have executed

For bounded operations:
1. Lamlet dispatches bounded kinstr to kamlets/memlets AND starts region check
2. Kamlets execute, applying modulo to indices/addresses
3. Region check completes (usually fast): unblock younger instructions
4. If region check fails: kamlets may have executed some elements (idempotent OK)

## Summary: Zamlet Frontend Requirements

Based on Saturn analysis and scalability considerations, lamlet frontend needs:

1. **Fast path for unit-stride**: Check 1-2 pages, dispatch immediately
2. **Parallel page checker for strided**: Compute touched pages, check in parallel with execution
3. **Region checker for bounded ops**: Verify bounded region valid, check in parallel
4. **Distributed TLB**: Lamlet authoritative + kamlet caches for translation during execution
5. **vtype/vl bypass** from scalar core decode stage
6. **Page-crossing cracking** into single-page operations (unit-stride)
7. **Scalar-vector disambiguation** with scalar store buffer
8. **Fault aggregation**: Collect fault reports from kamlets, determine precise element index

This is a different tradeoff than Saturn:
- Saturn: Centralized fault checking, simple backend, doesn't scale to many lanes
- Zamlet: Distributed fault checking, parallel execution, scales to many kamlets
