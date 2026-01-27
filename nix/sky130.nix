# Sky130 PDK derivation using ciel
# Self-contained - imports its own pkgs
let
  # Import the same nixpkgs as default.nix
  librelane-flake = (import (fetchTarball
    "https://github.com/edolstra/flake-compat/archive/35bb57c0c8d8b62bbfd284272c928ceb64ddbde9.tar.gz"
  ) { src = builtins.fetchGit {
    url = "https://github.com/librelane/librelane";
    ref = "main";
  }; }).defaultNix;

  pkgs = librelane-flake.legacyPackages.${builtins.currentSystem};
  inherit (pkgs) lib stdenvNoCC cacert ciel;

  # PDK version - matches librelane's open_pdks_rev
  version = "0fe599b2afb6708d281543108caf8310912f54af";
in

stdenvNoCC.mkDerivation {
  pname = "sky130-pdk";
  inherit version;

  # Fixed-output derivation - allows network access, output verified by hash
  outputHashAlgo = "sha256";
  outputHashMode = "recursive";
  outputHash = "sha256-/CctqSCfaKbaHsi7y/PJ/FHis8wIB/EYex4qBs4OPnM=";

  nativeBuildInputs = [ ciel cacert ];

  # No source - ciel fetches it
  dontUnpack = true;

  buildPhase = ''
    export HOME=$TMPDIR
    export SSL_CERT_FILE=${cacert}/etc/ssl/certs/ca-bundle.crt

    # Enable PDK (fetches and creates symlinks librelane expects)
    ciel enable --pdk-root $out --pdk-family sky130 ${version}
  '';

  dontInstall = true;

  meta = with lib; {
    description = "SkyWater SKY130 PDK";
    homepage = "https://github.com/google/skywater-pdk";
    license = licenses.asl20;
    platforms = platforms.all;
  };
}
