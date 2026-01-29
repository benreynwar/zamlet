# python_libs rule - provides linker flags for embedding Python in C++
# Based on rules_cocotb_verilator's python_libs.bzl

load("@rules_cc//cc/common:cc_common.bzl", "cc_common")
load("@rules_cc//cc/common:cc_info.bzl", "CcInfo")

def _python_libs_impl(ctx):
    # Get Python info from cocotb toolchain
    cocotb_tc = ctx.toolchains["//bazel/toolchains:cocotb_toolchain_type"].cocotb

    # Extract version from python_bin path or python_libdir
    # The libdir contains libpython3.X.so, so we can derive the version
    # For simplicity, we'll use a Python query at analysis time isn't possible,
    # so we'll construct the flag based on what we know

    # Create linker flags to link against Python
    # We use -L to add the library path and -lpython3.X
    # The actual version is embedded in the library filename in python_libdir
    link_flags = [
        "-L" + cocotb_tc.python_libdir,
        "-Wl,-rpath," + cocotb_tc.python_libdir,
    ]

    # Find Python version by looking at python_bin (e.g., .../python3.11)
    # or we can just use -lpython3 which should work
    python_bin = cocotb_tc.python_bin
    if "python3." in python_bin:
        # Extract version like "3.11" from path
        import_idx = python_bin.rfind("python")
        version_part = python_bin[import_idx + 6:]  # After "python"
        if version_part:
            link_flags.append("-lpython" + version_part)
        else:
            link_flags.append("-lpython3")
    else:
        link_flags.append("-lpython3")

    linker_input = cc_common.create_linker_input(
        owner = ctx.label,
        user_link_flags = depset(link_flags),
    )

    return [CcInfo(
        linking_context = cc_common.create_linking_context(
            linker_inputs = depset([linker_input]),
        ),
    )]

python_libs = rule(
    implementation = _python_libs_impl,
    toolchains = ["//bazel/toolchains:cocotb_toolchain_type"],
    doc = "Provides linker flags for embedding Python in C++ (uses Nix Python from cocotb toolchain)",
)
