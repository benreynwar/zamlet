load("//bazel:cocotb_rules.bzl", "cocotb_binary", "cocotb_test")

genrule(
    name = "memlet_default_verilog",
    srcs = ["//configs:zamlet_default.json"],
    outs = ["Memlet_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/memlet:memlet) $$TMPDIR $(location //configs:zamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/memlet:memlet"],
)

cocotb_binary(
    name = "memlet_default_exe",
    verilog_files = [":memlet_default_verilog"],
    module_top = "Memlet",
)

py_library(
    name = "test_cocotb_memlet_py",
    srcs = [
        "test_cocotb_memlet.py",
        "test_write_read.py",
        "memlet_driver.py",
        "model_driver.py",
        "cocotb_driver.py",
    ],
    deps = ["//python/zamlet:zamlet"],
    visibility = ["//python/zamlet/tests:__pkg__"],
)

cocotb_test(
    name = "test_memlet_default",
    binary = ":memlet_default_exe",
    test_module = "zamlet.memlet_test.test_cocotb_memlet",
    toplevel = "Memlet",
    env = {
        "ZAMLET_TEST_CONFIG_FILENAME": "configs/zamlet_default.json",
    },
    data = ["//configs:zamlet_default.json"],
    py_deps = [":test_cocotb_memlet_py"],
)

test_suite(
    name = "all_tests",
    tests = [
        ":test_memlet_default",
    ],
)
