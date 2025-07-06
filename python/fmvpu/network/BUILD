# NetworkNode module test

load("@rules_python//python:defs.bzl", "py_test")
load("//:chisel.bzl", "chisel_binary")

# List of config names to create targets for
CONFIG_NAMES = [
    "default",
]

[genrule(
    name = "generate_network_verilog_" + config,
    srcs = ["//configs:" + config + ".json"],
    outs = ["network_verilog_" + config + ".sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/network_verilog \\
        NetworkNode \\
        $(location //configs:""" + config + """.json)
    cat $$TMPDIR/network_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src:verilog_generator"],
) for config in CONFIG_NAMES]

# Create filegroups and tests for each config file
[filegroup(
    name = "network_verilog_files_" + config,
    srcs = [":generate_network_verilog_" + config],
) for config in CONFIG_NAMES]

[py_test(
    name = "test_network_" + config,
    srcs = ["test_network.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":network_verilog_files_" + config,
        "//configs:" + config + ".json",
    ],
    args = [
        "$(location :network_verilog_files_" + config + ")",
        "$(location //configs:" + config + ".json)",
    ],
    main = "test_network.py",
) for config in CONFIG_NAMES]
