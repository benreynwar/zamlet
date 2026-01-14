load("@rules_scala//scala:scala.bzl", "scala_library")

package(default_visibility = ["//visibility:public"])

scala_library(
    name = "cde",
    srcs = glob(["cde/src/**/*.scala"]),
    deps = [],
    scalacopts = [
        "-language:reflectiveCalls",
        "-deprecation",
        "-feature",
    ],
)
