load("//bazel:cocotb_rules.bzl", "cvc_cocotb_test")

py_library(
    name = "smoke_test_py",
    srcs = ["test_smoke.py"],
    deps = ["//python/zamlet:zamlet"],
)

cvc_cocotb_test(
    name = "smoke_test",
    verilog_files = ["smoke.v"],
    test_module = "zamlet.cvc_test.test_smoke",
    toplevel = "cvc_smoke",
    py_deps = [":smoke_test_py"],
)
