# Shuttle core cocotb tests

load("@rules_hdl//verilog:defs.bzl", "verilog_library")
load("//bazel:defs.bzl", "cocotb_exe", "cocotb_script", "riscv_asm_binary")

# Generate Shuttle Verilog using the shuttle_tile_generator
genrule(
    name = "shuttle_verilog",
    outs = ["ShuttleTop.sv"],
    cmd = """
        TMPDIR=$$(mktemp -d)
        $(location //src:shuttle_tile_generator) $$TMPDIR minimal
        cat $$TMPDIR/*.sv > $@
        rm -rf $$TMPDIR
    """,
    tools = ["//src:shuttle_tile_generator"],
)

verilog_library(
    name = "shuttle_verilog_lib",
    srcs = [":shuttle_verilog"],
)

cocotb_exe(
    name = "shuttle_exe",
    verilog_library = ":shuttle_verilog_lib",
    module_top = "ShuttleTop",
)

# Shared test runner library
py_library(
    name = "shuttle_test_runner",
    srcs = ["shuttle_test_runner.py"],
    imports = ["."],
    deps = [
        "@zamlet_pip_deps//cocotb",
        "@cocotb_bus//:cocotb_bus",
        "@cocotbext_axi//:cocotbext_axi",
    ],
)

# Test binaries
riscv_asm_binary(
    name = "test_simple_bin",
    src = "test_simple.S",
    linker_script = "link.ld",
)

riscv_asm_binary(
    name = "test_loop_bin",
    src = "test_loop.S",
    linker_script = "link.ld",
)

# Tests
cocotb_script(
    name = "test_simple",
    binary = ":shuttle_exe",
    script = ":shuttle_test_runner",
    module = "shuttle_test_runner",
    toplevel = "ShuttleTop",
    data = [":test_simple_bin"],
    env = {"ZAMLET_TEST_BINARY": "$(location :test_simple_bin)"},
)

cocotb_script(
    name = "test_loop",
    binary = ":shuttle_exe",
    script = ":shuttle_test_runner",
    module = "shuttle_test_runner",
    toplevel = "ShuttleTop",
    data = [":test_loop_bin"],
    env = {"ZAMLET_TEST_BINARY": "$(location :test_loop_bin)"},
)
