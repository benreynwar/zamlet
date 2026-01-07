# Scala source files for FMVPU

load("//bazel:chisel.bzl", "chisel_binary")

filegroup(
    name = "scala_sources",
    srcs = glob(["main/scala/**/*.scala"]),
    visibility = ["//visibility:public"],
)

filegroup(
    name = "tile_sources",
    srcs = glob(["main/scala/zamlet/tile/*.scala"]),
    visibility = ["//visibility:public"],
)

# Shared Verilog generator for all tests
chisel_binary(
    name = "verilog_generator",
    srcs = [":scala_sources"],
    main_class = "zamlet.Main",
    deps = [
        "@maven//:org_typelevel_cats_core_2_13",
        "@maven//:org_typelevel_cats_kernel_2_13",
        "@maven//:io_circe_circe_core_2_13",
        "@maven//:io_circe_circe_generic_2_13",
        "@maven//:io_circe_circe_parser_2_13",
        "@maven//:io_circe_circe_yaml_2_13",
        "@maven//:com_chuusai_shapeless_2_13",
    ],
    visibility = ["//visibility:public"],
)

# Shuttle tile generator - generates standalone Shuttle system with exposed AXI ports
chisel_binary(
    name = "shuttle_tile_generator",
    srcs = [":tile_sources"],
    main_class = "zamlet.tile.Main",
    deps = [
        "@shuttle//:shuttle",
        "@rocket_chip//:rocket_chip",
        "@cde//:cde",
        "@diplomacy//:diplomacy",
        "@maven//:com_lihaoyi_sourcecode_2_13",
    ],
    visibility = ["//visibility:public"],
)