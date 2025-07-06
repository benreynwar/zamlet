# FMVPU Python package

load("@rules_python//python:defs.bzl", "py_library")

exports_files(["params.json"], visibility = ["//visibility:public"])

py_library(
    name = "fmvpu",
    srcs = glob(["*.py"]),
    data = glob(["*.json"]),
    visibility = ["//visibility:public"],
    imports = [".."],
)