load("//bazel:chisel.bzl", "chisel_binary")

exports_files(
    [
        "KInstr.scala",
        "Moore.scala",
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
    "//src/main/scala/zamlet:zamlet_common_sources",
    "//src/main/scala/zamlet/utils:utils_sources",
    "//src/main/scala/zamlet/maths:maths_sources",
    "//src/main/scala/zamlet/network:network_sources",
]

JAMLET_MXU_SRCS = [
    "JamletMxu.scala",
    "JamletMxuCell.scala",
    "JamletMxuTestGrid.scala",
]

chisel_binary(
    name = "jamlet",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JamletMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jamlet_hard_macros",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JamletHardMacroMain",
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
    name = "sram",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.SramMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jce",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JceMain",
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
    name = "jamletalu",
    srcs = ["JamletALU.scala"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JamletAluMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jamletmxu",
    srcs = JAMLET_MXU_SRCS + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JamletMxuMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jamletmxucell",
    srcs = JAMLET_MXU_SRCS + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JamletMxuCellMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jamletmxutestgrid",
    srcs = JAMLET_MXU_SRCS + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JamletMxuTestGridMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jamletmxutestgrid_iverilog_wrapper",
    srcs = JAMLET_MXU_SRCS + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JamletMxuTestGridIverilogWrapperMain",
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
    name = "coordstoindexwithreg",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.CoordsToIndexWithRegMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "indextocoordswithreg",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.IndexToCoordsWithRegMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jte",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JteMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jteinitiator",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JteInitiatorMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jteinitiatorstage",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JteInitiatorStageMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jtehandler",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JteHandlerMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jtehandlerstage",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JteHandlerStageMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jtereceiver",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JteReceiverMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "jtestate",
    srcs = [":jamlet_sources"] + JAMLET_COMMON_SRCS,
    main_class = "zamlet.jamlet.JteStateMain",
    deps = JAMLET_DEPS,
    visibility = ["//visibility:public"],
)
