# Common Nix configuration shared between shell.nix and docker.nix
let
  # nixos-24.05 branch, pinned 2025-02-05
  nixpkgs = fetchTarball "https://github.com/NixOS/nixpkgs/archive/b134951a4c9f3c995fd7be05f3243f8ecd65d798.tar.gz";
  bootstrap-pkgs = import nixpkgs {};

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

  # Packages needed for development/builds
  buildInputs = with pkgs; [
    # Standard library for Bazel-downloaded binaries
    stdenv.cc.cc.lib

    # Chisel/Scala
    jdk21
    circt
    scala-cli

    # EDA tools
    openroad
    opensta
    yosys
    magic-vlsi
    verilator-new
    klayout

    # Python with librelane
    python-env

    # Build tools
    bazelisk
    git

    # RISC-V toolchain for shuttle tests
    riscv-toolchain
  ];

  # Environment variables
  env = {
    PDK_ROOT = sky130-pdk;
    PDK = "sky130A";
    LD_LIBRARY_PATH = "${pkgs.stdenv.cc.cc.lib}/lib";
    # For linking against Python (needed by cocotb build)
    LIBRARY_PATH = "${pkgs.python3}/lib";
  };
}
