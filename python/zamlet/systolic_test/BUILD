load("//bazel:cocotb_rules.bzl", "chisel_module_tests_no_config")
load("//bazel:defs.bzl", "json_file")

SYSTOLIC_ARRAY_PARAMS = [
    {
        "name": "systolic_array_8x8",
        "top": "SystolicArray",
        "n": 8,
    },
]

[json_file(
    name = params["name"] + "_params",
    data = {
        "n": params["n"],
    },
) for params in SYSTOLIC_ARRAY_PARAMS]

[chisel_module_tests_no_config(
    generator = "//src/main/scala/zamlet/systolic:systolicarray",
    toplevel = params["top"],
    srcs = ["test_systolic_array.py"],
    generator_args = [str(params["n"])],
    config = ":" + params["name"] + "_params",
    test_modules = ["zamlet.systolic_test.test_systolic_array"],
) for params in SYSTOLIC_ARRAY_PARAMS]

test_suite(
    name = "all_tests",
    tests = [":" + params["top"].lower() + "_tests" for params in SYSTOLIC_ARRAY_PARAMS],
)
