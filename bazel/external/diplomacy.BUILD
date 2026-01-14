load("@rules_scala//scala:scala.bzl", "scala_library")

package(default_visibility = ["//visibility:public"])

scala_library(
    name = "diplomacy",
    srcs = glob(["diplomacy/src/**/*.scala"]),
    deps = [
        "@cde//:cde",
        "@maven//:org_chipsalliance_chisel_2_13",
        "@maven//:com_lihaoyi_sourcecode_2_13",
    ],
    scalacopts = [
        "-language:reflectiveCalls",
        "-deprecation",
        "-feature",
    ],
    plugins = [
        "@maven//:org_chipsalliance_chisel_plugin_2_13_16",
    ],
)
