# Repository rule to find Nix-provided cocotb

def _find_nix_cocotb_impl(repository_ctx):
    # Watch nix files - when these change, Bazel refetches this repository
    repository_ctx.watch(repository_ctx.path(Label("//:shell.nix")))
    repository_ctx.watch(repository_ctx.path(Label("//nix:common.nix")))

    # Find cocotb installation
    result = repository_ctx.execute([
        "python3", "-c",
        "import cocotb, os; print(os.path.dirname(cocotb.__file__))"
    ])
    if result.return_code != 0:
        fail("cocotb not found. Are you in nix-shell? Error: " + result.stderr)
    cocotb_path = result.stdout.strip()

    # Find Python library directory (for LD_LIBRARY_PATH)
    result = repository_ctx.execute([
        "python3", "-c",
        "import sysconfig; print(sysconfig.get_config_var('LIBDIR'))"
    ])
    if result.return_code != 0:
        fail("Failed to find Python LIBDIR: " + result.stderr)
    python_libdir = result.stdout.strip()

    # Find Python interpreter path
    result = repository_ctx.execute(["python3", "-c", "import sys; print(sys.executable)"])
    if result.return_code != 0:
        fail("Failed to find Python executable: " + result.stderr)
    python_bin = result.stdout.strip()

    # Find Python version for library name
    result = repository_ctx.execute([
        "python3", "-c",
        "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    ])
    if result.return_code != 0:
        fail("Failed to find Python version: " + result.stderr)
    python_version = result.stdout.strip()

    # Paths within cocotb installation
    libs_dir = cocotb_path + "/libs"
    include_dir = cocotb_path + "/share/include"
    verilator_cpp = cocotb_path + "/share/lib/verilator/verilator.cpp"

    # Symlink directories for Bazel access
    repository_ctx.symlink(libs_dir, "libs")
    repository_ctx.symlink(include_dir, "include")
    repository_ctx.symlink(verilator_cpp, "verilator.cpp")

    # Symlink Python library (both versioned and unversioned for cocotb dlopen)
    python_lib_versioned = "libpython{}.so.1.0".format(python_version)
    python_lib_unversioned = "libpython{}.so".format(python_version)
    repository_ctx.symlink(python_libdir + "/" + python_lib_versioned, python_lib_versioned)
    repository_ctx.symlink(python_libdir + "/" + python_lib_unversioned, python_lib_unversioned)

    repository_ctx.file("BUILD.bazel", '''
load("@//bazel/toolchains:cocotb.bzl", "cocotb_toolchain")

cocotb_toolchain(
    name = "toolchain_impl",
    libs_dir = "{libs_dir}",
    include_dir = "{include_dir}",
    verilator_cpp = "{verilator_cpp}",
    python_libdir = "{python_libdir}",
    python_bin = "{python_bin}",
)

toolchain(
    name = "toolchain",
    toolchain = ":toolchain_impl",
    toolchain_type = "@//bazel/toolchains:cocotb_toolchain_type",
)

# Cocotb shared libraries
cc_import(
    name = "libcocotbvpi_verilator",
    shared_library = "libs/libcocotbvpi_verilator.so",
    visibility = ["//visibility:public"],
)

cc_import(
    name = "libcocotb",
    shared_library = "libs/libcocotb.so",
    visibility = ["//visibility:public"],
)

cc_import(
    name = "libgpi",
    shared_library = "libs/libgpi.so",
    visibility = ["//visibility:public"],
)

cc_import(
    name = "libembed",
    shared_library = "libs/libembed.so",
    visibility = ["//visibility:public"],
)

cc_import(
    name = "libgpilog",
    shared_library = "libs/libgpilog.so",
    visibility = ["//visibility:public"],
)

cc_import(
    name = "libcocotbutils",
    shared_library = "libs/libcocotbutils.so",
    visibility = ["//visibility:public"],
)

cc_import(
    name = "libpygpilog",
    shared_library = "libs/libpygpilog.so",
    visibility = ["//visibility:public"],
)

cc_library(
    name = "cocotb_libs",
    deps = [
        ":libcocotbvpi_verilator",
        ":libcocotb",
        ":libgpi",
        ":libembed",
        ":libgpilog",
        ":libcocotbutils",
        ":libpygpilog",
    ],
    visibility = ["//visibility:public"],
)

cc_library(
    name = "cocotb_headers",
    hdrs = glob(["include/**/*.h"]),
    includes = ["include"],
    visibility = ["//visibility:public"],
)

filegroup(
    name = "verilator_cpp",
    srcs = ["verilator.cpp"],
    visibility = ["//visibility:public"],
)

# Python library for linking (provides -lpython flags)
load("@//bazel/toolchains:python_libs.bzl", "python_libs")

python_libs(
    name = "python_libs",
    visibility = ["//visibility:public"],
)
'''.format(
        libs_dir = libs_dir,
        include_dir = include_dir,
        verilator_cpp = verilator_cpp,
        python_libdir = python_libdir,
        python_bin = python_bin,
    ))

find_nix_cocotb = repository_rule(
    implementation = _find_nix_cocotb_impl,
    local = True,
    environ = ["PATH"],
)
