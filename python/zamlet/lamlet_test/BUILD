# Lamlet module tests

load("//bazel:defs.bzl", "cocotb_exe", "cocotb_script")
load("@rules_hdl//verilog:defs.bzl", "verilog_library")

# Generate Lamlet verilog
genrule(
    name = "lamlet_default_verilog",
    srcs = ["//configs:lamlet_default.json"],
    outs = ["Lamlet_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/lamlet:lamlet) $$TMPDIR $(location //configs:lamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/lamlet:lamlet"],
)

# Verilog library for bazel_rules_hdl
verilog_library(
    name = "lamlet_default_verilog_lib",
    srcs = [":lamlet_default_verilog"],
)

# Cocotb executable
cocotb_exe(
    name = "lamlet_default_exe",
    verilog_library = ":lamlet_default_verilog_lib",
    module_top = "Lamlet",
)

# Test Python library
py_library(
    name = "test_lamlet_py",
    srcs = ["test_lamlet.py"],
    imports = ["."],
    deps = [
        "//python/zamlet:zamlet",
        "@zamlet_pip_deps//cocotb",
    ],
)

# Cocotb test script
cocotb_script(
    name = "test_lamlet_default",
    binary = ":lamlet_default_exe",
    script = ":test_lamlet_py",
    module = "test_lamlet",
    toplevel = "Lamlet",
)
