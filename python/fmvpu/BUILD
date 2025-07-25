# FMVPU Python package

load("@rules_python//python:defs.bzl", "py_library")


py_library(
    name = "fmvpu",
    srcs = glob(["*.py", "lane/*.py", "lane_array/*.py", "bamlet/*.py", "amlet/*.py", "bamlet_kernels/*.py"]),
    deps = [],
    visibility = ["//visibility:public"],
    imports = [".."],
)
