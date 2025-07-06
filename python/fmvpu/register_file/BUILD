# RegisterFile module test

load("@rules_python//python:defs.bzl", "py_test")
load("//:chisel.bzl", "chisel_binary")

# Test configurations for RegisterFile (width, depth, nReadPorts, nWritePorts)
REGISTER_FILE_CONFIGS = [
    {"width": 32, "depth": 16, "nReadPorts": 2, "nWritePorts": 2},
    {"width": 64, "depth": 32, "nReadPorts": 3, "nWritePorts": 1},
    {"width": 16, "depth": 8, "nReadPorts": 1, "nWritePorts": 3},
]

# Generate Verilog files and concatenate into single file for each config
[genrule(
    name = "register_file_verilog_{}w_{}d_{}r_{}w".format(config["width"], config["depth"], config["nReadPorts"], config["nWritePorts"]),
    outs = ["register_file_{}w_{}d_{}r_{}w.sv".format(config["width"], config["depth"], config["nReadPorts"], config["nWritePorts"])],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/register_file_verilog \\
        RegisterFile \\
        {} \\
        {} \\
        {} \\
        {}
    cat $$TMPDIR/register_file_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """.format(config["width"], config["depth"], config["nReadPorts"], config["nWritePorts"]),
    tools = ["//src:verilog_generator"],
) for config in REGISTER_FILE_CONFIGS]

# Create filegroups to expose the generated Verilog files
[filegroup(
    name = "register_file_verilog_files_{}w_{}d_{}r_{}w".format(config["width"], config["depth"], config["nReadPorts"], config["nWritePorts"]),
    srcs = [":register_file_verilog_{}w_{}d_{}r_{}w".format(config["width"], config["depth"], config["nReadPorts"], config["nWritePorts"])],
) for config in REGISTER_FILE_CONFIGS]

# Create py_test targets for each configuration
[py_test(
    name = "test_register_file_{}w_{}d_{}r_{}w".format(config["width"], config["depth"], config["nReadPorts"], config["nWritePorts"]),
    srcs = ["test_register_file.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":register_file_verilog_files_{}w_{}d_{}r_{}w".format(config["width"], config["depth"], config["nReadPorts"], config["nWritePorts"]),
    ],
    args = [
        "$(location :register_file_verilog_files_{}w_{}d_{}r_{}w)".format(config["width"], config["depth"], config["nReadPorts"], config["nWritePorts"]),
        str(config["width"]),
        str(config["depth"]),
        str(config["nReadPorts"]),
        str(config["nWritePorts"]),
    ],
    main = "test_register_file.py",
) for config in REGISTER_FILE_CONFIGS]

# Test suite that runs all configurations
test_suite(
    name = "test_register_file",
    tests = [
        ":test_register_file_{}w_{}d_{}r_{}w".format(config["width"], config["depth"], config["nReadPorts"], config["nWritePorts"])
        for config in REGISTER_FILE_CONFIGS
    ],
)
