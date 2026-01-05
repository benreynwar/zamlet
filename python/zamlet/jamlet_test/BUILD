# Jamlet module tests

load("//bazel:test_common.bzl", "create_module_tests")

# Config file mapping: short_name -> actual_filename
CONFIGS = {
    "default": "jamlet_default",
}

# Module definitions: name, top_level, extra_args
MODULES = [
    ("witem_monitor", "WitemMonitor", []),
]

# Test definitions: name, test_file, verilog_target, special_args
TESTS = [
    ("test_witem_monitor", "test_witem_monitor.py", "witem_monitor", []),
]

# Generate all Verilog, filegroups, and tests
create_module_tests(MODULES, TESTS, CONFIGS)
