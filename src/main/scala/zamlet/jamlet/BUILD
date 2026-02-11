load("//bazel:chisel.bzl", "chisel_binary")

exports_files(
    [
        "KInstr.scala",
        "Packet.scala",
        "WitemEntry.scala",
    ],
    visibility = ["//visibility:public"],
)

filegroup(
    name = "jamlet_sources",
    srcs = glob(["*.scala"]),
    visibility = ["//visibility:public"],
)

JAMLET_DEPS = [
    "@maven//:org_typelevel_cats_core_2_13",
    "@maven//:org_typelevel_cats_kernel_2_13",
    "@maven//:io_circe_circe_core_2_13",
    "@maven//:io_circe_circe_generic_2_13",
    "@maven//:io_circe_circe_parser_2_13",
    "@maven//:com_chuusai_shapeless_2_13",
]

JAMLET_COMMON_SRCS = [
    "//src/main/scala/zamlet:ModuleGenerator.scala",
    "//src/main/scala/zamlet:LamletParams.scala",
    "//src/main/scala/zamlet/utils:utils_sources",
]

chisel_binary(
    name = "jamlet",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JamletMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "rfslice",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.RfSliceMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "networknode",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.NetworkNodeMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "witemmonitor",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.WitemMonitorMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "localexec",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.LocalExecMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "combinednetworknode",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.CombinedNetworkNodeMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "vectorrf",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.VectorRfMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "packetarbiter",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.PacketArbiterGenerator",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)
