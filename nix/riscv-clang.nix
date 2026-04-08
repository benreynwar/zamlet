{ pkgs }:

let
  llvm-src = builtins.fetchGit {
    url = "https://github.com/benreynwar/llvm-project";
    ref = "main";
    rev = "e5a7a9a95ffda04e4ce2398d1950662873b8cd65";
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
