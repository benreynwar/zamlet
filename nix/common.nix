# Common Nix configuration for the Zamlet project.
# Exports buildDeps (project build dependencies) and devTools (developer tooling) separately
# so consumers can choose what they need.
let
  # nixos-24.05 branch, pinned 2025-02-05
  nixpkgs = fetchTarball "https://github.com/NixOS/nixpkgs/archive/b134951a4c9f3c995fd7be05f3243f8ecd65d798.tar.gz";
  bootstrap-pkgs = import nixpkgs {};

  # nixpkgs-unstable, pinned 2026-03-16 (for newer metals with Bazel support)
  nixpkgs-unstable = fetchTarball
    "https://github.com/NixOS/nixpkgs/archive/a07d4ce6bee67d7c838a8a5796e75dff9caa21ef.tar.gz";
  unstable-pkgs = import nixpkgs-unstable {};

  flake-compat = fetchTarball
    "https://github.com/edolstra/flake-compat/archive/35bb57c0c8d8b62bbfd284272c928ceb64ddbde9.tar.gz";

  # main branch, pinned 2025-02-05
  librelane-src-unpatched = builtins.fetchGit {
    url = "https://github.com/librelane/librelane";
    ref = "main";
    rev = "f315752cf2e1465aca24a002247aa6169becb541";
  };

  librelane-src = bootstrap-pkgs.applyPatches {
    name = "librelane-patched";
    src = librelane-src-unpatched;
    patches = [
      ./librelane-macro-placement.patch
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
    patches = [];
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
    src = pkgs.fetchFromGitHub {
      owner = "cocotb";
      repo = "cocotb-bus";
      rev = "b9b248ecc8793de6c4534e8014b99b92e1a1519a";
      sha256 = "sha256-eikhcBVnbqcYaTre99bEipcykHGZPKgLCXUjgjDn9RE=";
    };
    propagatedBuildInputs = [ cocotb2 ];
    doCheck = false;
  };

  # cocotbext-axi for AXI RAM simulation (same commit as MODULE.bazel)
  cocotbext-axi = pkgs.python3.pkgs.buildPythonPackage rec {
    pname = "cocotbext-axi";
    version = "0-unstable";
    src = pkgs.fetchFromGitHub {
      owner = "alexforencich";
      repo = "cocotbext-axi";
      rev = "3e1e7fc1ec488811d742adde6f7283852f134458";
      sha256 = "sha256-BITHHk1YXfYXH0kb7gh0A71WkKmz95VALBm3vmqMDFA=";
    };
    propagatedBuildInputs = [ cocotb2 cocotb-bus ];
    doCheck = false;
  };

  python-env = pkgs.python3.withPackages (ps: [
    ps.librelane
    ps.numpy
    ps.matplotlib
    ps.pytest
    ps.pytest-xdist
    ps.pyelftools
    cocotb2
    cocotb-bus
    cocotbext-axi
  ]);

  # RISC-V embedded toolchain (from regular nixpkgs, not librelane flake)
  riscv-toolchain = bootstrap-pkgs.pkgsCross.riscv64-embedded.buildPackages.gcc;
in {
  inherit pkgs sky130-pdk python-env;

  # Project build dependencies
  buildDeps = with pkgs; [
    stdenv.cc.cc.lib  # Standard library for Bazel-downloaded binaries
    jdk21
    circt
    openroad
    opensta
    yosys
    magic-vlsi
    verilator-new
    klayout
    python-env
    bazelisk
    git
    jq
    which
    riscv-toolchain
  ];

  # Developer tooling (editor, LSP, etc.)
  devTools = [
    ((pkgs.vim_configurable.override { guiSupport = "no"; }).customize {
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

  # Environment variables
  env = {
    PDK_ROOT = sky130-pdk;
    PDK = "sky130A";
    LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
      pkgs.stdenv.cc.cc.lib
      unstable-pkgs.mesa.drivers
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

    export PYTHONPATH="$PWD/python:$PYTHONPATH"

    # Ensure sandbox writable paths exist (Bazel requires them to)
    mkdir -p "$HOME/.cache/coursier" "$HOME/.cache/llvm-firtool"

    # Generate user-specific bazel sandbox paths
    cat > "$PWD/.bazelrc.user" <<BAZELRC
# Auto-generated by nix-shell. Do not edit.
# Allow Chisel's coursier to download firtool from within Bazel sandbox
build --sandbox_writable_path=$HOME/.cache/coursier
build --sandbox_writable_path=$HOME/.cache/llvm-firtool
BAZELRC
  '';

  # Developer tooling setup (BSP server, bazel wrapper for IDE)
  devHook = ''
    # Wrapper script so bazel-bsp uses a separate output_base, preventing it
    # from invalidating the terminal bazel's analysis cache.
    mkdir -p "$PWD/.nix-shell-bin"
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
