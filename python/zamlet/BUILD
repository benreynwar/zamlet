# FMVPU Python package

load("@rules_python//python:defs.bzl", "py_library", "py_binary")

test_suite(
    name = "all_tests",
    tests = [
        "//python/zamlet/tests:all_tests",
        "//python/zamlet/kernel_tests:all_tests",
    ],
)

test_suite(
    name = "cocotb_tests",
    tests = [
        "//python/zamlet/maths_test:all_tests",
        "//python/zamlet/utils_test:all_tests",
        "//python/zamlet/jamlet_test:all_tests",
        "//python/zamlet/kamlet_test:all_tests",
        # "//python/zamlet/lamlet_test:all_tests",  # empty - disabled
        "//python/zamlet/shuttle_test:all_tests",
        "//python/zamlet/memlet_test:all_tests",
    ],
)


test_suite(
    name = "kernel_tests",
    tests = [
        "//python/zamlet/kernel_tests/vecadd:test_vecadd",
        "//python/zamlet/kernel_tests/vid:test_vid",
        "//python/zamlet/kernel_tests/unaligned:test_unaligned",
        "//python/zamlet/kernel_tests/readwritebyte:test_simple_vpu",
        "//python/zamlet/kernel_tests/readwritebyte:test_should_fail",
        "//python/zamlet/kernel_tests/readwritebyte:test_write_read",
        "//python/zamlet/kernel_tests/sgemv:test_sgemv",
        "//python/zamlet/kernel_tests/daxpy:test_daxpy",
        "//python/zamlet/kernel_tests/dotprod:test_dotprod",
        "//python/zamlet/kernel_tests/conditional:test_conditional_tiny",
        "//python/zamlet/kernel_tests/conditional:test_conditional_small",
        "//python/zamlet/kernel_tests/conditional:test_conditional",
    ],
)

py_library(
    name = "zamlet",
    srcs = glob([
        "*.py",
        "cocotb/*.py",
        "instructions/*.py",
        "jamlet/*.py",
        "kamlet/*.py",
        "lamlet/*.py",
        "oamlet/*.py",
        "transactions/*.py",
        "analysis/*.py",
    ]),
    deps = [],
    visibility = ["//visibility:public"],
    imports = [".."],
)

