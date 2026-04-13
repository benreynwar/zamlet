{ pkgs }:

let
  # Build from upstream (reproducible, slow first build).
  llvm-src = builtins.fetchGit {
    url = "https://github.com/benreynwar/llvm-project";
    ref = "zamlet";
    rev = "27de313b6f6f9ecf7237062bebba9f11ef5d768c";
  };

  riscv-clang-github = pkgs.stdenv.mkDerivation {
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
  };

  # Pre-built locally (faster iteration during development).
  # Build with: cmake --install build --prefix /home/ben/Projects/llvm-project/install
  riscv-clang-local = pkgs.runCommand "riscv-clang-local" { } ''
    mkdir -p $out
    ln -s /home/ben/Projects/llvm-project/install/bin $out/bin
    ln -s /home/ben/Projects/llvm-project/install/lib $out/lib
    ln -s /home/ben/Projects/llvm-project/install/include $out/include
  '';
in
# Switch this line to toggle between the upstream-built and locally-built clang.
#riscv-clang-local
 riscv-clang-github
