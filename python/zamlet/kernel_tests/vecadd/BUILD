load("//bazel:defs.bzl", "riscv_kernel", "kernel_test")

riscv_kernel(
    name = "vec-add",
    srcs = ["vec-add_main.c", "vec-add.S"],
    common_srcs = ["//python/zamlet/kernel_tests/common:standard_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
)

riscv_kernel(
    name = "vec-add-evict",
    srcs = ["vec-add-evict_main.c", "vec-add.S"],
    common_srcs = ["//python/zamlet/kernel_tests/common:standard_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
)

kernel_test(
    name = "test_vecadd",
    kernel = ":vec-add",
)

kernel_test(
    name = "test_vecadd_evict",
    kernel = ":vec-add-evict",
)
