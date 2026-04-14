# LLVM Compiler Issues

Issues and limitations with using the LLVM RISC-V backend for zamlet's
loosely-coupled vector architecture.

## Auto-vectorization of small loops

LLVM's auto-vectorizer assumes a tightly-coupled vector unit (cheap
scalar-vector transfers, shared pipeline). On zamlet, vector instructions
go over the network to the kamlet, and scalar-vector transfers (vmv.x.s,
vmv.s.x, reductions) are expensive.

The compiler will vectorize small loops (even 2-3 iterations) because the
cost model doesn't account for this. For example, a scalar `bitreverse()`
over `n_bits` positions gets vectorized with vid/vmerge/vredor even when
`n_bits` is small.

There is no runtime trip-count profitability check — LLVM only checks that
the trip count >= VF for correctness, not whether vectorization is worth the
overhead.

Possible approaches:
- Per-loop `#pragma clang loop vectorize(disable)` for scalar utility code
- Compile scalar-only files with `-fno-vectorize`
- Inflate TTI costs for scalar-vector transfers and reductions in the
  backend (RISCVTargetTransformInfo.cpp) so the vectorizer's cost model
  reflects the actual architecture
- Longer term: use MLIR with a zamlet-aware dialect for kernel compilation,
  keeping LLVM only for scalar code

## Unordered scatter

The LLVM backend unconditionally emits `vsoxei` (ordered scatter) for
`llvm.masked.scatter`. No pragma or metadata can switch to `vsuxei`
(unordered). We use `__riscv_vsuxei32` intrinsics directly as a workaround.

A proper fix would use loop-independence metadata to select unordered
scatter during lowering.
