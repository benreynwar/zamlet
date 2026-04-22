# Plan: LLVM VPU Stack Patch (Phase 3)

This is a plan and tutorial for patching LLVM's RISC-V backend so that vector
stack objects (spills and local vector variables) use a dedicated VPU stack
pointer (s11) instead of the regular scalar stack pointer (sp).

## Background: How LLVM manages the stack

When LLVM compiles a function, it needs to figure out where everything lives in
memory: local variables, spilled registers, function arguments. This happens
across several compilation passes, and the RISC-V backend has specific code
to handle it.

### Frame objects and StackID

Every stack allocation in LLVM is represented as a **frame object** in
`MachineFrameInfo` (MFI). Each frame object has:
- A **size** (in bytes)
- An **alignment** requirement
- An **offset** from the stack/frame pointer (assigned later)
- A **StackID** that categorizes what kind of object it is

The StackID enum (`TargetStackID` in `TargetFrameLowering.h`) has:
```cpp
enum Value {
  Default = 0,           // Regular scalar objects
  SGPRSpill = 1,         // AMDGPU-specific
  ScalableVector = 2,    // RVV vector objects (this is what we care about)
  WasmLocal = 3,
  ScalablePredicateVector = 4,
  NoAlloc = 255
};
```

When the register allocator decides it needs to spill an RVV register, it
creates a frame object and the backend marks it with
`StackID::ScalableVector`. The same StackID is used for local vector
variables. This is our hook — any frame object with this StackID should
go on the VPU stack, not the scalar stack.

### The normal RISC-V stack layout

Without our patch, the RISC-V stack frame looks like this (stack grows down):

```
High addresses
|--------------------------| <-- FP (if used)
| varargs save area        |
|--------------------------|
| callee-saved registers   |  (scalar GPRs, FPRs)
|--------------------------|
| scalar local variables   |  StackID::Default objects
|--------------------------|
| RVV padding              |  (alignment)
|--------------------------|
| RVV objects              |  StackID::ScalableVector objects
|  (spills + locals)       |  (sizes are multiples of vlenb)
|--------------------------|
| VarSize objects          |  (alloca)
|--------------------------| <-- SP
Low addresses
```

The RVV objects live at the bottom of the frame, just above SP. Their sizes
are "scalable" — they're expressed as multiples of `vlenb` (vector register
length in bytes), which is only known at runtime. The prologue emits code
like:
```asm
csrr  a0, vlenb       # read vlenb (runtime value)
slli  a0, a0, 2       # multiply by number of vregs to spill
sub   sp, sp, a0      # grow the stack
```

### What we want instead

We want RVV objects to live on a completely separate stack, managed by s11:

```
Scalar stack (sp):             VPU stack (s11):
|--------------------------|   |--------------------------|
| varargs save area        |   |                          | <-- s11 initial (set by crt.S)
|--------------------------|   |                          |
| callee-saved registers   |   | (free space)             |
|--------------------------|   |                          |
| scalar local variables   |   |--------------------------|
|--------------------------| <-- SP                       | <-- s11 after prologue
                               | RVV objects              |
                               |  (spills + locals)       |
                               |--------------------------|
```

The scalar stack has no RVV section at all. The prologue adjusts s11
(not sp) to allocate space for RVV objects, and the epilogue restores it.

## The pipeline: where each piece runs

Understanding when each function runs helps make sense of the patch:

1. **Register allocation** — decides which virtual registers need spilling.
   Calls `assignCalleeSavedSpillSlots()` which creates frame objects for
   callee-saved RVV registers and marks them `StackID::ScalableVector`.

2. **`processFunctionBeforeFrameFinalized()`** — runs after register
   allocation but before frame layout is finalized. Calls
   `assignRVVStackObjectOffsets()` to lay out all ScalableVector frame
   objects (compute their offsets relative to each other). Also sets
   `RVVStackSize` and `RVVStackAlign`.

3. **`emitPrologue()` / `emitEpilogue()`** — emit the actual
   assembly for the function entry/exit. Allocate stack space, save/restore
   callee-saved registers, set up the frame pointer. Currently, the prologue
   emits `sub sp, sp, <RVV size>` for the scalable portion.

4. **`eliminateFrameIndex()`** (in `RISCVRegisterInfo.cpp`) — runs during
   Prologue/Epilogue Insertion (PEI). Every instruction that references a
   frame object (via a frame index operand) gets rewritten to use an actual
   register + offset. It calls `getFrameIndexReference()` to get the
   base register and offset for each frame index.

