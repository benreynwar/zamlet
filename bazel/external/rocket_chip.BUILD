load("@rules_scala//scala:scala.bzl", "scala_library")

package(default_visibility = ["//visibility:public"])

# RocketChip macros library (uses scala-reflect)
scala_library(
    name = "macros",
    srcs = glob(["macros/src/main/scala/**/*.scala"]),
    deps = [
        "@maven//:org_scala_lang_scala_reflect_2_13_16",
    ],
    scalacopts = [
        "-language:reflectiveCalls",
        "-deprecation",
        "-feature",
    ],
)

# Main RocketChip library
scala_library(
    name = "rocket_chip",
    srcs = glob(["src/main/scala/**/*.scala"]),
    resources = glob(["src/main/resources/**"]),
    deps = [
        ":macros",
        "@cde//:cde",
        "@diplomacy//:diplomacy",
        "@hardfloat//:hardfloat",
        "@maven//:org_chipsalliance_chisel_2_13",
        "@maven//:com_lihaoyi_mainargs_2_13",
        "@maven//:org_json4s_json4s_jackson_2_13",
        "@maven//:org_json4s_json4s_jackson_core_2_13",
        "@maven//:org_json4s_json4s_core_2_13",
        "@maven//:org_json4s_json4s_ast_2_13",
        "@maven//:com_lihaoyi_sourcecode_2_13",
        "@maven//:com_lihaoyi_os_lib_2_13",
        "@maven//:com_lihaoyi_geny_2_13",
        "@maven//:org_scala_lang_modules_scala_collection_compat_2_13",
    ],
    scalacopts = [
        "-language:reflectiveCalls",
        "-deprecation",
        "-feature",
        "-Xcheckinit",
    ],
    plugins = [
        "@maven//:org_chipsalliance_chisel_plugin_2_13_16",
    ],
)
