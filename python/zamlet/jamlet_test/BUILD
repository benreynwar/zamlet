# Jamlet module tests

load("//bazel:cocotb_rules.bzl", "cocotb_binary", "cocotb_test")

# WitemMonitor tests
genrule(
    name = "witem_monitor_default_verilog",
    srcs = ["//configs:zamlet_default.json"],
    outs = ["WitemMonitor_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/jamlet:witemmonitor) $$TMPDIR $(location //configs:zamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/jamlet:witemmonitor"],
)

cocotb_binary(
    name = "witem_monitor_default_exe",
    verilog_files = [":witem_monitor_default_verilog"],
    module_top = "WitemMonitor",
)

py_library(
    name = "test_witem_monitor_py",
    srcs = ["test_witem_monitor.py"],
    deps = ["//python/zamlet:zamlet"],
)

cocotb_test(
    name = "test_witem_monitor_default",
    binary = ":witem_monitor_default_exe",
    test_module = "zamlet.jamlet_test.test_witem_monitor",
    toplevel = "WitemMonitor",
    env = {
        "ZAMLET_TEST_CONFIG_FILENAME": "configs/zamlet_default.json",
    },
    data = ["//configs:zamlet_default.json"],
    py_deps = [":test_witem_monitor_py"],
)

test_suite(
    name = "all_tests",
    tests = [":test_witem_monitor_default"],
)
