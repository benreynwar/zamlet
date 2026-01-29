#!/usr/bin/env bash
# Run the zamlet Docker container
# Build first with: nix-build docker.nix && docker load < result

docker run -it \
  -v "$(pwd)":/workspace \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$HOME/.vimrc":/root/.vimrc:ro \
  -v "$HOME/.vim":/root/.vim:ro \
  -v "$HOME/.tmux.conf":/root/.tmux.conf:ro \
  -w /workspace \
  zamlet:latest "$@"
