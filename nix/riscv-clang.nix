{ pkgs }:

let
  llvm-src = builtins.fetchGit {
    url = "https://github.com/benreynwar/llvm-project";
    ref = "zamlet";
    rev = "27de313b6f6f9ecf7237062bebba9f11ef5d768c";
  };
in
pkgs.stdenv.mkDerivation {
  name = "riscv-clang";
  src = llvm-src;
  sourceRoot = "source/llvm";
  nativeBuildInputs = with pkgs; [ cmake ninja python3 ];
  cmakeFlags = [
    "-DLLVM_ENABLE_PROJECTS=clang;lld"
    "-DLLVM_TARGETS_TO_BUILD=RISCV"
    "-DCMAKE_BUILD_TYPE=Release"
    "-DLLVM_OPTIMIZED_TABLEGEN=ON"
  ];
}

# Pre-built locally (for faster iteration during development):
# /home/ben/Projects/llvm-project/install
