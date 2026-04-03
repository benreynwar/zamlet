load("//bazel:defs.bzl", "riscv_kernel", "kernel_test")

CONDITIONAL_COPTS = ["-DPREALLOCATE=0", "-ffast-math"]
LOCAL_HDRS = glob(["*.h"])

riscv_kernel(
    name = "vec-conditional-tiny",
    srcs = ["vec-conditional-tiny_main.c", "vec-conditional-64.S"],
    common_srcs = ["//python/zamlet/kernel_tests/common:ara_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"] + LOCAL_HDRS,
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    copts = CONDITIONAL_COPTS,
)

riscv_kernel(
    name = "vec-conditional-small",
    srcs = ["vec-conditional-small_main.c", "vec-conditional.S"],
    common_srcs = ["//python/zamlet/kernel_tests/common:ara_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"] + LOCAL_HDRS,
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    copts = CONDITIONAL_COPTS,
)

riscv_kernel(
    name = "vec-conditional",
    srcs = ["vec-conditional_main.c", "vec-conditional.S"],
    common_srcs = ["//python/zamlet/kernel_tests/common:ara_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"] + LOCAL_HDRS,
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    copts = CONDITIONAL_COPTS,
)

kernel_test(
    name = "test_conditional_tiny",
    kernel = ":vec-conditional-tiny",
)

kernel_test(
    name = "test_conditional_small",
    kernel = ":vec-conditional-small",
)

kernel_test(
    name = "test_conditional",
    kernel = ":vec-conditional",
)
