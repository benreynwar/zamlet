# FMVPU Python package

load("@rules_python//python:defs.bzl", "py_library", "py_binary")

test_suite(
    name = "cocotb_tests",
    tests = [
        "//python/zamlet/maths_test:all_tests",
        "//python/zamlet/utils_test:all_tests",
        "//python/zamlet/jamlet_test:all_tests",
        "//python/zamlet/kamlet_test:all_tests",
        # "//python/zamlet/lamlet_test:all_tests",  # empty - disabled
        "//python/zamlet/shuttle_test:all_tests",
    ],
)


py_library(
    name = "zamlet",
    srcs = glob([
        "*.py",
        "instructions/*.py",
        "jamlet/*.py",
        "kamlet/*.py",
        "lamlet/*.py",
        "transactions/*.py",
    ]),
    deps = [],
    visibility = ["//visibility:public"],
    imports = [".."],
)

