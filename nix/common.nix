# Common Nix configuration for the Zamlet project.
# Exports buildDeps (project build dependencies) and devTools (developer tooling) separately
# so consumers can choose what they need.
let
  # nixos-24.05 branch, pinned 2025-02-05
  nixpkgs = fetchTarball "https://github.com/NixOS/nixpkgs/archive/b134951a4c9f3c995fd7be05f3243f8ecd65d798.tar.gz";
  bootstrap-pkgs = import nixpkgs {};
  cvc-pkgs = import nixpkgs {
    config.allowUnfreePredicate = pkg: (pkg.pname or "") == "open-src-cvc";
  };

  # nixpkgs-unstable, pinned 2026-03-16 (for newer metals with Bazel support)
  nixpkgs-unstable = fetchTarball
    "https://github.com/NixOS/nixpkgs/archive/a07d4ce6bee67d7c838a8a5796e75dff9caa21ef.tar.gz";
  unstable-pkgs = import nixpkgs-unstable {};

  flake-compat = fetchTarball
    "https://github.com/edolstra/flake-compat/archive/35bb57c0c8d8b62bbfd284272c928ceb64ddbde9.tar.gz";

  # 3.0.4 release, pinned 2026-06-07
  librelane-src-unpatched = builtins.fetchGit {
    url = "https://github.com/librelane/librelane";
    ref = "refs/tags/3.0.4";
    rev = "0f39aab99009d4a81ee3f863f0da9ca2f0b43a99";
  };

  librelane-src = bootstrap-pkgs.applyPatches {
    name = "librelane-patched";
    src = librelane-src-unpatched;
    patches = [
      ./patches/librelane-magic-abspath-rcfile.patch
    ];
  };

  # Local version (for development)
  # librelane-src = /home/ben/Code/librelane;

  librelane-flake = (import flake-compat { src = librelane-src; }).defaultNix;
  pkgs = librelane-flake.legacyPackages.${builtins.currentSystem};
  sky130-pdk = import ./sky130.nix { inherit pkgs; };

  # cocotb 2.0 override
  cocotb2 = pkgs.python3.pkgs.cocotb.overridePythonAttrs (old: rec {
    version = "2.0.0";
    src = pkgs.fetchFromGitHub {
      owner = "cocotb";
      repo = "cocotb";
      rev = "v${version}";
      sha256 = "sha256-BpshczKA83ZeytGDrHEg6IAbI5FxciAUnzwE10hgPC0=";
    };
    patches = [
      ./patches/cocotb-cvc-iterator-probes.patch
    ];
    # cocotb 2.0 uses src/ layout instead of cocotb/ at root
    preCheck = ''
      export PATH=$out/bin:$PATH
      if [ -d src/cocotb ]; then
        mv src/cocotb src/cocotb.hidden
      fi
    '';
  });

  # verilator 5.030+ needed for cocotb 2.0
  verilator-new = pkgs.verilator.overrideAttrs (old: rec {
    version = "5.030";
    src = pkgs.fetchFromGitHub {
      owner = "verilator";
      repo = "verilator";
      rev = "v${version}";
      sha256 = "sha256-3eWNCJBuSBYPLr1cUJgGHA+LPL+rpRNZYRtNoF0Cz+4=";
    };
  });

  # cocotb-bus for AXI testing (same commit as MODULE.bazel)
  cocotb-bus = pkgs.python3.pkgs.buildPythonPackage rec {
    pname = "cocotb-bus";
    version = "0-unstable";
    pyproject = true;

    src = pkgs.fetchFromGitHub {
      owner = "cocotb";
      repo = "cocotb-bus";
      rev = "b9b248ecc8793de6c4534e8014b99b92e1a1519a";
      sha256 = "sha256-eikhcBVnbqcYaTre99bEipcykHGZPKgLCXUjgjDn9RE=";
    };
    build-system = [ pkgs.python3.pkgs.setuptools ];
    propagatedBuildInputs = [ cocotb2 pkgs.python3.pkgs.scapy ];
    doCheck = false;
  };

  # cocotbext-axi for AXI RAM simulation (same commit as MODULE.bazel)
  cocotbext-axi = pkgs.python3.pkgs.buildPythonPackage rec {
    pname = "cocotbext-axi";
    version = "0-unstable";
    pyproject = true;

    src = pkgs.fetchFromGitHub {
      owner = "alexforencich";
      repo = "cocotbext-axi";
      rev = "3e1e7fc1ec488811d742adde6f7283852f134458";
      sha256 = "sha256-BITHHk1YXfYXH0kb7gh0A71WkKmz95VALBm3vmqMDFA=";
    };
    build-system = [ pkgs.python3.pkgs.setuptools ];
    propagatedBuildInputs = [ cocotb2 cocotb-bus ];
    doCheck = false;
  };

  pywellen = pkgs.python3.pkgs.buildPythonPackage rec {
    pname = "pywellen";
    version = "0.18.1";
    format = "wheel";

    src = pkgs.fetchurl {
      url = "https://files.pythonhosted.org/packages/5f/44/05241150719b39c77b398ffbe6cddc32fb9ed5f099029dd89f10845ba09f/pywellen-0.18.1-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl";
      hash = "sha256-FTLFv+BwA2w7+GXGQm045jRdDr/TYKVCTaC3+vKa7Pk=";
    };

    doCheck = false;
  };

  python-env = pkgs.python3.withPackages (ps: [
    ps.librelane
    ps.numpy
    ps.matplotlib
    ps.pytest
    ps.pytest-xdist
    ps.pyelftools
    ps.mkdocs
    ps.mkdocs-material
    cocotb2
    cocotb-bus
    cocotbext-axi
    pywellen
  ]);

  # RISC-V embedded toolchain (from regular nixpkgs, not librelane flake)
  riscv-toolchain = bootstrap-pkgs.pkgsCross.riscv64-embedded.buildPackages.gcc;

  # RISC-V Clang/LLD (for VPU vector spill support)
  riscv-clang = import ./riscv-clang.nix { pkgs = bootstrap-pkgs; };

  cvc = import ./cvc.nix { pkgs = cvc-pkgs; };

  # Project build dependencies
  buildDeps = with pkgs; [
    stdenv.cc.cc.lib  # Standard library for Bazel-downloaded binaries
    cmake             # For building LLVM locally
    ninja             # For building LLVM locally
    jdk21
    circt
    openroad
    opensta
    yosys
    magic-vlsi
    verilator-new
    cvc
    klayout
    python-env
    bazelisk
    ccache
    git
    jq
    which
    riscv-toolchain
    riscv-clang
  ];

  # Developer tooling (editor, LSP, etc.)
  devTools = [
    pkgs.cachix
    pkgs.ruff
    pkgs.mypy
    (pkgs.vim-full.customize {
      vimrcConfig.packages.zamlet = with pkgs.vimPlugins; {
        start = [ ale ];
      };
      vimrcConfig.customRC = ''
        source ~/.vimrc
      '';
    })
    unstable-pkgs.metals
    unstable-pkgs.coursier
    unstable-pkgs.surfer
  ];

  bazelPath = pkgs.lib.makeBinPath (buildDeps ++ devTools ++ (with pkgs; [
    stdenv.cc
    binutils
    bashInteractive
    coreutils
    findutils
    diffutils
    gnused
    gnugrep
    gawk
    gnutar
    gzip
    bzip2
    gnumake
    bash
    patch
    xz
    file
  ]));
