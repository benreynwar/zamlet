# AdjustableDelay module test

load("@rules_python//python:defs.bzl", "py_test")
load("//:chisel.bzl", "chisel_binary")

# Test configurations for AdjustableDelay (max_delay, width)
ADJUSTABLE_DELAY_CONFIGS = [
    {"max_delay": 8, "width": 16},
    {"max_delay": 16, "width": 32},
    {"max_delay": 32, "width": 64},
]

# Generate Verilog files and concatenate into single file for each config
[genrule(
    name = "adjustable_delay_verilog_{}d_{}w".format(config["max_delay"], config["width"]),
    outs = ["adjustable_delay_{}d_{}w.sv".format(config["max_delay"], config["width"])],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/adjustable_delay_verilog \\
        AdjustableDelay \\
        {} \\
        {}
    cat $$TMPDIR/adjustable_delay_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """.format(config["max_delay"], config["width"]),
    tools = ["//src:verilog_generator"],
) for config in ADJUSTABLE_DELAY_CONFIGS]

# Create filegroups to expose the generated Verilog files
[filegroup(
    name = "adjustable_delay_verilog_files_{}d_{}w".format(config["max_delay"], config["width"]),
    srcs = [":adjustable_delay_verilog_{}d_{}w".format(config["max_delay"], config["width"])],
) for config in ADJUSTABLE_DELAY_CONFIGS]

# Create py_test targets for each configuration
[py_test(
    name = "test_adjustable_delay_{}d_{}w".format(config["max_delay"], config["width"]),
    srcs = ["test_adjustable_delay.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":adjustable_delay_verilog_files_{}d_{}w".format(config["max_delay"], config["width"]),
    ],
    args = [
        "$(location :adjustable_delay_verilog_files_{}d_{}w)".format(config["max_delay"], config["width"]),
        str(config["max_delay"]),
        str(config["width"]),
    ],
    main = "test_adjustable_delay.py",
) for config in ADJUSTABLE_DELAY_CONFIGS]

# Test suite that runs all configurations
test_suite(
    name = "test_adjustable_delay",
    tests = [
        ":test_adjustable_delay_{}d_{}w".format(config["max_delay"], config["width"])
        for config in ADJUSTABLE_DELAY_CONFIGS
    ],
)