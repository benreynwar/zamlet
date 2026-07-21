{ pkgs }:

pkgs.stdenv.mkDerivation {
  pname = "open-src-cvc";
  version = "0-unstable-2024-03-11";

  src = pkgs.fetchFromGitHub {
    owner = "cambridgehackers";
    repo = "open-src-cvc";
    rev = "1c5e043ec33ef6f1fdbf38565501c944893a83cf";
    hash = "sha256-15cuJmbyvYdZjfYY6s9Wf76Hr/x6AYKxjsyHpHfKLRk=";
  };

  nativeBuildInputs = [ pkgs.makeWrapper ];
  buildInputs = [ pkgs.zlib ];

  buildPhase = ''
    runHook preBuild
    make -C src cvc64
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin $out/include/cvc $out/share/licenses/open-src-cvc
    cp build64/cvc64 $out/bin/
    ln -s cvc64 $out/bin/cvc
    cp -r pli_incs/. $out/include/cvc/
    cp OSS-CVC-MODIFIED-ARTISTIC-LIC.TXT \
      OSS-CVC-ARTISTIC-LICENSING-FAQ.pdf \
      $out/share/licenses/open-src-cvc/
    wrapProgram $out/bin/cvc64 \
      --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.stdenv.cc pkgs.binutils ]}
    runHook postInstall
  '';

  meta = {
    description = "Tachyon CVC IEEE 1364 Verilog simulator";
    homepage = "https://github.com/cambridgehackers/open-src-cvc";
    license = pkgs.lib.licenses.unfreeRedistributable;
    platforms = [ "x86_64-linux" ];
    mainProgram = "cvc";
  };
}