in {
  inherit pkgs sky130-pdk python-env riscv-clang buildDeps devTools;

  # Environment variables
  env = {
    PDK_ROOT = sky130-pdk;
    PDK = "sky130A";
    LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
      pkgs.stdenv.cc.cc.lib
      unstable-pkgs.mesa
      unstable-pkgs.libGL
      unstable-pkgs.wayland
      unstable-pkgs.libxkbcommon
    ];
    # For linking against Python (needed by cocotb build)
    LIBRARY_PATH = "${pkgs.python3}/lib";
    GIT_SSL_CAINFO = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
  };

  # Project build setup
  buildHook = ''
    # Deduplicate PATH to prevent Bazel cache invalidation.
    # Each nix-shell entry can append duplicates, and --action_env=PATH
    # hashes the full value into action keys.
    dedupPATH() {
      local IFS=: result=() seen=()
      for dir in $PATH; do
        local found=0
        for s in "''${seen[@]}"; do
          if [ "$s" = "$dir" ]; then found=1; break; fi
        done
        if [ "$found" = 0 ]; then
          seen+=("$dir")
          result+=("$dir")
        fi
      done
      printf '%s\n' "$(IFS=:; echo "''${result[*]}")"
    }
    export PATH="$(dedupPATH)"
    export ZAMLET_CCACHE_DIR="$HOME/.cache/ccache-zamlet-bazel"
    export ZAMLET_CCACHE_WRAPPER_DIR="$PWD/.nix-shell-bin"
    mkdir -p "$ZAMLET_CCACHE_WRAPPER_DIR"
    cat > "$ZAMLET_CCACHE_WRAPPER_DIR/gcc" <<CCACHE_GCC
#!/usr/bin/env bash
exec "${pkgs.ccache}/bin/ccache" "${pkgs.stdenv.cc}/bin/gcc" "\$@"
CCACHE_GCC
    cat > "$ZAMLET_CCACHE_WRAPPER_DIR/g++" <<CCACHE_GXX
