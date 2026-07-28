{ pkgs }:

let
  inherit (pkgs) lib stdenvNoCC;

  open-pdks-rev = "0fe9d247453b611112252260609f5063c6427914";
  asap7-rev = "d24f8b857ff74cf5b21ab18a7e1b11a3954c449b";
  asap7-pdk-rev = "58d72c9d291e186a77468586ab0c43d8a21eda6a";
  asap7-sc-rev = "f970bd3c3292b79ae4d022a3ec80533534614066";

  open-pdks = pkgs.fetchFromGitHub {
    owner = "benreynwar";
    repo = "open-pdks";
    rev = open-pdks-rev;
    hash = "sha256-++Xopm2F+8qajY0n2Mpc+E9krd3eBGIux6fesySOCaA=";
  };

  asap7 = pkgs.fetchFromGitHub {
    owner = "The-OpenROAD-Project";
    repo = "asap7";
    rev = asap7-rev;
    hash = "sha256-o1xcs9iolT0CuLNknhSlgQxaHuOKVy8dIj8meUMEyws=";
  };

  asap7-pdk = pkgs.fetchFromGitHub {
    owner = "The-OpenROAD-Project";
    repo = "asap7_pdk_r1p7";
    rev = asap7-pdk-rev;
    hash = "sha256-/U+NHOPT+qL1I2h2q4WudvLYNxQmCwxtJ9KANe9PPpw=";
  };

  asap7-sc = pkgs.fetchFromGitHub {
    owner = "The-OpenROAD-Project";
    repo = "asap7sc7p5t_28";
    rev = asap7-sc-rev;
    hash = "sha256-/R65ZrdiMq7puojumvfGtbMKGlw/ozLQEhOuSLvsOc8=";
  };

  # open-pdks expects the process and standard-cell repositories beneath the
  # top-level ASAP7 source checkout.
  asap7-sources = pkgs.linkFarm "asap7-sources" [
    {
      name = "LICENSE";
      path = "${asap7}/LICENSE";
    }
    {
      name = "asap7_pdk_r1p7";
      path = asap7-pdk;
    }
    {
      name = "asap7sc7p5t_28";
      path = asap7-sc;
    }
  ];
in

stdenvNoCC.mkDerivation {
  pname = "asap7-pdk";
  version = builtins.substring 0 7 open-pdks-rev;

  src = open-pdks;

  nativeBuildInputs = [
    pkgs.gnumake
    pkgs.magic-vlsi
    pkgs.p7zip
    pkgs.python3
  ];

  postPatch = ''
    substituteInPlace common/staging_install.py \
      --replace-fail "#!/usr/bin/env python3" "#!${pkgs.python3}/bin/python3"
  '';

  configurePhase = ''
    runHook preConfigure
    ./configure \
      --prefix=$out \
      --enable-asap7-pdk=${asap7-sources} \
      --with-asap7-link-targets=none \
      --disable-magic \
      --disable-netgen \
      --disable-irsim \
      --disable-qflow \
      --disable-xschem \
      --disable-xcircuit
    runHook postConfigure
  '';

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    make -C asap7 install \
      SHELL=${pkgs.bash}/bin/bash \
      SHARED_PDKS_PATH=$out \
      ASAP7_REVISION=${asap7-rev} \
      ASAP7_PDK_REVISION=${asap7-pdk-rev} \
      ASAP7_SC_REVISION=${asap7-sc-rev}
    runHook postInstall
  '';

  meta = with lib; {
    description = "ASAP7 predictive PDK and 7.5-track RVT standard-cell library";
    homepage = "https://github.com/The-OpenROAD-Project/asap7";
    license = licenses.bsd3;
    platforms = platforms.all;
  };
}
