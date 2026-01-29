# Repository rule to find Nix-provided Verilator

def _find_nix_verilator_impl(repository_ctx):
    # Watch nix files - when these change, Bazel refetches this repository
    repository_ctx.watch(repository_ctx.path(Label("//:shell.nix")))
    repository_ctx.watch(repository_ctx.path(Label("//nix:common.nix")))

    # Find verilator binary
    result = repository_ctx.execute(["which", "verilator"])
    if result.return_code != 0:
        fail("verilator not found in PATH. Are you in nix-shell?")
    verilator_bin = result.stdout.strip()

    # Derive include path from binary location
    verilator_root = verilator_bin.rsplit("/", 2)[0]
    include_dir = verilator_root + "/share/verilator/include"

    # Symlink include directory for cc_library access
    repository_ctx.symlink(include_dir, "include")

    repository_ctx.file("BUILD.bazel", '''
load("@//bazel/toolchains:verilator.bzl", "verilator_toolchain")

verilator_toolchain(
    name = "toolchain_impl",
    verilator_bin = "{verilator_bin}",
    include_dir = "{include_dir}",
)

toolchain(
    name = "toolchain",
    toolchain = ":toolchain_impl",
    toolchain_type = "@//bazel/toolchains:verilator_toolchain_type",
)

# Verilator runtime headers for compilation
cc_library(
    name = "verilator_includes",
    hdrs = glob(["include/**/*.h", "include/**/*.cpp"]),
    includes = ["include", "include/vltstd"],
    visibility = ["//visibility:public"],
)

# Verilator runtime sources needed for simulation
filegroup(
    name = "verilator_sources",
    srcs = [
        "include/verilated.cpp",
        "include/verilated_vcd_c.cpp",
        "include/verilated_threads.cpp",
        "include/verilated_dpi.cpp",
        "include/verilated_vpi.cpp",
    ],
    visibility = ["//visibility:public"],
)
'''.format(
        verilator_bin = verilator_bin,
        include_dir = include_dir,
    ))

find_nix_verilator = repository_rule(
    implementation = _find_nix_verilator_impl,
    local = True,
    environ = ["PATH"],
)
