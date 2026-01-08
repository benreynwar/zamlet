# Kamlet module tests

load("//bazel:defs.bzl", "cocotb_exe", "cocotb_script")
load("@rules_hdl//verilog:defs.bzl", "verilog_library")

# Generate Synchronizer verilog using the dedicated generator
genrule(
    name = "synchronizer_default_verilog",
    srcs = ["//configs:synchronizer_default.json"],
    outs = ["Synchronizer_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/kamlet:synchronizer) $$TMPDIR $(location //configs:synchronizer_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/kamlet:synchronizer"],
)

# Verilog library for bazel_rules_hdl
verilog_library(
    name = "synchronizer_default_verilog_lib",
    srcs = [":synchronizer_default_verilog"],
)

# Cocotb executable
cocotb_exe(
    name = "synchronizer_default_exe",
    verilog_library = ":synchronizer_default_verilog_lib",
    module_top = "Synchronizer",
)

# Test Python library
py_library(
    name = "test_synchronizer_py",
    srcs = ["test_synchronizer.py"],
    imports = ["."],
    deps = [
        "//python/zamlet:zamlet",
        "@zamlet_pip_deps//cocotb",
    ],
)

# Cocotb test script
cocotb_script(
    name = "test_synchronizer_default",
    binary = ":synchronizer_default_exe",
    script = ":test_synchronizer_py",
    module = "test_synchronizer",
    toplevel = "Synchronizer",
)
