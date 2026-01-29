# Utils module tests

load("//bazel:cocotb_rules.bzl", "cocotb_binary", "cocotb_test")

DROPPING_FIFO_CONFIGS = [
    ("default", "dropping_fifo_default"),
]

[genrule(
    name = "dropping_fifo_{}_verilog".format(name),
    srcs = ["//configs:{}.json".format(config)],
    outs = ["DroppingFifo_{}.sv".format(name)],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/utils:dropping_fifo) $$TMPDIR $(location //configs:{}.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """.format(config),
    tools = ["//src/main/scala/zamlet/utils:dropping_fifo"],
) for name, config in DROPPING_FIFO_CONFIGS]

[cocotb_binary(
    name = "dropping_fifo_{}_exe".format(name),
    verilog_files = [":dropping_fifo_{}_verilog".format(name)],
    module_top = "DroppingFifo",
) for name, config in DROPPING_FIFO_CONFIGS]

py_library(
    name = "test_dropping_fifo_py",
    srcs = ["test_dropping_fifo.py"],
    deps = ["//python/zamlet:zamlet"],
)

[cocotb_test(
    name = "test_dropping_fifo_{}".format(name),
    binary = ":dropping_fifo_{}_exe".format(name),
    test_module = "zamlet.utils_test.test_dropping_fifo",
    toplevel = "DroppingFifo",
    env = {
        "ZAMLET_TEST_CONFIG_FILENAME": "configs/{}.json".format(config),
    },
    data = ["//configs:{}.json".format(config)],
    py_deps = [":test_dropping_fifo_py"],
) for name, config in DROPPING_FIFO_CONFIGS]

test_suite(
    name = "all_tests",
    tests = [":test_dropping_fifo_{}".format(name) for name, _ in DROPPING_FIFO_CONFIGS],
)
