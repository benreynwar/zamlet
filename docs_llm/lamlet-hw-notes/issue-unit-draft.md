# IssueUnit (First Draft)

Decodes RISC-V vector instructions, performs TLB lookup, generates kinstrs.

**First draft scope:** Only unit-stride vle/vse, no pipeline, no BLOCKING stage.

## Interfaces

```
IssueUnit
├── IN:  io.ex.valid, io.ex.uop, io.ex.vconfig, io.ex.vstart
├── IN:  io.mem.tlb_resp
├── IN:  ident_available (from IdentTracker - can allocate ident)
├── IN:  allocated_ident (from IdentTracker)
├── IN:  dispatch_ready (from DispatchQueue - can accept kinstr)
│
├── OUT: io.ex.ready
├── OUT: io.mem.tlb_req
├── OUT: io.com.retire_late, io.com.inst, io.com.xcpt, ...
├── OUT: kinstr (to DispatchQueue)
├── OUT: kinstr_valid
├── OUT: alloc_ident_req (request ident from IdentTracker)
├── OUT: k_index (which kamlet, or None for broadcast)
```

## Backpressure

- **Ident availability**: IssueUnit checks `ident_available` before proceeding
- **Dispatch backpressure**: DispatchQueue signals `dispatch_ready`, IssueUnit waits if not ready
- **Tokens**: Checked by DispatchQueue (not IssueUnit's concern)

## State Machine

```
IDLE: Wait for io.ex.valid && ident_available
      On valid: capture inst, go to TLB_REQ

TLB_REQ: Issue TLB request
         Go to TLB_WAIT

TLB_WAIT: Check tlb_resp
          If miss: internal_replay, go to IDLE
          If fault: xcpt, go to IDLE
          If ok: go to DISPATCH

DISPATCH: Assert kinstr_valid, alloc_ident_req
          Wait for dispatch_ready
          On dispatch accepted: retire_late, go to IDLE
```

## Decode Logic (unit-stride only)

```
opcode = inst[6:0]
is_load  = (opcode == 0000111)  // LOAD-FP
is_store = (opcode == 0100111)  // STORE-FP
mop = inst[27:26]  // 00 = unit-stride
vm = inst[25]      // 1 = unmasked
vd = inst[11:7]    // destination/source register
width = inst[14:12] // element width encoding
```

## Kinstr Generation

For unit-stride load `vle8.v v1, (a0)` with vl=8:
- dst = 1
- k_maddr = physical address from TLB
- start_index = vstart
- n_elements = vl - vstart
- dst_ordering = (word_order from TLB metadata, eew from instruction)
- mask_reg = None (vm=1)
- instr_ident = allocated from IdentTracker

## Answered Questions

1. **TLB timing**: Combinational. If `tlb_req.ready` is false, treat as miss (triggers replay).
   From Saturn: `mem_tlb_resp.miss := io.core.mem.tlb_resp.miss || !io.core.mem.tlb_req.ready`

2. **vsetvli handling**: Shuttle handles internally. We receive updated `vconfig` via
   `io.core.ex.vconfig`. No special handling needed.

3. **Kinstr encoding**: Use `J2JInstr` format from `jamlet/KInstr.scala` (64-bit packed).
   Python Load fields map to:
   - opcode: Load opcode
   - cacheSlot: derived from k_maddr
   - memWordOrder, memEw: from k_maddr.ordering
   - rfWordOrder, rfEw: from dst_ordering
   - baseBitAddr: from k_maddr
   - startIndex: start_index
   - nElementsIdx: index into param memory (n_elements stored separately)
   - reg: dst register

   Plus `instr_ident` (7 bits) needs to be in packet - either in header or instruction word.
