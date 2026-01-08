load("//bazel:chisel.bzl", "chisel_binary")

chisel_binary(
    name = "ident_tracker",
    srcs = [
        "IdentTracker.scala",
        "//src/main/scala/zamlet:ModuleGenerator.scala",
        "//src/main/scala/zamlet:LamletParams.scala",
        "//src/main/scala/zamlet/kamlet:Synchronizer.scala",
        "//src/main/scala/zamlet/utils:utils_sources",
    ],
    main_class = "zamlet.lamlet.IdentTrackerMain",
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
