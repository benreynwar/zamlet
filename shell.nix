# Use librelane's flake via flake-compat
let
  nixpkgs = fetchTarball "https://github.com/NixOS/nixpkgs/archive/nixos-24.05.tar.gz";
  bootstrap-pkgs = import nixpkgs {};

  flake-compat = fetchTarball
    "https://github.com/edolstra/flake-compat/archive/35bb57c0c8d8b62bbfd284272c928ceb64ddbde9.tar.gz";

  # GitHub version with patch for BasicMacroPlacement
  librelane-src-unpatched = builtins.fetchGit {
    url = "https://github.com/librelane/librelane";
    ref = "main";
  };

  # Apply patch to fix BasicMacroPlacement.get_script_path()
  librelane-src = bootstrap-pkgs.applyPatches {
    name = "librelane-patched";
    src = librelane-src-unpatched;
    patches = [ ./nix/librelane-macro-placement.patch ];
  };

  # Local version (for development)
  # librelane-src = /home/ben/Code/librelane;

  librelane-flake = (import flake-compat { src = librelane-src; }).defaultNix;

  pkgs = librelane-flake.legacyPackages.${builtins.currentSystem};
  sky130-pdk = import ./nix/sky130.nix;
in
pkgs.mkShell {
  buildInputs = with pkgs; [
    # Standard library for Bazel-downloaded binaries
    stdenv.cc.cc.lib
    # Chisel/Scala
    jdk21
    circt
    scala-cli

    # EDA tools (from librelane's overlay)
    openroad
    opensta
    yosys
    magic-vlsi
    verilator
    klayout

    # Python with librelane (must use python3 from flake, not python313)
    (python3.withPackages (ps: [ ps.librelane ]))

    # Build tools
    bazelisk
    git
  ];

  PDK_ROOT = sky130-pdk;
  PDK = "sky130A";

  # For Bazel-downloaded binaries that need libstdc++
  LD_LIBRARY_PATH = "${pkgs.stdenv.cc.cc.lib}/lib";

  shellHook = ''
    echo "Zamlet Development Environment"
    echo "  OpenROAD: $(openroad -version 2>/dev/null | head -1 || echo 'available')"
    echo "  Yosys:    $(yosys -V 2>/dev/null | head -1 || echo 'available')"
    echo "  Bazel:    $(bazel --version 2>/dev/null | head -1 || echo 'available')"
    echo "  PDK_ROOT: $PDK_ROOT"
    echo "  PDK:      $PDK"
    echo ""
  '';
}
