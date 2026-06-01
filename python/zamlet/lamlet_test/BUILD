# Lamlet module tests

load("//bazel:cocotb_rules.bzl", "chisel_module_tests")

chisel_module_tests(
    generator = "//src/main/scala/zamlet/lamlet:lamlet",
    toplevel = "Lamlet",
    srcs = ["test_lamlet.py"],
    test_modules = ["zamlet.lamlet_test.test_lamlet"],
)

test_suite(
    name = "all_tests",
    tests = [
        # TODO: Re-enable when fixed
        # ":lamlet_tests",
    ],
)
