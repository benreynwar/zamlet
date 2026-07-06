# Maths module tests

load("//bazel:cocotb_rules.bzl", "chisel_module_tests", "cocotb_binary", "cocotb_test")
load("//bazel:defs.bzl", "json_file")

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
    config = "//configs:{}.json".format(config),
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

SEGMENTED_PREFIX_ADDER_REGISTER_CONFIGS = [
    (register_input, register_middle, register_output)
    for register_input in (False, True)
    for register_middle in (False, True)
    for register_output in (False, True)
]

[json_file(
    name = "segmented_prefix_adder_64_{}{}{}_params".format(
        "i" if register_input else "n",
        "m" if register_middle else "n",
        "o" if register_output else "n",
    ),
    data = {
        "width": 64,
        "registerInput": register_input,
        "registerMiddle": register_middle,
        "registerOutput": register_output,
    },
) for register_input, register_middle, register_output in SEGMENTED_PREFIX_ADDER_REGISTER_CONFIGS]

chisel_module_tests(
    generator = "//src/main/scala/zamlet/maths:segmented_prefix_adder",
    toplevel = "SegmentedPrefixAdder64",
    srcs = ["test_segmented_prefix_adder.py"],
    test_modules = ["zamlet.maths_test.test_segmented_prefix_adder"],
    configs = [
        (
            "{}{}{}".format(
                "i" if register_input else "n",
                "m" if register_middle else "n",
                "o" if register_output else "n",
            ),
            ":segmented_prefix_adder_64_{}{}{}_params".format(
                "i" if register_input else "n",
                "m" if register_middle else "n",
                "o" if register_output else "n",
            ),
        )
        for register_input, register_middle, register_output in SEGMENTED_PREFIX_ADDER_REGISTER_CONFIGS
    ],
)

test_suite(
    name = "all_tests",
    tests = [":test_wallace_{}".format(size) for size, _ in WALLACE_MULT_CONFIGS] + [
        ":segmentedprefixadder64_tests",
        ":test_segmented_multiplier_64",
    ],
)
