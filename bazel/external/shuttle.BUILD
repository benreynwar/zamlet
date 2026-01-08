load("@rules_scala//scala:scala.bzl", "scala_library")

package(default_visibility = ["//visibility:public"])

scala_library(
    name = "shuttle",
    srcs = glob(["src/main/scala/**/*.scala"]),
    deps = [
        "@rocket_chip//:rocket_chip",
        "@cde//:cde",
        "@diplomacy//:diplomacy",
        "@hardfloat//:hardfloat",
        "@maven//:org_chipsalliance_chisel_2_13",
        "@maven//:com_lihaoyi_sourcecode_2_13",
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