5. **`getFrameIndexReference()`** — the key translation function. Given a
   frame index, returns which register to use as a base (SP, FP, or BP)
   and what offset to add. Currently returns SP or FP for ScalableVector
   objects.

## The patch: step by step

### Step 0: Add the `cl::opt` flag

**File**: `llvm/lib/Target/RISCV/RISCVFrameLowering.cpp` (top of file,
near other `cl::opt` declarations)

Add a command-line option to enable the VPU stack behavior:
```cpp
static cl::opt<bool> UseVPUStack(
    "riscv-vpu-stack",
    cl::desc("Use separate stack pointer (s11) for scalable vector objects"),
    cl::init(false));
```

This defaults to off. Enable it from clang with:
```bash
clang --target=riscv64 -march=rv64gcv -mllvm -riscv-vpu-stack ...
```

Every subsequent step should be guarded with `if (UseVPUStack)` so the
patch is a no-op when the flag is off. The flag also needs to be visible
in `RISCVRegisterInfo.cpp` for Step 1 — either declare it `extern` there,
or add a helper method to `RISCVFrameLowering` that exposes it.

### Step 1: Reserve s11 in `RISCVRegisterInfo.cpp`

**File**: `llvm/lib/Target/RISCV/RISCVRegisterInfo.cpp`, `getReservedRegs()`
(line 123)

We need to tell the register allocator that s11 (X27) is not available for
general use. Currently sp, gp, tp, and conditionally fp and bp are reserved.

Add:
```cpp
// Reserve s11 as the VPU stack pointer for ScalableVector frame objects.
if (UseVPUStack && MF.getSubtarget<RISCVSubtarget>().hasVInstructions())
  markSuperRegs(Reserved, RISCV::X27_H);  // s11
```

We condition on both `UseVPUStack` (the flag from Step 0) and
`hasVInstructions()`. The latter is needed because s11 is only relevant
when the target has vector instructions. This matches `hasRVVFrameObject()`
which also uses `hasVInstructions()` (see the FIXME comment at line 1841
of RISCVFrameLowering.cpp — it's imprecise but necessary for consistency
with register allocation).

**Why X27_H?** The `_H` suffix refers to the "half" sub-register. The
`markSuperRegs` function marks the register and all its super-registers as
reserved, so `X27_H` covers both the 32-bit and 64-bit views of the
register. This is the same pattern used for sp (`X2_H`), gp (`X3_H`), etc.

### Step 2: Redirect `getFrameIndexReference()` for ScalableVector

**File**: `llvm/lib/Target/RISCV/RISCVFrameLowering.cpp`,
`getFrameIndexReference()` (line 1436)

This is the core change. Currently, when a frame object has
`StackID::ScalableVector`, the offset is computed relative to SP or FP with
complex adjustments for the scalar stack portion. We want to return s11
as the base register with a simple scalable offset.

The current code (line 1460-1462):
```cpp
} else if (StackID == TargetStackID::ScalableVector) {
  Offset = StackOffset::getScalable(MFI.getObjectOffset(FI));
}
```

This sets `Offset` to the object's offset within the RVV stack section (a
negative scalable value, since the stack grows down). Then further code
below adds the distance from SP/FP to the RVV section base.

With our patch, when `UseVPUStack` is enabled, for ScalableVector objects
we can short-circuit: set `FrameReg = RISCV::X27` and return the scalable
offset directly. The offset
from `assignRVVStackObjectOffsets()` is already relative to the top of the
RVV section, which is exactly where s11 points before the prologue adjusts
it. After the prologue adjusts s11, the objects are at positive offsets
from the new s11 value — but the offset convention is: s11 points to the
base (high end) of the RVV area, and objects have negative offsets from
there. This matches how `assignRVVStackObjectOffsets` already assigns them.

Wait — let's look at the offset convention more carefully.
`assignRVVStackObjectOffsets()` does:
```cpp
Offset = alignTo(Offset + ObjectSize, ObjectAlign);  // Offset grows positive
MFI.setObjectOffset(FI, -Offset);                    // Stored as negative
```

