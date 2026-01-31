# Lamlet module tests

load("//bazel:cocotb_rules.bzl", "cocotb_binary", "cocotb_test")

# Lamlet tests
genrule(
    name = "lamlet_default_verilog",
    srcs = ["//configs:lamlet_default.json"],
    outs = ["Lamlet_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/lamlet:lamlet) $$TMPDIR $(location //configs:lamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/lamlet:lamlet"],
)

cocotb_binary(
    name = "lamlet_default_exe",
    verilog_files = [":lamlet_default_verilog"],
    module_top = "Lamlet",
)

py_library(
    name = "test_lamlet_py",
    srcs = ["test_lamlet.py"],
    deps = ["//python/zamlet:zamlet"],
)

cocotb_test(
    name = "test_lamlet_default",
    binary = ":lamlet_default_exe",
    test_module = "zamlet.lamlet_test.test_lamlet",
    toplevel = "Lamlet",
    env = {
        "ZAMLET_TEST_CONFIG_FILENAME": "configs/lamlet_default.json",
    },
    data = ["//configs:lamlet_default.json"],
    py_deps = [":test_lamlet_py"],
)

test_suite(
    name = "all_tests",
    tests = [
        # TODO: Re-enable when fixed
        # ":test_lamlet_default",
    ],
)
