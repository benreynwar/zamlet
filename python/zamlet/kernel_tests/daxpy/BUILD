load("//bazel:defs.bzl", "riscv_kernel", "kernel_test")

DAXPY_COPTS = ["-DPREALLOCATE=1", "-ffast-math"]

riscv_kernel(
    name = "vec-daxpy",
    srcs = ["vec-daxpy_main.c"],
    common_srcs = ["//python/zamlet/kernel_tests/common:ara_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    copts = DAXPY_COPTS,
)

riscv_kernel(
    name = "vec-daxpy-small",
    srcs = ["vec-daxpy-small.c"],
    common_srcs = ["//python/zamlet/kernel_tests/common:ara_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    copts = DAXPY_COPTS,
)

kernel_test(
    name = "test_daxpy",
    kernel = ":vec-daxpy",
)

kernel_test(
    name = "test_daxpy_small",
    kernel = ":vec-daxpy-small",
)
