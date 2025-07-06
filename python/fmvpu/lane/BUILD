# Lane module test

load("@rules_python//python:defs.bzl", "py_test")
load("//:chisel.bzl", "chisel_binary")

genrule(
    name = "generate_lane_verilog",
    srcs = ["//python/fmvpu:params.json"],
    outs = ["lane_verilog.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/lane_verilog \\
        Lane \\
        $(location //python/fmvpu:params.json)
    cat $$TMPDIR/lane_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src:verilog_generator"],
)

# Create a filegroup to expose the generated Verilog directory
filegroup(
    name = "lane_verilog_files",
    srcs = [":generate_lane_verilog"],
)

py_test(
    name = "test_lane",
    srcs = ["test_lane.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":lane_verilog_files",
        "//python/fmvpu:params.json",
    ],
    args = [
        "$(location :lane_verilog_files)",
        "$(location //python/fmvpu:params.json)",
    ],
    main = "test_lane.py",
)