So object offsets are negative, meaning "below the base". If we make s11
point to the top of the VPU stack area (before allocation), then after
the prologue does `sub s11, s11, <total RVV size>`, s11 points to the
bottom. We need the objects to be accessible at *positive* offsets from
the adjusted s11 value.

The cleanest approach: keep the offset calculation as-is, but add
`RVVStackSize` to shift the reference point from the top to the bottom
of the RVV section. This matches what the existing SP-relative path does
(line 1604):
```cpp
Offset += StackOffset::get(ScalarLocalVarSize, RVFI->getRVVStackSize());
```

The scalable component `RVFI->getRVVStackSize()` shifts from the bottom
of the RVV area (where SP points) to the top. For s11, after the prologue
adjusts it, s11 points to the bottom too, so we need the same shift:

```cpp
if (UseVPUStack && StackID == TargetStackID::ScalableVector) {
  FrameReg = RISCV::X27;  // s11
  Offset = StackOffset::getScalable(
      MFI.getObjectOffset(FI) + RVFI->getRVVStackSize());
  return Offset;
}
```

This early-returns, bypassing all the SP/FP/BP logic that doesn't apply.
When `UseVPUStack` is false, falls through to the existing code.

### Step 3: Retarget the prologue RVV adjustment

**File**: `llvm/lib/Target/RISCV/RISCVFrameLowering.cpp`, `emitPrologue()`
(line 1155)

Currently the prologue allocates RVV space by subtracting from SP:
```cpp
if (RVVStackSize) {
  if (NeedProbe) {
    allocateAndProbeStackForRVV(MF, MBB, MBBI, DL, RVVStackSize, ...);
  } else {
    RI->adjustReg(MBB, MBBI, DL, SPReg, SPReg,
                  StackOffset::getScalable(-RVVStackSize),
                  MachineInstr::FrameSetup, getStackAlign());
  }
  // ... DWARF CFI ...
}
```

When `UseVPUStack` is enabled, both paths (probe and non-probe) should
adjust s11 instead of SP. Use `Register RVVReg = UseVPUStack ? RISCV::X27
: SPReg` and substitute throughout:

For the non-probe path:
```cpp
Register RVVReg = UseVPUStack ? RISCV::X27 : SPReg;
RI->adjustReg(MBB, MBBI, DL, RVVReg, RVVReg,
              StackOffset::getScalable(-RVVStackSize),
              MachineInstr::FrameSetup, getStackAlign());
```

For the probe path, `allocateAndProbeStackForRVV()` (line 657) currently
hardcodes `SPReg` in the `SUB` instruction (line 689) and the residual
probe store (line 697). Update it to read `UseVPUStack` internally and
use s11 when enabled. The probing loop itself (`PROBED_STACKALLOC_RVV`
pseudo, line 680) will also need attention — it gets expanded later in
`inlineStackProbe` and likely touches SP there too.

`adjustReg` with a scalable offset emits:
```asm
csrr  t0, vlenb
slli  t0, t0, N       # multiply by number of vregs
sub   s11, s11, t0    # grow VPU stack
```

The DWARF CFI directives (lines 1168-1173) may need updating too, but
for our use case (bare metal, no unwinding) we can defer this. Add a
TODO comment.

### Step 4: Retarget the epilogue RVV adjustment

**File**: `llvm/lib/Target/RISCV/RISCVFrameLowering.cpp`, `emitEpilogue()`
(line 1300)

Mirror of the prologue change. Currently:
```cpp
if (RVVStackSize) {
  if (!RestoreSPFromFP)
    RI->adjustReg(MBB, FirstScalarCSRRestoreInsn, DL, SPReg, SPReg,
                  StackOffset::getScalable(RVVStackSize),
                  MachineInstr::FrameDestroy, getStackAlign());
}
```

When `UseVPUStack` is enabled, adjust s11 instead. Same approach as the
prologue — use `Register RVVReg = UseVPUStack ? RISCV::X27 : SPReg`.

Note: the existing code skips the SP restore when `RestoreSPFromFP` is
true (SP gets restored from FP later). That condition is about SP, not
s11 — we always need to restore s11 in the epilogue regardless.

### Step 5: Enforce vline-width alignment

**File**: `llvm/lib/Target/RISCV/RISCVFrameLowering.cpp`,
`assignRVVStackObjectOffsets()` (line 1725)

Each VPU stack slot must be aligned to the vline width (VLEN/8 bytes =
vlenb), because the VPU memory model tracks element width per vline.
A misaligned slot would span two vlines with potentially different ew tags.

