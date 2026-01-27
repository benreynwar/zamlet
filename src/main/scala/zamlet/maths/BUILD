load("//bazel:chisel.bzl", "chisel_binary")

filegroup(
    name = "maths_sources",
    srcs = glob(["*.scala"]),
    visibility = ["//visibility:public"],
)

MATHS_DEPS = [
    "@maven//:org_typelevel_cats_core_2_13",
    "@maven//:org_typelevel_cats_kernel_2_13",
    "@maven//:io_circe_circe_core_2_13",
    "@maven//:io_circe_circe_generic_2_13",
    "@maven//:io_circe_circe_parser_2_13",
    "@maven//:com_chuusai_shapeless_2_13",
]

MATHS_COMMON_SRCS = [
    "//src/main/scala/zamlet:ModuleGenerator.scala",
]

chisel_binary(
    name = "wallace_tree_adder",
    srcs = [":maths_sources"] + MATHS_COMMON_SRCS,
    main_class = "zamlet.maths.WallaceTreeAdderMain",
    deps = MATHS_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "wallace_mult",
    srcs = [":maths_sources"] + MATHS_COMMON_SRCS,
    main_class = "zamlet.maths.WallaceMultMain",
    deps = MATHS_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "carry_select_adder",
    srcs = [":maths_sources"] + MATHS_COMMON_SRCS,
    main_class = "zamlet.maths.CarrySelectAdderMain",
    deps = MATHS_DEPS,
    visibility = ["//visibility:public"],
)
