# Gamlet module tests

load("//bazel:test_common.bzl", "create_module_tests")

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

# Generate all Verilog, filegroups, and tests
create_module_tests(MODULES, TESTS, CONFIGS)