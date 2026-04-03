# Dependencies

The dependencies for this project are installed using nix.

1. Install nix
2. Add the following to /etc/nix/nix.conf

        extra-experimental-features = nix-command flakes
        extra-substituters = https://nix-cache.fossi-foundation.org
        extra-trusted-public-keys = nix-cache.fossi-foundation.org:3+K59iFwXqKsL7BNu6Guy0v+uTlwsxYQxjspXzqLYQs=

    This allows nix to use the precompiled FOSSi binaries which speeds things up a bunch.

3. Run `nix-shell` in the project directory.

Hopefully after this you're in a nix shell with all the dependencies installed.

# Build System

Bazel is used as the build system for this project.  It's the first time I've used bazel and I've been leaning
heavily on Claude to write the bazel files. I expect that they are a hot vibe coded mess.
That said, I've been finding bazel very pleasant to use.

**Some randomly selected interesting bazel targets to run would be:**

Builds and generates a GDS for the router. Uses librelane and the skywater130 PDK.
Currently fails due to routing congestion, but maybe I'll have fixed it by the time you run this.

    bazel build //dse/network:CombinedNetworkNode_default_sky130hd_gds

Generates the verilog for a kamlet mesh, and runs a cocotb test that tests
the synchronization network.

    bazel test //python/zamlet/kamlet_test:test_kamlet_default

**Some interesting non-bazel targets to run would be:**

Runs a bunch of tests of strided loads using the python model of the architecture.

    python -m pytest python/zamlet/tests/test_strided_load.py

Runs a FFT kernel on the python model.

    python python/zamlet/kernel_tests/fft/test_fft.py
