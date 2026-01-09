load("//bazel:chisel.bzl", "chisel_binary")

LAMLET_DEPS = [
    "@maven//:org_typelevel_cats_core_2_13",
    "@maven//:org_typelevel_cats_kernel_2_13",
    "@maven//:io_circe_circe_core_2_13",
    "@maven//:io_circe_circe_generic_2_13",
    "@maven//:io_circe_circe_parser_2_13",
    "@maven//:com_chuusai_shapeless_2_13",
]

LAMLET_COMMON_SRCS = [
    "//src/main/scala/zamlet:ModuleGenerator.scala",
    "//src/main/scala/zamlet:LamletParams.scala",
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
    ] + LAMLET_COMMON_SRCS,
    main_class = "zamlet.lamlet.IdentTrackerMain",
    deps = LAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "issue_unit",
    srcs = [
        "IssueUnit.scala",
        "IdentTracker.scala",
    ] + LAMLET_COMMON_SRCS,
    main_class = "zamlet.lamlet.IssueUnitMain",
    deps = LAMLET_DEPS,
    visibility = ["//visibility:public"],
)

chisel_binary(
    name = "lamlet",
    srcs = [
        "Lamlet.scala",
        "IssueUnit.scala",
        "IdentTracker.scala",
        "DispatchQueue.scala",
    ] + LAMLET_COMMON_SRCS,
    main_class = "zamlet.lamlet.LamletMain",
    deps = LAMLET_DEPS,
    visibility = ["//visibility:public"],
)
