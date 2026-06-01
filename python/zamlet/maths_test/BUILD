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

genrule(
    name = "segmented_multiplier_64_verilog",
    outs = ["SegmentedMultiplier64x64.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/maths:segmented_multiplier) $$TMPDIR 64 8
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/maths:segmented_multiplier"],
)

cocotb_binary(
    name = "segmented_multiplier_64_exe",
    verilog_files = [":segmented_multiplier_64_verilog"],
    module_top = "SegmentedMultiplier64x64",
)

py_library(
    name = "test_segmented_multiplier_py",
    srcs = ["test_segmented_multiplier.py"],
    deps = ["//python/zamlet:zamlet"],
)

cocotb_test(
    name = "test_segmented_multiplier_64",
    binary = ":segmented_multiplier_64_exe",
    test_module = "zamlet.maths_test.test_segmented_multiplier",
    toplevel = "SegmentedMultiplier64x64",
    py_deps = [":test_segmented_multiplier_py"],
)

genrule(
    name = "segmented_prefix_adder_64_verilog",
    outs = ["SegmentedPrefixAdder64.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/maths:segmented_prefix_adder) $$TMPDIR 64
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/maths:segmented_prefix_adder"],
)

cocotb_binary(
    name = "segmented_prefix_adder_64_exe",
    verilog_files = [":segmented_prefix_adder_64_verilog"],
    module_top = "SegmentedPrefixAdder64",
)

py_library(
    name = "test_segmented_prefix_adder_py",
    srcs = ["test_segmented_prefix_adder.py"],
    deps = ["//python/zamlet:zamlet"],
)

cocotb_test(
    name = "test_segmented_prefix_adder_64",
    binary = ":segmented_prefix_adder_64_exe",
    test_module = "zamlet.maths_test.test_segmented_prefix_adder",
    toplevel = "SegmentedPrefixAdder64",
    py_deps = [":test_segmented_prefix_adder_py"],
)

test_suite(
    name = "all_tests",
    tests = [":test_wallace_{}".format(size) for size, _ in WALLACE_MULT_CONFIGS] + [
        ":test_segmented_prefix_adder_64",
        ":test_segmented_multiplier_64",
    ],
)
