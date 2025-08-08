# Amlet module tests

load("//bazel:test_common.bzl", "create_module_tests")

# Config file mapping: short_name -> actual_filename
CONFIGS = {
    "default": "amlet_default",
}

# Module definitions: name, top_level, extra_args
MODULES = [
    ("alurs", "ALURS", []),
    ("alu", "ALU", []),
]

# Test definitions: name, test_file, verilog_target, special_args
TESTS = [
    ("test_alurs_basic", "test_alurs_basic.py", "alurs", []),
    ("test_alu_basic", "test_alu_basic.py", "alu", []),
]


# Generate all Verilog, filegroups, and tests
create_module_tests(MODULES, TESTS, CONFIGS)