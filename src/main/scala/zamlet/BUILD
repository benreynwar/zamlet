load("//bazel:chisel.bzl", "chisel_library")

exports_files(
    ["ModuleGenerator.scala", "ZamletParams.scala", "Utils.scala"],
    visibility = ["//visibility:public"],
)

ZAMLET_COMMON_DEPS = [
    "@maven//:org_typelevel_cats_core_2_13",
    "@maven//:org_typelevel_cats_kernel_2_13",
    "@maven//:io_circe_circe_core_2_13",
    "@maven//:io_circe_circe_generic_2_13",
    "@maven//:io_circe_circe_parser_2_13",
    "@maven//:io_circe_circe_yaml_2_13",
    "@maven//:com_chuusai_shapeless_2_13",
]

chisel_library(
    name = "zamlet_common",
    srcs = [
        "ModuleGenerator.scala",
        "ZamletParams.scala",
        "Utils.scala",
    ],
    deps = ZAMLET_COMMON_DEPS,
    visibility = ["//visibility:public"],
)
