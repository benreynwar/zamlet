# Sky130 PDK derivation using ciel
# Takes pkgs from common.nix to avoid duplicating librelane fetch
{ pkgs }:

let
  inherit (pkgs) lib stdenvNoCC cacert;
  ciel = pkgs.python3.pkgs.ciel;

  # PDK version - matches librelane's open_pdks_rev
  version = "8afc8346a57fe1ab7934ba5a6056ea8b43078e71";
in

stdenvNoCC.mkDerivation {
  pname = "sky130-pdk";
  inherit version;

  # Fixed-output derivation - allows network access, output verified by hash
  outputHashAlgo = "sha256";
  outputHashMode = "recursive";
  outputHash = "sha256-4/knv2g/YSg9bLZLn5xswtrOJ0rxEcY8dWGvlfdOl0M=";

  nativeBuildInputs = [ ciel cacert ];

  # No source - ciel fetches it
  dontUnpack = true;

  buildPhase = ''
    export HOME=$TMPDIR
    export SSL_CERT_FILE=${cacert}/etc/ssl/certs/ca-bundle.crt

    # Enable PDK (fetches and creates symlinks librelane expects)
    ciel enable --pdk sky130 --pdk-root $out ${version}
  '';

  dontInstall = true;

  meta = with lib; {
    description = "SkyWater SKY130 PDK";
    homepage = "https://github.com/google/skywater-pdk";
    license = licenses.asl20;
    platforms = platforms.all;
  };
}
