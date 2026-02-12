load("//bazel:chisel.bzl", "chisel_binary", "chisel_library")

exports_files(
    ["Synchronizer.scala"],
    visibility = ["//visibility:public"],
)

# Kamlet sources (for use by other packages)
filegroup(
    name = "kamlet_sources",
    srcs = [
        "InstrQueue.scala",
        "InstrExecutor.scala",
        "Kamlet.scala",
        "KamletMesh.scala",
        "Synchronizer.scala",
    ],
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "synchronizer",
    srcs = [
        "Synchronizer.scala",
        "//src/main/scala/zamlet:ZamletParams.scala",
        "//src/main/scala/zamlet:ModuleGenerator.scala",
        "//src/main/scala/zamlet/utils:utils_sources",
    ],
    main_class = "zamlet.kamlet.SynchronizerMain",
    deps = [
        "@maven//:org_typelevel_cats_core_2_13",
        "@maven//:org_typelevel_cats_kernel_2_13",
        "@maven//:io_circe_circe_core_2_13",
        "@maven//:io_circe_circe_generic_2_13",
        "@maven//:io_circe_circe_parser_2_13",
        "@maven//:com_chuusai_shapeless_2_13",
    ],
    visibility = ["//visibility:public"],
)

chisel_library(
    name = "kamlet_lib",
    srcs = [
        ":kamlet_sources",
        "//src/main/scala/zamlet:ZamletParams.scala",
        "//src/main/scala/zamlet:ModuleGenerator.scala",
        "//src/main/scala/zamlet/jamlet:jamlet_sources",
        "//src/main/scala/zamlet/utils:utils_sources",
    ],
    deps = [
        "@maven//:org_typelevel_cats_core_2_13",
        "@maven//:org_typelevel_cats_kernel_2_13",
        "@maven//:io_circe_circe_core_2_13",
        "@maven//:io_circe_circe_generic_2_13",
        "@maven//:io_circe_circe_parser_2_13",
        "@maven//:com_chuusai_shapeless_2_13",
    ],
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "kamlet",
    srcs = [
        ":kamlet_sources",
        "//src/main/scala/zamlet:ZamletParams.scala",
        "//src/main/scala/zamlet:ModuleGenerator.scala",
        "//src/main/scala/zamlet/jamlet:jamlet_sources",
        "//src/main/scala/zamlet/utils:utils_sources",
    ],
    main_class = "zamlet.kamlet.KamletMain",
    deps = [
        "@maven//:org_typelevel_cats_core_2_13",
        "@maven//:org_typelevel_cats_kernel_2_13",
        "@maven//:io_circe_circe_core_2_13",
        "@maven//:io_circe_circe_generic_2_13",
        "@maven//:io_circe_circe_parser_2_13",
        "@maven//:com_chuusai_shapeless_2_13",
    ],
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "kamletmesh",
    srcs = [
        ":kamlet_sources",
        "//src/main/scala/zamlet:ZamletParams.scala",
        "//src/main/scala/zamlet:ModuleGenerator.scala",
        "//src/main/scala/zamlet/jamlet:jamlet_sources",
        "//src/main/scala/zamlet/utils:utils_sources",
    ],
    main_class = "zamlet.kamlet.KamletMeshMain",
    deps = [
        "@maven//:org_typelevel_cats_core_2_13",
        "@maven//:org_typelevel_cats_kernel_2_13",
        "@maven//:io_circe_circe_core_2_13",
        "@maven//:io_circe_circe_generic_2_13",
        "@maven//:io_circe_circe_parser_2_13",
        "@maven//:com_chuusai_shapeless_2_13",
    ],
    visibility = ["//visibility:public"],
)
