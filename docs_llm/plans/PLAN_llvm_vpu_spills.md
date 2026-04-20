# Plan: LLVM Toolchain for VPU Stack

## Goal

Switch kernel compilation from GCC to a custom LLVM/Clang so that vector stack objects
(spills and local vector variables) go to VPU memory instead of the scalar stack. This
removes the current constraint of having to hand-tune kernels to avoid vector spills.

## Background

The zamlet architecture has separate physical memories for scalar and vector data, mapped into
the same virtual address space via page tables. The scalar stack lives in scalar memory
(around 0x10000000). Vector data lives in VPU memory (0x20000000+ for static, 0x90000000+
for dynamic).

When GCC spills vector registers or allocates local vector variables, it puts them on
the regular scalar stack. This is wrong because the VPU needs to access that data via
VPU memory. There's no clean hook in GCC to redirect vector stack objects.

LLVM has `StackID::ScalableVector` which tags vector stack objects separately from scalar
ones. The RISC-V backend already uses this to group scalable objects into a separate stack
frame region. We can patch the backend to resolve those objects relative to a dedicated
VPU stack pointer instead of SP.

## Steps

### Phase 1: Build LLVM from source in Nix ✓

Done. LLVM is fetched and built in nix with clang+lld for RISC-V.

### Phase 2: Switch kernel builds to Clang ✓

Done. Kernel tests pass with Clang-compiled binaries.

### Phase 3: VPU stack patch

8. Fork LLVM (or just work on a branch of the fetched source). Update the nix fetch URL
   to point at the fork.

9. Patch `RISCVFrameLowering` to redirect `StackID::ScalableVector` slots.
   Controlled by a `cl::opt` flag (`-riscv-vpu-stack`, default off).
   See `docs/PLAN_llvm_vpu_spill_patch.md` for detailed tutorial.
   - This covers both vector register spills and local vector variables — both get
     `StackID::ScalableVector` frame objects in the RISC-V backend
   - Reserve `s11`/`x27` as the VPU stack pointer (compiler manages it like SP)
   - In `getFrameIndexReference()`: when frame object has `StackID::ScalableVector`,
     return s11 instead of SP/FP
   - In `emitPrologue()`/`emitEpilogue()`: retarget the scalable stack adjustment
     (including probing) to use s11 instead of SP
   - In `RISCVRegisterInfo`: mark s11 as reserved
   - Alignment: already correct since vline width equals vlenb

10. Update `crt.S` to initialize s11 to the top of the VPU stack region
    (0xA0100000). s11 grows downward, just like SP.

11. Update `run_oamlet.py` to allocate the VPU stack memory region.

12. Test with a kernel that previously required manual rewriting to avoid spills.

## Key files

- `nix/common.nix` — toolchain setup
- `python/zamlet/kernel_tests/*/build_*.sh` — kernel build scripts
- `python/zamlet/kernel_tests/common/crt.S` — startup code
- `python/zamlet/kernel_tests/common/test.ld` — linker script
- `bazel/defs.bzl` — `riscv_asm_binary` rule

## LLVM files to patch (Phase 3)

- `llvm/lib/Target/RISCV/RISCVFrameLowering.cpp`
- `llvm/lib/Target/RISCV/RISCVFrameLowering.h`
- `llvm/lib/Target/RISCV/RISCVRegisterInfo.cpp`
- `llvm/include/llvm/CodeGen/TargetFrameLowering.h` (TargetStackID enum, for reference)

## References

- LLVM `StackID` mechanism: `TargetStackID::ScalableVector` in `TargetFrameLowering.h`
- AArch64 SVE frame lowering (design template): `AArch64FrameLowering.cpp`
- AMDGPU scratch vs LDS (separate memory spill example): `AMDGPUFrameLowering.cpp`
- RISC-V vector calling convention: riscv-non-isa/riscv-elf-psabi-doc PR #389
- Hexagon HVX vector spills: `HexagonFrameLowering.cpp`
