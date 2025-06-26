# DataMemory module test

load("@rules_python//python:defs.bzl", "py_test")
load("//:chisel.bzl", "chisel_binary")

# Test configurations for DataMemory (width, depth, nBanks)
DATA_MEMORY_CONFIGS = [
    {"width": 32, "depth": 16, "nBanks": 2},
    {"width": 64, "depth": 32, "nBanks": 4},
    {"width": 16, "depth": 64, "nBanks": 8},
]

# Generate Verilog files and concatenate into single file for each config
[genrule(
    name = "data_memory_verilog_{}w_{}d_{}b".format(config["width"], config["depth"], config["nBanks"]),
    outs = ["data_memory_{}w_{}d_{}b.sv".format(config["width"], config["depth"], config["nBanks"])],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //python/fmvpu:verilog_generator) \\
        $$TMPDIR/data_memory_verilog \\
        DataMemory \\
        {} \\
        {} \\
        {}
    cat $$TMPDIR/data_memory_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """.format(config["width"], config["depth"], config["nBanks"]),
    tools = ["//python/fmvpu:verilog_generator"],
) for config in DATA_MEMORY_CONFIGS]

# Create filegroups to expose the generated Verilog files
[filegroup(
    name = "data_memory_verilog_files_{}w_{}d_{}b".format(config["width"], config["depth"], config["nBanks"]),
    srcs = [":data_memory_verilog_{}w_{}d_{}b".format(config["width"], config["depth"], config["nBanks"])],
) for config in DATA_MEMORY_CONFIGS]

# Create py_test targets for each configuration
[py_test(
    name = "test_data_memory_{}w_{}d_{}b".format(config["width"], config["depth"], config["nBanks"]),
    srcs = ["test_data_memory.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":data_memory_verilog_files_{}w_{}d_{}b".format(config["width"], config["depth"], config["nBanks"]),
    ],
    args = [
        "$(location :data_memory_verilog_files_{}w_{}d_{}b)".format(config["width"], config["depth"], config["nBanks"]),
    ],
    main = "test_data_memory.py",
) for config in DATA_MEMORY_CONFIGS]

# Test suite that runs all configurations
test_suite(
    name = "test_data_memory",
    tests = [
        ":test_data_memory_{}w_{}d_{}b".format(config["width"], config["depth"], config["nBanks"])
        for config in DATA_MEMORY_CONFIGS
    ],
)