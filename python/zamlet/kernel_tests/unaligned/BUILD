load("//bazel:defs.bzl", "riscv_kernel", "kernel_test")

riscv_kernel(
    name = "unaligned",
    srcs = ["unaligned_main.c", "unaligned.S"],
    common_srcs = ["//python/zamlet/kernel_tests/common:standard_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
)

kernel_test(
    name = "test_unaligned",
    kernel = ":unaligned",
)
