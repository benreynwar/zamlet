load("//bazel:chisel.bzl", "chisel_binary")

filegroup(
    name = "utils_sources",
    srcs = glob(["*.scala"]),
    visibility = ["//visibility:public"],
)

UTILS_DEPS = [
    "@maven//:org_typelevel_cats_core_2_13",
    "@maven//:org_typelevel_cats_kernel_2_13",
    "@maven//:io_circe_circe_core_2_13",
    "@maven//:io_circe_circe_generic_2_13",
    "@maven//:io_circe_circe_parser_2_13",
    "@maven//:com_chuusai_shapeless_2_13",
]

UTILS_COMMON_SRCS = [
    "//src/main/scala/zamlet:ModuleGenerator.scala",
]

chisel_binary(
    name = "dropping_fifo",
    srcs = [":utils_sources"] + UTILS_COMMON_SRCS,
    main_class = "zamlet.utils.DroppingFifoMain",
    deps = UTILS_DEPS,
    visibility = ["//visibility:public"],
)
