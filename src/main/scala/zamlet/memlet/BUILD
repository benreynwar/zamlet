load("//bazel:chisel.bzl", "chisel_binary")

filegroup(
    name = "memlet_sources",
    srcs = glob(["*.scala"]),
    visibility = ["//visibility:public"],
)

MEMLET_DEPS = [
    "@maven//:org_typelevel_cats_core_2_13",
    "@maven//:org_typelevel_cats_kernel_2_13",
    "@maven//:io_circe_circe_core_2_13",
    "@maven//:io_circe_circe_generic_2_13",
    "@maven//:io_circe_circe_parser_2_13",
    "@maven//:com_chuusai_shapeless_2_13",
]

MEMLET_COMMON_SRCS = [
    "//src/main/scala/zamlet:ModuleGenerator.scala",
    "//src/main/scala/zamlet:ZamletParams.scala",
    "//src/main/scala/zamlet/utils:utils_sources",
    "//src/main/scala/zamlet/network:network_sources",
]

chisel_binary(
    name = "memlet",
    srcs = [":memlet_sources"] + MEMLET_COMMON_SRCS,
    main_class = "zamlet.memlet.MemletMain",
    deps = MEMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "gatherside",
    srcs = [":memlet_sources"] + MEMLET_COMMON_SRCS,
    main_class = "zamlet.memlet.GatherSideMain",
    deps = MEMLET_DEPS,
    visibility = ["//visibility:public"],
)
