load("//bazel:chisel.bzl", "chisel_binary")

filegroup(
    name = "network_sources",
    srcs = glob(["*.scala"]),
    visibility = ["//visibility:public"],
)

NETWORK_DEPS = [
    "@maven//:org_typelevel_cats_core_2_13",
    "@maven//:org_typelevel_cats_kernel_2_13",
    "@maven//:io_circe_circe_core_2_13",
    "@maven//:io_circe_circe_generic_2_13",
    "@maven//:io_circe_circe_parser_2_13",
    "@maven//:com_chuusai_shapeless_2_13",
]

NETWORK_COMMON_SRCS = [
    "//src/main/scala/zamlet:ModuleGenerator.scala",
    "//src/main/scala/zamlet:ZamletParams.scala",
    "//src/main/scala/zamlet/utils:utils_sources",
]

chisel_binary(
    name = "combinednetworknode",
    srcs = [":network_sources"] + NETWORK_COMMON_SRCS,
    main_class = "zamlet.network.CombinedNetworkNodeMain",
    deps = NETWORK_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "networknode",
    srcs = [":network_sources"] + NETWORK_COMMON_SRCS,
    main_class = "zamlet.network.NetworkNodeMain",
    deps = NETWORK_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "packetswitch",
    srcs = [":network_sources"] + NETWORK_COMMON_SRCS,
    main_class = "zamlet.network.PacketSwitchMain",
    deps = NETWORK_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "packetarbiter",
    srcs = [":network_sources"] + NETWORK_COMMON_SRCS,
    main_class = "zamlet.network.PacketArbiterGenerator",
    deps = NETWORK_DEPS,
    visibility = ["//visibility:public"],
)
