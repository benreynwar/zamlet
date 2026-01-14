load("@rules_python//python:defs.bzl", "py_library")

package(default_visibility = ["//visibility:public"])

py_library(
    name = "cocotbext_axi",
    srcs = glob(["cocotbext/axi/**/*.py"]),
    imports = ["."],
    deps = ["@cocotb_bus//:cocotb_bus"],
)
