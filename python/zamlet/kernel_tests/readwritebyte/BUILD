load("//bazel:defs.bzl", "riscv_kernel", "kernel_test")

riscv_kernel(
    name = "simple_vpu_test",
    srcs = ["simple_vpu_test.c", "minimal_crt.S"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    march = "rv64gc",
)

riscv_kernel(
    name = "should_fail",
    srcs = ["should_fail.c", "minimal_crt.S"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    march = "rv64gc",
)

riscv_kernel(
    name = "write_then_read_many_bytes",
    srcs = ["write_then_read_many_bytes.c", "minimal_crt.S"],
    linker_script = "//python/zamlet/kernel_tests/common:test.ld",
    march = "rv64gc",
)

kernel_test(
    name = "test_simple_vpu",
    kernel = ":simple_vpu_test",
)

kernel_test(
    name = "test_should_fail",
    kernel = ":should_fail",
    expected_failure = True,
)

kernel_test(
    name = "test_write_read",
    kernel = ":write_then_read_many_bytes",
)
