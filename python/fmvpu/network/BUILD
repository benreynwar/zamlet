# NetworkNode module test

load("@rules_python//python:defs.bzl", "py_test")
load("//:chisel.bzl", "chisel_binary")

genrule(
    name = "generate_network_verilog",
    srcs = ["//python/fmvpu:params.json"],
    outs = ["network_verilog.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //python/fmvpu:verilog_generator) \\
        $$TMPDIR/network_verilog \\
        NetworkNode \\
        $(location //python/fmvpu:params.json)
    cat $$TMPDIR/network_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//python/fmvpu:verilog_generator"],
)

# Create a filegroup to expose the generated Verilog directory
filegroup(
    name = "network_verilog_files",
    srcs = [":generate_network_verilog"],
)

py_test(
    name = "test_network",
    srcs = ["test_network.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":network_verilog_files",
        "//python/fmvpu:params.json",
    ],
    args = [
        "$(location :network_verilog_files)",
        "$(location //python/fmvpu:params.json)",
    ],
    main = "test_network.py",
)