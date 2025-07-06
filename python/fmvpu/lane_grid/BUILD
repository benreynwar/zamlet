# LaneGrid module test

load("@rules_python//python:defs.bzl", "py_test")
load("//:chisel.bzl", "chisel_binary")

# List of config names to create targets for
CONFIG_NAMES = [
    "default",
]

[genrule(
    name = "generate_lane_grid_verilog_" + config,
    srcs = ["//configs:" + config + ".json"],
    outs = ["lane_grid_verilog_" + config + ".sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/lane_grid_verilog \\
        LaneGrid \\
        $(location //configs:""" + config + """.json)
    cat $$TMPDIR/lane_grid_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src:verilog_generator"],
) for config in CONFIG_NAMES]

# Create filegroups and tests for each config file
[filegroup(
    name = "lane_grid_verilog_files_" + config,
    srcs = [":generate_lane_grid_verilog_" + config],
) for config in CONFIG_NAMES]

[py_test(
    name = "test_lane_grid_" + config,
    srcs = ["test_lane_grid.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":lane_grid_verilog_files_" + config,
        "//configs:" + config + ".json",
    ],
    args = [
        "$(location :lane_grid_verilog_files_" + config + ")",
        "$(location //configs:" + config + ".json)",
    ],
    main = "test_lane_grid.py",
) for config in CONFIG_NAMES]
