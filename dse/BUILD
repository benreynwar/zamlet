# FMVPU NetworkNode Design Space Exploration
# Adapted from RegFileStudy: https://github.com/Pinata-Consulting/RegFileStudy

load("@bazel-orfs//:openroad.bzl", "orfs_flow", "orfs_run")
load("@bazel-orfs//:write_binary.bzl", "write_binary")
load("@bazel-orfs//:yosys.bzl", "yosys")
load("@rules_python//python:defs.bzl", "py_binary")
load("//bazel:chisel.bzl", "chisel_binary")
load(":openram.bzl", "openram_sram")

# Export files for use by sub-packages
exports_files([
    "config/constraints_asap7.sdc",
    "config/constraints_sky130hd.sdc",
    "scripts/analysis.tcl",
    "scripts/netlist_hierarchy_report.tcl",
])


PDKS = ["asap7", "sky130hd"]

chisel_binary(
    name = "zamlet_generator",
    srcs = ["//src:scala_sources"],
    main_class = "zamlet.Main",
    visibility = ["//dse/amlet:__pkg__", "//dse/bamlet:__pkg__", "//dse/gamlet:__pkg__", "//dse/jamlet:__pkg__", "//dse/utils:__pkg__"],
    deps = [
        "@maven//:io_circe_circe_core_2_13",
        "@maven//:io_circe_circe_generic_2_13",
        "@maven//:io_circe_circe_parser_2_13",
        "@maven//:io_circe_circe_yaml_2_13",
        "@maven//:org_typelevel_cats_core_2_13",
        "@maven//:org_typelevel_cats_kernel_2_13",
        "@maven//:com_chuusai_shapeless_2_13",
    ],
)

# Area analysis pie chart generator
py_binary(
    name = "area_pie_chart_script",
    srcs = ["area_pie_chart.py"],
    main = "area_pie_chart.py",
    data = [
        "//dse/amlet:all_default__sky130hd_results",
        "//dse/bamlet:all_default__sky130hd_results",
    ],
    deps = [
        "@rules_python//python/runfiles",
        "@zamlet_pip_deps//matplotlib:pkg",
    ],
)

# Pie chart as a build target
genrule(
    name = "area_pie_chart",
    srcs = [
        "//dse/amlet:all_default__sky130hd_results",
        "//dse/bamlet:all_default__sky130hd_results",
    ],
    outs = ["zamlet_area_pie_chart.png"],
    tools = [":area_pie_chart_script"],
    cmd = "$(location :area_pie_chart_script) && cp zamlet_area_pie_chart.png $@",
)

# Test OpenRAM SRAM generation
openram_sram(
    name = "test_sram_8x16",
    word_size = 8,
    num_words = 16,
    write_size = 2,
    num_rw_ports = 1,
)

openram_sram(
    name = "test_sram_16x16",
    word_size = 16,
    num_words = 16,
    write_size = 16,
    num_rw_ports = 1,
)

openram_sram(
    name = "test_sram_32x16",
    word_size = 32,
    num_words = 16,
    write_size = 32,
    num_rw_ports = 1,
)

openram_sram(
    name = "test_sram_32x32",
    word_size = 32,
    num_words = 32,
    write_size = 32,
    num_rw_ports = 1,
)

openram_sram(
    name = "test_sram_32x64",
    word_size = 32,
    num_words = 64,
    write_size = 32,
    num_rw_ports = 1,
)

openram_sram(
    name = "test_sram_32x128",
    word_size = 32,
    num_words = 128,
    write_size = 32,
    num_rw_ports = 1,
)
