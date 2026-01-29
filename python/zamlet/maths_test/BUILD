# Maths module tests

load("//bazel:cocotb_rules.bzl", "cocotb_binary", "cocotb_test")

WALLACE_MULT_CONFIGS = [
    ("8x8", "WallaceMult8x8"),
    ("16x16", "WallaceMult16x16"),
    ("32x32", "WallaceMult32x32"),
    ("64x64", "WallaceMult64x64"),
]

[genrule(
    name = "wallace_mult_{}_verilog".format(size),
    srcs = ["//configs:{}.json".format(config)],
    outs = ["{}.sv".format(config)],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/maths:wallace_mult) $$TMPDIR $(location //configs:{}.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """.format(config),
    tools = ["//src/main/scala/zamlet/maths:wallace_mult"],
) for size, config in WALLACE_MULT_CONFIGS]

[cocotb_binary(
    name = "wallace_mult_{}_exe".format(size),
    verilog_files = [":wallace_mult_{}_verilog".format(size)],
    module_top = config,
) for size, config in WALLACE_MULT_CONFIGS]

py_library(
    name = "test_wallace_py",
    srcs = ["test_wallace.py"],
    deps = ["//python/zamlet:zamlet"],
)

[cocotb_test(
    name = "test_wallace_{}".format(size),
    binary = ":wallace_mult_{}_exe".format(size),
    test_module = "zamlet.maths_test.test_wallace",
    toplevel = config,
    env = {
        "ZAMLET_TEST_CONFIG_FILENAME": "configs/{}.json".format(config),
    },
    data = ["//configs:{}.json".format(config)],
    py_deps = [":test_wallace_py"],
) for size, config in WALLACE_MULT_CONFIGS]

test_suite(
    name = "all_tests",
    tests = [":test_wallace_{}".format(size) for size, _ in WALLACE_MULT_CONFIGS],
)
