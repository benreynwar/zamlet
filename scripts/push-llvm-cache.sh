#!/usr/bin/env bash
# Build riscv-clang from nix and push to cachix so CI doesn't have to build it.
#
# Run this from inside nix-shell after updating nix/riscv-clang.nix to point
# at a new LLVM commit.
set -euo pipefail

if [ -z "${IN_NIX_SHELL:-}" ]; then
    echo "Error: run this from inside nix-shell" >&2
    exit 1
fi

echo "Building riscv-clang..."
STORE_PATH=$(nix-build --no-out-link -E '(import ./nix/common.nix).riscv-clang')
echo "Built: $STORE_PATH"

echo "Pushing to cachix..."
cachix push benreynwar "$STORE_PATH"
echo "Done."
