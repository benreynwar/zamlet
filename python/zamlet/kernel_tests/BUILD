exports_files(["run_kernel_test.py"])

test_suite(
    name = "all_tests",
    tests = [":tests_a", ":tests_b", ":tests_c", ":tests_fft"],
)

test_suite(
    name = "tests_a",
    tests = [
        "//python/zamlet/kernel_tests/conditional:test_conditional",
        "//python/zamlet/kernel_tests/conditional:test_conditional_small",
        "//python/zamlet/kernel_tests/conditional:test_conditional_tiny",
        "//python/zamlet/kernel_tests/daxpy:test_daxpy",
        "//python/zamlet/kernel_tests/daxpy:test_daxpy_small",
    ],
)

test_suite(
    name = "tests_c",
    tests = [
        "//python/zamlet/kernel_tests/dotprod:test_dotprod",
        "//python/zamlet/kernel_tests/readwritebyte:test_should_fail",
        "//python/zamlet/kernel_tests/readwritebyte:test_simple_vpu",
        "//python/zamlet/kernel_tests/readwritebyte:test_write_read",
    ],
)

test_suite(
    name = "tests_b",
    tests = [
        "//python/zamlet/kernel_tests/sgemv:test_sgemv",
        "//python/zamlet/kernel_tests/sgemv:test_sgemv_64x64",
        "//python/zamlet/kernel_tests/sgemv:test_sgemv_large",
        "//python/zamlet/kernel_tests/unaligned:test_unaligned",
        "//python/zamlet/kernel_tests/vecadd:test_vecadd",
        "//python/zamlet/kernel_tests/vecadd:test_vecadd_evict",
        "//python/zamlet/kernel_tests/vid:test_vid",
    ],
)

test_suite(
    name = "tests_fft",
    tests = [
        "//python/zamlet/kernel_tests/fft:all_fft_tests",
    ],
)
