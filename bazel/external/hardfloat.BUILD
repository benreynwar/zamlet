load("@rules_scala//scala:scala.bzl", "scala_library")

package(default_visibility = ["//visibility:public"])

scala_library(
    name = "hardfloat",
    srcs = glob(["hardfloat/src/main/scala/**/*.scala"]),
    deps = [
        "@maven//:org_chipsalliance_chisel_2_13",
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
