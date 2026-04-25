load("//bazel:defs.bzl", "riscv_kernel", "kernel_test")

riscv_kernel(
    name = "trap-delivery",
    srcs = ["trap_delivery.c"],
    common_srcs = ["//python/zamlet/kernel_tests/common:standard_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
)

riscv_kernel(
    name = "trap-delivery-unhandled",
    srcs = ["trap_delivery_unhandled.c"],
    common_srcs = ["//python/zamlet/kernel_tests/common:standard_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
)

kernel_test(
    name = "test_trap_delivery",
    kernel = ":trap-delivery",
    max_cycles = 200000,
)

kernel_test(
    name = "test_trap_delivery_unhandled",
    kernel = ":trap-delivery-unhandled",
    expected_failure = True,
    max_cycles = 200000,
)
