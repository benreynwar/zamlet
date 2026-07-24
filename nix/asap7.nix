{ pkgs }:

let
  inherit (pkgs) lib stdenvNoCC;

  orfs = builtins.fetchGit {
    url = "https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts";
    rev = "aaf99bfae2bd77848e9778e902d0f4b4c8e1f11c";
  };

  liberty-parser = pkgs.python3.pkgs.buildPythonPackage rec {
    pname = "liberty-parser";
    version = "0.0.29";
    pyproject = true;

    src = pkgs.fetchPypi {
      pname = "liberty_parser";
      inherit version;
      hash = "sha256-/oQTIsP/dmovdimzCnX2W2abBFw5i8WZ/jbC5WzQ0vs=";
    };

    build-system = [ pkgs.python3.pkgs.setuptools ];
    dependencies = with pkgs.python3.pkgs; [
      lark
      numpy
      sympy
    ];
  };

  normalization-python = pkgs.python3.withPackages (_: [ liberty-parser ]);
in

stdenvNoCC.mkDerivation {
  pname = "asap7-pdk";
  version = "orfs-aaf99bfa";

  src = orfs;
  dontBuild = true;
  nativeBuildInputs = [
    pkgs.gzip
    pkgs.gnumake
    normalization-python
  ];

  installPhase = ''
    platform=$src/flow/platforms/asap7
    pdk=$out/asap7
    scl=$pdk/libs.ref/asap7sc7p5t
    config=$pdk/libs.tech/librelane

    mkdir -p \
      $scl/techlef \
      $scl/lef \
      $scl/gds \
      $scl/lib \
      $scl/verilog \
      $pdk/libs.tech/klayout \
      $config/asap7sc7p5t

    cp $platform/lef/asap7_tech_1x_201209.lef $scl/techlef/
    cp $platform/lef/asap7sc7p5t_28_R_1x_220121a.lef $scl/lef/
    cp $platform/gds/asap7sc7p5t_28_R_220121a.gds $scl/gds/
    cp $platform/lib/NLDM/*RVT*.lib* $scl/lib/
    cp $platform/verilog/stdcell/*RVT*.v $scl/verilog/
    cp $platform/verilog/stdcell/empty.v $scl/verilog/

    cp $platform/openlane/asap7sc7p5t/no_synth.cells $config/asap7sc7p5t/
    cp $platform/yoSys/cells_latch_R.v $config/asap7sc7p5t/cells_latch.v
    cp $platform/yoSys/cells_adders_R.v $config/asap7sc7p5t/cells_adders.v
    cp $platform/rcx_patterns.rules $config/
    cp $platform/openRoad/pdn/grid_strategy-M1-M2-M5-M6.tcl $config/pdn.tcl

    cp $platform/KLayout/asap7.lyt $pdk/libs.tech/klayout/
    cp $platform/KLayout/asap7.lyp $pdk/libs.tech/klayout/
    cp $platform/drc/asap7.lydrc $pdk/libs.tech/klayout/

    PYTHONPATH=${./.} python ${./test_asap7_liberty.py}
    python ${./asap7_liberty.py} $scl/lib/*RVT*.lib*
    gzip --decompress $scl/lib/*.lib.gz

    ${pkgs.python3}/bin/python ${./asap7_config.py} \
      --orfs-platform $platform \
      --pdk-output $pdk
  '';

  meta = with lib; {
    description = "ASAP7 predictive PDK and 7.5-track standard-cell library";
    homepage = "https://github.com/The-OpenROAD-Project/asap7";
    license = licenses.bsd3;
    platforms = platforms.all;
  };
}
