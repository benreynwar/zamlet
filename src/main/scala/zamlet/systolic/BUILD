load("//bazel:chisel.bzl", "chisel_binary")

SYSTOLIC_SRCS = [
    "SystolicArray.scala",
]

SYSTOLIC_DEPS = [
    "@maven//:com_chuusai_shapeless_2_13",
    "@maven//:io_circe_circe_core_2_13",
    "@maven//:io_circe_circe_generic_2_13",
    "@maven//:io_circe_circe_parser_2_13",
    "@maven//:org_typelevel_cats_core_2_13",
    "@maven//:org_typelevel_cats_kernel_2_13",
]

chisel_binary(
    name = "systolicarray",
    srcs = SYSTOLIC_SRCS + [
        "//src/main/scala/zamlet:zamlet_common_sources",
    ],
    main_class = "zamlet.systolic.SystolicArrayMain",
    deps = SYSTOLIC_DEPS,
    visibility = ["//visibility:public"],
)
