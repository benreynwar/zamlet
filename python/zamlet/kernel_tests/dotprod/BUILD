load("//bazel:defs.bzl", "riscv_kernel", "kernel_test")

LOCAL_HDRS = glob(["*.h"])

riscv_kernel(
    name = "vec-dotprod",
    srcs = ["main.c", "dotproduct.c", "data.S"],
    common_srcs = ["//python/zamlet/kernel_tests/common:ara_runtime"],
    hdrs = ["//python/zamlet/kernel_tests/common:headers"] + LOCAL_HDRS,
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    copts = ["-DPREALLOCATE=1", "-ffast-math"],
)

kernel_test(
    name = "test_dotprod",
    kernel = ":vec-dotprod",
    timeout = "long",
)
