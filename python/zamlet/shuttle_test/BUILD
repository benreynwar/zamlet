# Shuttle core cocotb tests

load("//bazel:cocotb_rules.bzl", "cocotb_binary", "cocotb_test")
load("//bazel:defs.bzl", "riscv_asm_binary")

# Generate Shuttle Verilog
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

cocotb_binary(
    name = "shuttle_exe",
    verilog_files = [":shuttle_verilog"],
    module_top = "ShuttleTop",
)

# Shared test runner library
py_library(
    name = "shuttle_test_runner_py",
    srcs = ["shuttle_test_runner.py"],
    deps = ["//python/zamlet:zamlet"],
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
cocotb_test(
    name = "test_simple",
    binary = ":shuttle_exe",
    test_module = "zamlet.shuttle_test.shuttle_test_runner",
    toplevel = "ShuttleTop",
    data = [":test_simple_bin"],
    env = {"ZAMLET_TEST_BINARY": "$(location :test_simple_bin)"},
    py_deps = [":shuttle_test_runner_py"],
)

cocotb_test(
    name = "test_loop",
    binary = ":shuttle_exe",
    test_module = "zamlet.shuttle_test.shuttle_test_runner",
    toplevel = "ShuttleTop",
    data = [":test_loop_bin"],
    env = {"ZAMLET_TEST_BINARY": "$(location :test_loop_bin)"},
    py_deps = [":shuttle_test_runner_py"],
)

# Oamlet (Shuttle + Zamlet vector unit) tests
cocotb_binary(
    name = "oamlet_exe",
    verilog_files = ["//src:oamlet_verilog"],
    module_top = "OamletTop",
)

cocotb_test(
    name = "test_simple_oamlet",
    binary = ":oamlet_exe",
    test_module = "zamlet.shuttle_test.shuttle_test_runner",
    toplevel = "OamletTop",
    data = [":test_simple_bin"],
    env = {"ZAMLET_TEST_BINARY": "$(location :test_simple_bin)"},
    py_deps = [":shuttle_test_runner_py"],
)

cocotb_test(
    name = "test_loop_oamlet",
    binary = ":oamlet_exe",
    test_module = "zamlet.shuttle_test.shuttle_test_runner",
    toplevel = "OamletTop",
    data = [":test_loop_bin"],
    env = {"ZAMLET_TEST_BINARY": "$(location :test_loop_bin)"},
    py_deps = [":shuttle_test_runner_py"],
)

test_suite(
    name = "all_tests",
    tests = [
        ":test_simple",
        ":test_loop",
        ":test_simple_oamlet",
        ":test_loop_oamlet",
    ],
)
