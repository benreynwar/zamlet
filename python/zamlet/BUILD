# FMVPU Python package

load("@rules_python//python:defs.bzl", "py_library", "py_binary")


py_library(
    name = "zamlet",
    srcs = glob([
        "*.py",
        "bamlet/*.py",
        "amlet/*.py",
        "bamlet_kernels/*.py",
        "instructions/*.py",
    ]),
    deps = [],
    visibility = ["//visibility:public"],
    imports = [".."],
)

