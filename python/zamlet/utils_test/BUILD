# Utils module tests

load("//bazel:test_common.bzl", "create_module_tests")

# Config file mapping: short_name -> actual_filename
CONFIGS = {
    "default": "dropping_fifo_default",
}

# Module definitions: name, top_level, extra_args
MODULES = [
    ("dropping_fifo", "DroppingFifo", []),
]

# Test definitions: name, test_file, verilog_target, special_args
TESTS = [
    ("test_dropping_fifo", "test_dropping_fifo.py", "dropping_fifo", []),
]

# Generate all Verilog, filegroups, and tests
create_module_tests(MODULES, TESTS, CONFIGS)