# Backend and test shell without the custom RISC-V LLVM build or editor tools.
let
  common = import ./nix/common.nix { includeRiscvClang = false; };
  inherit (common) pkgs buildDeps env buildHook;
in
pkgs.mkShell {
  buildInputs = buildDeps ++ [ pkgs.glibcLocales ];

  PDK_ROOT = env.PDK_ROOT;
  PDK = env.PDK;
  LD_LIBRARY_PATH = env.LD_LIBRARY_PATH;
  LIBRARY_PATH = env.LIBRARY_PATH;
  GIT_SSL_CAINFO = env.GIT_SSL_CAINFO;
  LOCALE_ARCHIVE = "${pkgs.glibcLocales}/lib/locale/locale-archive";

  shellHook = buildHook + ''
    echo "Zamlet Backend Environment"
    echo "  OpenROAD: $(openroad -version 2>/dev/null | head -1 || echo 'available')"
    echo "  Yosys:    $(yosys -V 2>/dev/null | head -1 || echo 'available')"
    echo "  Bazel:    $(bazel --version 2>/dev/null | head -1 || echo 'available')"
    echo "  PDK_ROOT: $PDK_ROOT"
    echo "  PDK:      $PDK"
    echo ""
  '';
}
