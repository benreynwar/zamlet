load("//bazel:defs.bzl", "riscv_kernel", "kernel_test")

SGEMV_COPTS = ["-DPREALLOCATE=1", "-ffast-math"]
LOCAL_HDRS = glob(["*.h"])

riscv_kernel(
    name = "vec-sgemv",
    srcs = ["vec-sgemv_main.c", "vec-sgemv.S"],
    common_srcs = ["//python/zamlet/kernel_tests/common:ara_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"] + LOCAL_HDRS,
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    copts = SGEMV_COPTS,
)

riscv_kernel(
    name = "vec-sgemv-large",
    srcs = ["vec-sgemv-large_main.c", "vec-sgemv.S"],
    common_srcs = ["//python/zamlet/kernel_tests/common:ara_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"] + LOCAL_HDRS,
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    copts = SGEMV_COPTS,
)

riscv_kernel(
    name = "vec-sgemv-64x64",
    srcs = ["vec-sgemv-64x64_main.c", "vec-sgemv.S"],
    common_srcs = ["//python/zamlet/kernel_tests/common:ara_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"] + LOCAL_HDRS,
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    copts = SGEMV_COPTS,
)

kernel_test(
    name = "test_sgemv",
    kernel = ":vec-sgemv",
)

kernel_test(
    name = "test_sgemv_large",
    kernel = ":vec-sgemv-large",
)

kernel_test(
    name = "test_sgemv_64x64",
    kernel = ":vec-sgemv-64x64",
)
