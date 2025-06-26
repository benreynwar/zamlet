# FMVPU Python package

load("@rules_python//python:defs.bzl", "py_library")
load("//:chisel.bzl", "chisel_binary")

exports_files(["params.json"], visibility = ["//visibility:public"])

py_library(
    name = "fmvpu",
    srcs = glob(["*.py"]),
    data = glob(["*.json"]),
    visibility = ["//visibility:public"],
    imports = [".."],
)

# Shared Verilog generator for all tests
chisel_binary(
    name = "verilog_generator",
    srcs = ["//src:scala_sources"],
    main_class = "fmvpu.Main",
    deps = [
        "@maven//:org_typelevel_cats_core_2_13",
        "@maven//:org_typelevel_cats_kernel_2_13",
        "@maven//:io_circe_circe_core_2_13",
        "@maven//:io_circe_circe_generic_2_13",
        "@maven//:io_circe_circe_parser_2_13",
        "@maven//:io_circe_circe_yaml_2_13",
        "@maven//:com_chuusai_shapeless_2_13",
    ],
    visibility = ["//python/fmvpu:__subpackages__"],
)