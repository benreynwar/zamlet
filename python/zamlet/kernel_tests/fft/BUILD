load("//bazel:defs.bzl", "riscv_kernel", "kernel_test")

riscv_kernel(
    name = "vec-fft8",
    srcs = [
        "vec-fft8.c",
        "//python/zamlet/kernel_tests/bitreverse_reorder:compute_indices.c",
        "//python/zamlet/kernel_tests/bitreverse_reorder:bitreverse.S",
        "//python/zamlet/kernel_tests/bitreverse_reorder:bitreverse_reorder64.c",
    ],
    common_srcs = ["//python/zamlet/kernel_tests/common:ara_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    copts = ["-DPREALLOCATE=1", "-ffast-math"],
)

kernel_test(
    name = "test_fft",
    kernel = ":vec-fft8",
)
