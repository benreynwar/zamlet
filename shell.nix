# Development shell - uses common.nix for shared configuration
let
  common = import ./nix/common.nix;
  inherit (common) pkgs buildInputs env;
in
pkgs.mkShell {
  inherit buildInputs;

  PDK_ROOT = env.PDK_ROOT;
  PDK = env.PDK;
  LD_LIBRARY_PATH = env.LD_LIBRARY_PATH;
  LIBRARY_PATH = env.LIBRARY_PATH;

  shellHook = ''
    alias bazel=bazelisk
    export PYTHONPATH="$PWD/python:$PYTHONPATH"
    echo "Zamlet Development Environment"
    echo "  OpenROAD: $(openroad -version 2>/dev/null | head -1 || echo 'available')"
    echo "  Yosys:    $(yosys -V 2>/dev/null | head -1 || echo 'available')"
    echo "  Bazel:    $(bazel --version 2>/dev/null | head -1 || echo 'available')"
    echo "  PDK_ROOT: $PDK_ROOT"
    echo "  PDK:      $PDK"
    echo ""
  '';
}
