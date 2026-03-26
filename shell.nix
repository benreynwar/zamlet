# Development shell - includes both project build deps and developer tooling
let
  common = import ./nix/common.nix;
  inherit (common) pkgs buildDeps devTools env buildHook devHook;
in
pkgs.mkShell {
  buildInputs = buildDeps ++ devTools ++ [ pkgs.glibcLocales ];

  PDK_ROOT = env.PDK_ROOT;
  PDK = env.PDK;
  LD_LIBRARY_PATH = env.LD_LIBRARY_PATH;
  LIBRARY_PATH = env.LIBRARY_PATH;
  GIT_SSL_CAINFO = env.GIT_SSL_CAINFO;
  LOCALE_ARCHIVE = "${pkgs.glibcLocales}/lib/locale/locale-archive";

  shellHook = buildHook + devHook + ''
    echo "Zamlet Development Environment"
    echo "  OpenROAD: $(openroad -version 2>/dev/null | head -1 || echo 'available')"
    echo "  Yosys:    $(yosys -V 2>/dev/null | head -1 || echo 'available')"
    echo "  Bazel:    $(bazel --version 2>/dev/null | head -1 || echo 'available')"
    echo "  PDK_ROOT: $PDK_ROOT"
    echo "  PDK:      $PDK"
    echo ""
  '';
}
