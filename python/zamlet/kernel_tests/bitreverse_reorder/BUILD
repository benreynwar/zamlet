load("//bazel:defs.bzl", "riscv_kernel", "kernel_test")

exports_files([
    "compute_indices.c",
    "bitreverse.S",
    "bitreverse_reorder.S",
    "bitreverse_reorder64.S",
])

riscv_kernel(
    name = "bitreverse-reorder",
    srcs = [
        "bitreverse_main.c",
        "compute_indices.c",
        "bitreverse.S",
        "bitreverse_reorder.S",
    ],
    common_srcs = ["//python/zamlet/kernel_tests/common:standard_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    visibility = ["//python/zamlet/kernel_tests:__subpackages__"],
)

riscv_kernel(
    name = "bitreverse-reorder64",
    srcs = [
        "bitreverse_main64.c",
        "compute_indices.c",
        "bitreverse.S",
        "bitreverse_reorder64.c",
    ],
    common_srcs = ["//python/zamlet/kernel_tests/common:standard_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    visibility = ["//python/zamlet/kernel_tests:__subpackages__"],
)

riscv_kernel(
    name = "bitreverse-repro",
    srcs = ["bitreverse_repro.c"],
    common_srcs = ["//python/zamlet/kernel_tests/common:standard_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    visibility = ["//python/zamlet/kernel_tests:__subpackages__"],
)

kernel_test(
    name = "test_bitreverse_repro",
    kernel = ":bitreverse-repro",
    symbol_values = {"n_bits": 2, "input_val": 0},
)

[kernel_test(
    name = "test_bitreverse_reorder64_n%d" % n,
    kernel = ":bitreverse-reorder64",
    symbol_values = {"n": n},
) for n in [8, 16, 32, 64]]
