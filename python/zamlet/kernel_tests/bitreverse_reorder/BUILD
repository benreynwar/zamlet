load("//bazel:defs.bzl", "riscv_kernel")

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
        "bitreverse_reorder64.S",
    ],
    common_srcs = ["//python/zamlet/kernel_tests/common:standard_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    visibility = ["//python/zamlet/kernel_tests:__subpackages__"],
)

# Tests for bitreverse use symbol_values injection, so they stay as pytest for now.
# Build targets only — no kernel_test macro here.
