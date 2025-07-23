# Bamlet module tests

load("//python/fmvpu:test_common.bzl", "create_module_tests")

# Config file mapping: short_name -> actual_filename
CONFIGS = {
    "default": "bamlet_default",
}

# Module definitions: name, top_level, extra_args
MODULES = [
    ("bamlet", "Bamlet", []),
]

# Test definitions: name, test_file, verilog_target, special_args
TESTS = [
    ("test_write_im", "test_write_im.py", "bamlet", []),
]

# Generate all Verilog, filegroups, and tests
create_module_tests(MODULES, TESTS, CONFIGS)