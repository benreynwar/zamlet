# FMVPU Design Space Exploration
# Uses librelane for physical design flows

load("@rules_python//python:defs.bzl", "py_binary")
load("//bazel:chisel.bzl", "chisel_binary")
load(":openram.bzl", "openram_sram")

# Export files for use by sub-packages
exports_files([
    "config/constraints_sky130hd.sdc",
    "scripts/analysis.tcl",
    "scripts/netlist_hierarchy_report.tcl",
])

chisel_binary(
    name = "zamlet_generator",
    srcs = ["//src:scala_sources"],
    main_class = "zamlet.Main",
    visibility = [
        "//dse/kamlet:__pkg__",
        "//dse/lamlet:__pkg__",
        "//dse/jamlet:__pkg__",
        "//dse/utils:__pkg__",
    ],
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
