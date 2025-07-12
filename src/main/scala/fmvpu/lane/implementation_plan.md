# FMVPU Lane Implementation Plan

Single-issue pipeline with Tomasulo approach, packet-based networking, minimal buffering.

## Implementation Status

### Phase 1: Foundation ✅
- [x] **RFF** - Register file with dependency tracking - **34,363 µm²** (4,409 inst)
- [x] **InstructionMemory** - 64-deep instruction storage - **39,776 µm²** (1,794 inst)  
- [x] **ALU** - Add/Sub/Mult/MultAcc operations - **22,014 µm²** (2,587 inst)

### Phase 2: Reservation Stations ✅
- [x] **ALU RS** (`alu_rs.txt`) - Out-of-order execution, dependency resolution - **29,608 µm²** (3,426 inst)
- [x] **Load/Store RS** (`ldst_rs.txt`) - Memory ops, base+offset calc - **15,363 µm²** (1,764 inst)
- [x] **Packet RS** (`packet_rs.txt`) - Network packet ops, channel assignment - **3,907 µm²** (414 inst)

### Phase 3: Execution Units
- [x] **Data Memory** - Local memory interface, load/store execution - **77,727 µm²** (3,321 inst)
- [x] **Packet Interface** (`packet_interface.txt`) - Network send/receive/forward - **11,012 µm²** (1,194 inst) - **BUGGY: Missing forwarding logic**

### Phase 4: Network Infrastructure  
- [x] **Packet Input Handler** (`packet_in_handler.txt`) - Reception, routing, arbitration - **1,815 µm²** (252 inst)
- [x] **Packet Output Handler** (`packet_out_handler.txt`) - Transmission, channel management - **1,745 µm²** (168 inst)
- [x] **Packet Switch** - Multi-channel routing and switching - **31,381 µm²** (4,060 inst) - *Note: Area could be reduced by ~20% by eliminating self-connections (4 inputs per output instead of 5)*
- [x] **LaneNetworkNode** - Connection state, priority arbitration - **48,409 µm²** (5,615 inst)

### Phase 5: Integration ✅
- [x] **NewLane** - Top-level wiring, I/O interfaces - **282,411 µm²** (24,710 inst)
- [ ] **Testing** - Unit and integration tests
- [ ] **Area Analysis** - Compare vs old NetworkNode

## Architecture
- **Registers**: 8 total (0=packet out, 1=accum, 2=mask, 3=base, 4=channel, 5-7=general)
- **Network**: 4-direction (N/S/E/W), multi-channel, packet forwarding
- **Pipeline**: Single-issue, write identifier renaming, minimal buffering

## Module Implementation Checklist (for Claude Code)

### 1. Implement
- [ ] Read corresponding .txt specification file
- [ ] Create `ModuleName.scala` in `src/main/scala/fmvpu/lane/`
- [ ] Add ModuleNameGenerator and case to `Main.scala`
- [ ] Update `LaneParams.scala` and `lane_default.json` if needed

### 2. Test
- [ ] Create `test_modulename_basic.py` in `python/fmvpu/new_lane/`
- [ ] Add BUILD rules for test
- [ ] Run: `bazel test //python/fmvpu/new_lane:test_modulename_basic`

### 3. Area Analysis
- [ ] Add to `NEW_LANE_STUDIES` in `dse/new_lane/BUILD`
- [ ] Run: `bazel build //dse/new_lane:ModuleName_default__sky130hd_results`
- [ ] Update plan with area (µm²) and instance count

## Implementation Lessons Learned

### Interface Design Consistency
- **Always use Valid() or Decoupled() wrappers** instead of embedding `valid` fields in Bundle classes

### Testing Signal Access
- In cocotb tests, always use `.value` attribute: `dut.signal.value = 0`
- For dynamic signal access: `getattr(dut, f'signal_{i}').value = 0`
