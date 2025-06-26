# Chisel compilation rules for FMVPU
# Adapted from RegFileStudy: https://github.com/Pinata-Consulting/RegFileStudy
# buildifier: disable=module-docstring
load("@rules_scala//scala:scala.bzl", "scala_binary", "scala_library")

def chisel_binary(name, **kwargs):
    scala_binary(
        name = name,
        deps = [
            "@maven//:org_chipsalliance_chisel_2_13",
        ] + kwargs.pop("deps", []),
        scalacopts = [
            "-language:reflectiveCalls",
            "-deprecation",
            "-feature",
            "-Xcheckinit",
        ] + kwargs.pop("scalacopts", []),
        plugins = [
            "@maven//:org_chipsalliance_chisel_plugin_2_13_16",
        ],
        **kwargs
    )

def chisel_library(name, **kwargs):
    scala_library(
        name = name,
        deps = [
            "@maven//:org_chipsalliance_chisel_2_13",
        ] + kwargs.pop("deps", []),
        scalacopts = [
            "-language:reflectiveCalls",
            "-deprecation",
            "-feature",
            "-Xcheckinit",
        ] + kwargs.pop("scalacopts", []),
        plugins = [
            "@maven//:org_chipsalliance_chisel_plugin_2_13_16",
        ],
        **kwargs
    )