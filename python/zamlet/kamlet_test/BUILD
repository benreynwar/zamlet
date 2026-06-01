# Kamlet module tests

load("//bazel:cocotb_rules.bzl", "chisel_module_tests")

chisel_module_tests(
    generator = "//src/main/scala/zamlet/kamlet:synchronizer",
    toplevel = "Synchronizer",
    srcs = ["test_synchronizer.py"],
    test_modules = ["zamlet.kamlet_test.test_synchronizer"],
    configs = [("default", "//configs:synchronizer_default.json")],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/kamlet:kamletmesh",
    toplevel = "KamletMesh",
    srcs = ["test_kamlet.py"],
    test_modules = ["zamlet.kamlet_test.test_kamlet"],
)

test_suite(
    name = "all_tests",
    tests = [
        # TODO: Re-enable when fixed
        # ":synchronizer_tests",
        ":kamletmesh_tests",
    ],
)