#!/usr/bin/env bash
exec "${pkgs.ccache}/bin/ccache" "${pkgs.stdenv.cc}/bin/g++" "\$@"
CCACHE_GXX
    cat > "$ZAMLET_CCACHE_WRAPPER_DIR/cc" <<CCACHE_CC
#!/usr/bin/env bash
exec "${pkgs.ccache}/bin/ccache" "${pkgs.stdenv.cc}/bin/cc" "\$@"
CCACHE_CC
    cat > "$ZAMLET_CCACHE_WRAPPER_DIR/c++" <<CCACHE_CXX
#!/usr/bin/env bash
exec "${pkgs.ccache}/bin/ccache" "${pkgs.stdenv.cc}/bin/c++" "\$@"
CCACHE_CXX
    chmod +x \
      "$ZAMLET_CCACHE_WRAPPER_DIR/gcc" \
      "$ZAMLET_CCACHE_WRAPPER_DIR/g++" \
      "$ZAMLET_CCACHE_WRAPPER_DIR/cc" \
      "$ZAMLET_CCACHE_WRAPPER_DIR/c++"

    export ZAMLET_BAZEL_PATH="$ZAMLET_CCACHE_WRAPPER_DIR:${bazelPath}"

    export PYTHONPATH="$PWD/python:$PYTHONPATH"
    export CCACHE_DIR="$ZAMLET_CCACHE_DIR"
    export CCACHE_BASEDIR="$PWD"
    export CCACHE_NOHASHDIR=1

    # Ensure sandbox writable paths exist (Bazel requires them to)
    mkdir -p "$HOME/.cache/coursier" "$HOME/.cache/llvm-firtool" "$ZAMLET_CCACHE_DIR"

    # Generate user-specific bazel sandbox paths
    cat > "$PWD/.bazelrc.user" <<BAZELRC
# Auto-generated by shell.nix from nix/common.nix. Do not edit.
# Pin Bazel action PATH to a deterministic Nix-derived PATH. This keeps
# editor/agent launcher PATH prefixes from changing action keys.
build --action_env=PATH=$ZAMLET_BAZEL_PATH
build --host_action_env=PATH=$ZAMLET_BAZEL_PATH
build --repo_env=PATH=$ZAMLET_BAZEL_PATH
build --action_env=CCACHE_DIR=$ZAMLET_CCACHE_DIR
build --host_action_env=CCACHE_DIR=$ZAMLET_CCACHE_DIR
build --repo_env=CCACHE_DIR=$ZAMLET_CCACHE_DIR
build --action_env=CCACHE_BASEDIR=$PWD
build --host_action_env=CCACHE_BASEDIR=$PWD
build --repo_env=CCACHE_BASEDIR=$PWD
build --action_env=CCACHE_NOHASHDIR=1
build --host_action_env=CCACHE_NOHASHDIR=1
build --repo_env=CCACHE_NOHASHDIR=1
# Allow Chisel's coursier to download firtool from within Bazel sandbox
build --sandbox_writable_path=$HOME/.cache/coursier
build --sandbox_writable_path=$HOME/.cache/llvm-firtool
build --sandbox_writable_path=$ZAMLET_CCACHE_DIR
BAZELRC
  '';

  # Developer tooling setup (BSP server, bazel wrapper for IDE)
  devHook = ''
    # Wrapper script so bazel-bsp uses a separate output_base, preventing it
    # from invalidating the terminal bazel's analysis cache.
    rm -f "$PWD/.nix-shell-bin/bazel"
    cat > "$PWD/.nix-shell-bin/bazel" <<WRAPPER
#!/usr/bin/env bash
# Redirect BSP calls to a separate output_base so they don't invalidate
# the terminal bazel's analysis cache.
for arg in "\$@"; do
  if [[ "\$arg" == *"bazelbsp"* ]]; then
    exec "$(which bazelisk)" --output_base="$PWD/.bazel-bsp-output-base" "\$@"
  fi
done
exec "$(which bazelisk)" "\$@"
WRAPPER
    chmod +x "$PWD/.nix-shell-bin/bazel"
    export PATH="$PWD/.nix-shell-bin:$PATH"

    # Install Bazel BSP server for Metals (vim/ALE can't handle the interactive
    # import prompt, so we install it automatically).
    if [ ! -f .bsp/bazelbsp.json ]; then
      echo "Installing Bazel BSP server for Metals..."
      cs launch org.virtuslab:bazel-bsp:4.0.3 \
        -M org.jetbrains.bsp.bazel.install.Install \
        && echo "  Bazel BSP installed." \
        || echo "  Bazel BSP install failed (non-critical)."
    fi
  '';
}
