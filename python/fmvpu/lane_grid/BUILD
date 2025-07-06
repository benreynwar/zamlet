# LaneGrid module test

load("@rules_python//python:defs.bzl", "py_test")
load("//:chisel.bzl", "chisel_binary")

genrule(
    name = "generate_lane_grid_verilog",
    srcs = ["//python/fmvpu:params.json"],
    outs = ["lane_grid_verilog.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/lane_grid_verilog \\
        LaneGrid \\
        $(location //python/fmvpu:params.json)
    cat $$TMPDIR/lane_grid_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src:verilog_generator"],
)

# Create a filegroup to expose the generated Verilog directory
filegroup(
    name = "lane_grid_verilog_files",
    srcs = [":generate_lane_grid_verilog"],
)

py_test(
    name = "test_lane_grid",
    srcs = ["test_lane_grid.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":lane_grid_verilog_files",
        "//python/fmvpu:params.json",
    ],
    args = [
        "$(location :lane_grid_verilog_files)",
        "$(location //python/fmvpu:params.json)",
    ],
    main = "test_lane_grid.py",
)