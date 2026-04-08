load("@rules_python//python:defs.bzl", "py_library", "py_test")

py_library(
    name = "test_utils",
    srcs = ["test_utils.py"],
    deps = ["//python/zamlet:zamlet"],
    imports = ["../.."],
)

FAST_TESTS = [
    "test_conditional_kamlet",
    "test_reg_gather",
    "test_reg_mem_mapping",
    "test_synchronization",
]

SLOW_TESTS = [
    "test_indexed_load",
    "test_indexed_store",
    "test_ordered_indexed_load",
    "test_ordered_indexed_store",
    "test_reduction",
    "test_strided_load",
    "test_strided_store",
    "test_unaligned",
]

TEST_FILES = FAST_TESTS + SLOW_TESTS

[py_test(
    name = t,
    srcs = ["run_pytest.py", t + ".py"],
    main = "run_pytest.py",
    deps = [
        ":test_utils",
        "//python/zamlet:zamlet",
    ],
    imports = ["../.."],
    args = ["python/zamlet/tests/" + t + ".py", "-v"],
    timeout = "moderate",
) for t in FAST_TESTS]

[py_test(
    name = t,
    srcs = ["run_pytest.py", t + ".py"],
    main = "run_pytest.py",
    deps = [
        ":test_utils",
        "//python/zamlet:zamlet",
    ],
    imports = ["../.."],
    args = ["python/zamlet/tests/" + t + ".py", "-v"],
    timeout = "moderate",
    shard_count = 4,
) for t in SLOW_TESTS]

py_test(
    name = "test_memlet_model",
    srcs = ["run_pytest.py", "test_memlet_model.py"],
    main = "run_pytest.py",
    deps = [
        ":test_utils",
        "//python/zamlet:zamlet",
        "//python/zamlet/memlet_test:test_cocotb_memlet_py",
    ],
    imports = ["../.."],
    args = ["python/zamlet/tests/test_memlet_model.py", "-v"],
    timeout = "moderate",
)

test_suite(
    name = "all_tests",
    tests = TEST_FILES + ["test_memlet_model"],
)
