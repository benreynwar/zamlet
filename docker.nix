# Build Docker image - uses common.nix for shared configuration
# Usage: nix-build docker.nix && docker load < result
let
  common = import ./nix/common.nix;
  inherit (common) pkgs buildInputs;

  # nixpkgs-unstable for claude-code (not yet in 24.05)
  nixpkgs-unstable = fetchTarball "https://github.com/NixOS/nixpkgs/archive/nixos-unstable.tar.gz";
  unstable = import nixpkgs-unstable { config.allowUnfree = true; };
in
pkgs.dockerTools.buildImage {
  name = "zamlet";
  tag = "latest";

  copyToRoot = pkgs.buildEnv {
    name = "zamlet-env";
    paths = buildInputs ++ (with pkgs; [
      # Base utilities (not needed in shell, but needed in container)
      bashInteractive
      coreutils
      gnugrep
      gnused
      findutils
      gawk
      curl
      wget
      gnumake
      gcc

      # Node.js for Claude Code
      nodejs

      # SSL certificates
      cacert

      # Nix package manager (for installing packages at runtime)
      nix

      # Utilities
      less
      vim
      tmux

      # Docker client (for Docker-in-Docker)
      docker-client

      # Claude Code (from unstable)
      unstable.claude-code
    ]);
    pathsToLink = [ "/bin" "/lib" "/share" "/etc" ];
  };

  config = {
    Cmd = [ "/bin/bash" ];
    WorkingDir = "/workspace";
    Env = [
      "LANG=C.UTF-8"
      "LC_ALL=C.UTF-8"
      "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
      "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
    ];
  };
}
