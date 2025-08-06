# Gamlet module tests

load("@rules_python//python:defs.bzl", "py_test")
load("//:chisel.bzl", "chisel_binary")

# Config file mapping: short_name -> actual_filename
CONFIGS = {
    "default": "gamlet_default",
}

# Module definitions: name, top_level, extra_args
MODULES = [
    ("rename", "Rename", []),
]

# Test definitions: name, test_file, verilog_target, special_args
TESTS = [
    ("test_rename_basic", "test_rename_basic.py", "rename", []),
]

# Generate Verilog files for each module + config combination
[genrule(
    name = "{}_{}_verilog".format(name, config_name),
    srcs = ["//configs:{}.json".format(config_file)],
    outs = ["{}_{}.sv".format(name, config_name)],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/{name}_{config_name}_verilog \\
        {top_level} \\
        $(location //configs:{config_file}.json) {extra_args}
    cat $$TMPDIR/{name}_{config_name}_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """.format(name=name, config_name=config_name, top_level=top_level, config_file=config_file, extra_args=" ".join(extra_args)),
    tools = ["//src:verilog_generator"],
) for name, top_level, extra_args in MODULES for config_name, config_file in CONFIGS.items()]

# Create filegroups for all Verilog files
[filegroup(
    name = "{}_{}_verilog_files".format(name, config_name),
    srcs = [":{}_{}_verilog".format(name, config_name)],
) for name, _, _ in MODULES for config_name, _ in CONFIGS.items()]

# Generate all tests for each config
[py_test(
    name = "{}_{}".format(test_name, config_name),
    srcs = [test_file],
    deps = [
        "//python/zamlet:zamlet",
    ],
    data = [
        ":{}_{}_verilog_files".format(verilog_target, config_name),
        "//configs:{}.json".format(config_file),
    ],
    args = special_args + [
        "$(location :{}_{}_verilog_files)".format(verilog_target, config_name),
        "$(location //configs:{}.json)".format(config_file),
    ],
    main = test_file,
) for test_name, test_file, verilog_target, special_args in TESTS for config_name, config_file in CONFIGS.items()]