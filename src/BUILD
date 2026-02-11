# Scala source files for FMVPU

load("//bazel:chisel.bzl", "chisel_binary")

# Common dependencies for Zamlet modules
ZAMLET_DEPS = [
    "@maven//:org_typelevel_cats_core_2_13",
    "@maven//:org_typelevel_cats_kernel_2_13",
    "@maven//:io_circe_circe_core_2_13",
    "@maven//:io_circe_circe_generic_2_13",
    "@maven//:io_circe_circe_parser_2_13",
    "@maven//:io_circe_circe_yaml_2_13",
    "@maven//:com_chuusai_shapeless_2_13",
]

# Shuttle/Rocket-Chip dependencies
SHUTTLE_DEPS = [
    "@shuttle//:shuttle",
    "@rocket_chip//:rocket_chip",
    "@cde//:cde",
    "@diplomacy//:diplomacy",
    "@maven//:com_lihaoyi_sourcecode_2_13",
]

# Common Zamlet sources
ZAMLET_COMMON_SRCS = [
    "//src/main/scala/zamlet:ModuleGenerator.scala",
    "//src/main/scala/zamlet:LamletParams.scala",
    "//src/main/scala/zamlet/utils:utils_sources",
]

# Shuttle tile generator - generates standalone Shuttle system with exposed AXI ports
chisel_binary(
    name = "shuttle_tile_generator",
    srcs = [
        "//src/main/scala/zamlet/shuttle:shuttle_sources",
    ],
    main_class = "zamlet.shuttle.Main",
    deps = SHUTTLE_DEPS,
    visibility = ["//visibility:public"],
)

# Oamlet generator - Shuttle with Zamlet vector unit
chisel_binary(
    name = "oamlet_generator",
    srcs = [
        "//src/main/scala/zamlet/shuttle:shuttle_sources",
        "//src/main/scala/zamlet/oamlet:oamlet_sources",
        "//src/main/scala/zamlet/lamlet:lamlet_sources",
        "//src/main/scala/zamlet/kamlet:kamlet_sources",
        "//src/main/scala/zamlet/jamlet:jamlet_sources",
    ] + ZAMLET_COMMON_SRCS,
    main_class = "zamlet.oamlet.Main",
    deps = ZAMLET_DEPS + SHUTTLE_DEPS,
    visibility = ["//visibility:public"],
)

# Generate Oamlet Verilog (small config for faster iteration)
genrule(
    name = "oamlet_verilog",
    srcs = ["//configs:lamlet_default.json"],
    outs = ["OamletTop.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location :oamlet_generator) $$TMPDIR $(location //configs:lamlet_default.json) small
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = [":oamlet_generator"],
    visibility = ["//visibility:public"],
)
