load("//bazel:chisel.bzl", "chisel_binary")

SYSTOLIC_DEPS = [
    "@maven//:com_chuusai_shapeless_2_13",
    "@maven//:io_circe_circe_core_2_13",
    "@maven//:io_circe_circe_generic_2_13",
    "@maven//:io_circe_circe_parser_2_13",
    "@maven//:org_typelevel_cats_core_2_13",
    "@maven//:org_typelevel_cats_kernel_2_13",
]

SUM_STATIONARY_SRCS = [
    "SumStationary.scala",
    "//src/main/scala/zamlet:zamlet_common_sources",
    "//src/main/scala/zamlet/maths:maths_sources",
    "//src/main/scala/zamlet/utils:utils_sources",
]

chisel_binary(
    name = "weightstationary",
    srcs = [
        "WeightStationary.scala",
        "//src/main/scala/zamlet:zamlet_common_sources",
        "//src/main/scala/zamlet/utils:utils_sources",
    ],
    main_class = "zamlet.systolic.WeightStationaryMain",
    deps = SYSTOLIC_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "sumstationary",
    srcs = SUM_STATIONARY_SRCS,
    main_class = "zamlet.systolic.SumStationaryMain",
    deps = SYSTOLIC_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "sumstationary_iverilog_wrapper",
    srcs = SUM_STATIONARY_SRCS,
    main_class = "zamlet.systolic.SumStationaryIverilogWrapperMain",
    deps = SYSTOLIC_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "weightstationary_iverilog_wrapper",
    srcs = [
        "WeightStationary.scala",
        "//src/main/scala/zamlet:zamlet_common_sources",
        "//src/main/scala/zamlet/utils:utils_sources",
    ],
    main_class = "zamlet.systolic.WeightStationaryIverilogWrapperMain",
    deps = SYSTOLIC_DEPS,
    visibility = ["//visibility:public"],
)