Currently, alignment defaults to `RISCV::RVVBytesPerBlock` (line 1764):
```cpp
auto ObjectAlign =
    std::max(Align(RISCV::RVVBytesPerBlock), MFI.getObjectAlign(FI));
```

`RVVBytesPerBlock` is 8 (the minimum vscale * 64 bits). For a machine
where VLEN=256, vlenb=32, we need 32-byte alignment. The minimum
alignment should be `vlenb`, but vlenb is a runtime value.

Since scalable offsets are in units of `RVVBytesPerBlock` (8 bytes), and
vlenb = vscale * 8, each "scalable unit" is already exactly vlenb bytes
at runtime. So any object whose scalable offset is a whole number is
automatically vline-aligned. The existing code already rounds up object
sizes to at least `RVVBytesPerBlock` (line 1767-1768):
```cpp
if (ObjectSize < RISCV::RVVBytesPerBlock)
  ObjectSize = RISCV::RVVBytesPerBlock;
```

This means every RVV frame object is already at least one vscale unit in
size and aligned to one vscale unit. **If our vline width equals vlenb
(one vector register width), then alignment is already correct and no
change is needed here.** Verify this matches the zamlet VPU architecture.

If vline width differs from vlenb, we'd need to adjust the minimum
alignment.

### Step 6: Model-side changes (zamlet)

**File**: `python/zamlet/kernel_tests/common/crt.S`

Initialize s11 to the top of the VPU stack region in the startup code:
```asm
li s11, 0xA0100000    # VPU stack pointer (grows downward)
```

**File**: `python/zamlet/oamlet/run_oamlet.py`

Allocate the VPU stack memory region (1MB at 0xA0000000) in the test
harness. Placed at an isolated address so overflow hits unmapped memory.

### Step 7: Test

Write a kernel that uses enough vector registers to force spills, and
verify it compiles and runs correctly. Compare the generated assembly
before and after the patch to confirm spills use s11 instead of sp.

Useful test approach:
```bash
# Compile to assembly to inspect spill code
clang --target=riscv64 -march=rv64gcv -S -O2 test_kernel.c -o test_kernel.s
# Look for s11 references in the spill code
grep s11 test_kernel.s
```

## Files to modify

LLVM (in `/home/ben/Projects/llvm-project`):
- `llvm/lib/Target/RISCV/RISCVRegisterInfo.cpp` — reserve s11
- `llvm/lib/Target/RISCV/RISCVFrameLowering.cpp` — getFrameIndexReference,
  emitPrologue, emitEpilogue

zamlet (in `/home/ben/Projects/zamlet2`):
- `python/zamlet/kernel_tests/common/crt.S` — init s11
- `python/zamlet/oamlet/run_oamlet.py` — allocate VPU stack memory

## Resolved questions

- **Vline width vs vlenb**: Confirmed equal. Alignment is already handled.
- **Callee-saved RVV registers**: Save/restore uses `storeRegToStackSlot`
  and `loadRegFromStackSlot` with frame indices, resolved via
  `eliminateFrameIndex` → `getFrameIndexReference`. Our Step 2 change
  routes them to s11 automatically. No hardcoded SP references.

## Deferred work

These items are about the scalar stack being computed as if it still
contains an RVV section when `UseVPUStack` is on. The scalar stack ends
up slightly larger than necessary, but the generated code is correct.

- **Scalar stack size** — `getStackSizeWithRVVPadding()` and
  `getRVVPadding()` compute padding between the scalar and RVV sections.
  With UseVPUStack, there's no RVV section on the scalar stack, so this
  padding wastes scalar stack space.
- **`hasReservedCallFrame()`** (line 1963) — returns false when
  `hasFP(MF) && hasRVVFrameObject(MF)`, triggering call frame pseudo
  instructions. With UseVPUStack the RVV objects aren't on the scalar
  stack, so this condition is overly conservative.
- **`getFirstSPAdjustAmount()`** — splits the SP adjustment for large
  frames. Its calculation includes RVV-related sizes that don't apply
  when RVV is on a separate stack.
- **DWARF CFI for s11** — the current CFI describes RVV objects relative
  to SP, which is wrong when they're on the VPU stack. Not needed for
  bare-metal testing, but would matter for debugger backtraces or C++
  exception unwinding through vector frames.
