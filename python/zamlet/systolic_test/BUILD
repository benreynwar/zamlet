load("//bazel:cocotb_rules.bzl", "chisel_module_tests_no_config")
load("//bazel:design/systolic/defs.bzl", "sum_stationary_top", "weight_stationary_top")
load("//bazel:defs.bzl", "json_file")

WEIGHT_STATIONARY_PARAMS = [
    {
        "top": weight_stationary_top(8, reset_group_size),
        "n": 8,
        "resetGroupSize": reset_group_size,
    },
    for reset_group_size in [0, 4]
]

[json_file(
    name = params["top"].lower() + "_params",
    data = {
        "n": params["n"],
        "resetGroupSize": params["resetGroupSize"],
    },
) for params in WEIGHT_STATIONARY_PARAMS]

[chisel_module_tests_no_config(
    generator = "//src/main/scala/zamlet/systolic:weightstationary",
    toplevel = params["top"],
    srcs = ["test_weight_stationary.py"],
    generator_args = [str(params["n"]), str(params["resetGroupSize"])],
    config = ":" + params["top"].lower() + "_params",
    test_modules = ["zamlet.systolic_test.test_weight_stationary"],
) for params in WEIGHT_STATIONARY_PARAMS]

SUM_STATIONARY_CONFIGS = [
    (False, True, False, False, 0),
    (False, True, False, True, 4),
    (False, False, False, False, 0),
    (False, True, True, False, 0),
    (True, True, False, False, 0),
    (True, True, True, False, 0),
]

SUM_STATIONARY_PARAMS = [
    {
        "top": sum_stationary_top(
            8,
            use_carry_save_accumulator,
            register_bc,
            register_de,
            split_c_drain,
            reset_group_size,
        ),
        "n": 8,
        "useCarrySaveAccumulator": use_carry_save_accumulator,
        "registerBC": register_bc,
        "registerDE": register_de,
        "splitCDrain": split_c_drain,
        "resetGroupSize": reset_group_size,
    }
    for use_carry_save_accumulator, register_bc, register_de, split_c_drain, reset_group_size in
    SUM_STATIONARY_CONFIGS
]

[json_file(
    name = params["top"].lower() + "_params",
    data = {
        "n": params["n"],
        "useCarrySaveAccumulator": params["useCarrySaveAccumulator"],
        "registerBC": params["registerBC"],
        "registerDE": params["registerDE"],
        "splitCDrain": params["splitCDrain"],
        "resetGroupSize": params["resetGroupSize"],
    },
) for params in SUM_STATIONARY_PARAMS]

[chisel_module_tests_no_config(
    generator = "//src/main/scala/zamlet/systolic:sumstationary",
    toplevel = params["top"],
    srcs = ["test_sum_stationary.py"],
    generator_args = [
        str(params["n"]),
        "true" if params["useCarrySaveAccumulator"] else "false",
        "true" if params["registerBC"] else "false",
        "true" if params["registerDE"] else "false",
        "true" if params["splitCDrain"] else "false",
        str(params["resetGroupSize"]),
    ],
    config = ":" + params["top"].lower() + "_params",
    test_modules = ["zamlet.systolic_test.test_sum_stationary"],
) for params in SUM_STATIONARY_PARAMS]

test_suite(
    name = "all_tests",
    tests = (
        [":" + params["top"].lower() + "_tests" for params in WEIGHT_STATIONARY_PARAMS] +
        [":" + params["top"].lower() + "_tests" for params in SUM_STATIONARY_PARAMS]
    ),
)
