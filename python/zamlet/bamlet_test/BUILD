# Bamlet module tests

load("//bazel:test_common.bzl", "create_module_tests")

# Config file mapping: short_name -> actual_filename
CONFIGS = {
    "default": "bamlet_default",
}

# Module definitions: name, top_level, extra_args
MODULES = [
    ("bamlet", "Bamlet", []),
    ("dependency_tracker", "DependencyTracker", []),
]

# Test definitions: name, test_file, verilog_target, special_args
TESTS = [
    ("test_write_im", "test_write_im.py", "bamlet", []),
    ("test_basic", "test_basic.py", "bamlet", []),
    ("test_alu", "test_alu.py", "bamlet", []),
    ("test_alu_lite", "test_alu_lite.py", "bamlet", []),
    ("test_ldst", "test_ldst.py", "bamlet", []),
    ("test_packet", "test_packet.py", "bamlet", []),
    ("test_receive", "test_receive.py", "bamlet", []),
    ("test_predicate", "test_predicate.py", "bamlet", []),
    ("test_loops", "test_loops.py", "bamlet", []),
    ("test_dependency_tracker", "test_dependency_tracker.py", "dependency_tracker", []),
]

# Generate all Verilog, filegroups, and tests
create_module_tests(MODULES, TESTS, CONFIGS)
