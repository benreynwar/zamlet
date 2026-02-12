load("//bazel:chisel.bzl", "chisel_binary")

# Lamlet sources (for use by other packages)
filegroup(
    name = "lamlet_sources",
    srcs = [
        "Lamlet.scala",
        "Zamlet.scala",
        "IssueUnit.scala",
        "IdentTracker.scala",
        "DispatchQueue.scala",
        "ScalarLoadQueue.scala",
        "VpuToScalarMem.scala",
        "ZamletVectorDecode.scala",
    ],
    visibility = ["//visibility:public"],
)

ZAMLET_DEPS = [
    "@maven//:org_typelevel_cats_core_2_13",
    "@maven//:org_typelevel_cats_kernel_2_13",
    "@maven//:io_circe_circe_core_2_13",
    "@maven//:io_circe_circe_generic_2_13",
    "@maven//:io_circe_circe_parser_2_13",
    "@maven//:com_chuusai_shapeless_2_13",
]

ZAMLET_COMMON_SRCS = [
    "//src/main/scala/zamlet:ModuleGenerator.scala",
    "//src/main/scala/zamlet:ZamletParams.scala",
    "//src/main/scala/zamlet/kamlet:Synchronizer.scala",
    "//src/main/scala/zamlet/utils:utils_sources",
    "//src/main/scala/zamlet/jamlet:KInstr.scala",
    "//src/main/scala/zamlet/jamlet:Packet.scala",
    "//src/main/scala/zamlet/jamlet:WitemEntry.scala",
]

chisel_binary(
    name = "ident_tracker",
    srcs = [
        "IdentTracker.scala",
        "DispatchQueue.scala",
    ] + ZAMLET_COMMON_SRCS,
    main_class = "zamlet.lamlet.IdentTrackerMain",
    deps = ZAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "issue_unit",
    srcs = [
        "IssueUnit.scala",
        "IdentTracker.scala",
        "ScalarLoadQueue.scala",
    ] + ZAMLET_COMMON_SRCS,
    main_class = "zamlet.lamlet.IssueUnitMain",
    deps = ZAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "lamlet",
    srcs = [
        "Lamlet.scala",
        "IssueUnit.scala",
        "IdentTracker.scala",
        "DispatchQueue.scala",
        "ScalarLoadQueue.scala",
        "VpuToScalarMem.scala",
    ] + ZAMLET_COMMON_SRCS,
    main_class = "zamlet.lamlet.LamletMain",
    deps = ZAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "zamlet",
    srcs = [
        "Zamlet.scala",
        "Lamlet.scala",
        "IssueUnit.scala",
        "IdentTracker.scala",
        "DispatchQueue.scala",
        "ScalarLoadQueue.scala",
        "VpuToScalarMem.scala",
        "//src/main/scala/zamlet/kamlet:kamlet_sources",
        "//src/main/scala/zamlet/jamlet:jamlet_sources",
    ] + ZAMLET_COMMON_SRCS,
    main_class = "zamlet.lamlet.ZamletMain",
    deps = ZAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "scalar_load_queue",
    srcs = [
        "ScalarLoadQueue.scala",
        "IdentTracker.scala",
    ] + ZAMLET_COMMON_SRCS,
    main_class = "zamlet.lamlet.ScalarLoadQueueMain",
    deps = ZAMLET_DEPS,
    visibility = ["//visibility:public"],
)
