load("//bazel/flow:defs.bzl",
    "librelane_classic_flow",
    "librelane_classic_bundled_flow",
    "librelane_compare_flows_test",
)
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

pdk(name = "sky130hd")


WALLACE_MULT_CONFIGS = [
    "WallaceMult8x8",
    "WallaceMult16x16",
    "WallaceMult32x32",
    "WallaceMult64x64",
]

[genrule(
    name = "{}_verilog".format(name),
    srcs = ["//configs:{}.json".format(name)],
    outs = ["{}.sv".format(name)],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/maths:wallace_mult) $$TMPDIR $(location //configs:{}.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """.format(name),
    tools = ["//src/main/scala/zamlet/maths:wallace_mult"],
) for name in WALLACE_MULT_CONFIGS]

[librelane_classic_flow(
    name = "{}_sky130hd".format(name),
    verilog_files = [":{}.sv".format(name)],
    top = name,
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "40",
    input_delay_constraint = "40",
    output_delay_constraint = "40",
) for name in WALLACE_MULT_CONFIGS]

# Bundled flow for validation (same attrs as classic_flow)
librelane_classic_bundled_flow(
    name = "WallaceMult8x8_bundled",
    verilog_files = [":WallaceMult8x8.sv"],
    top = "WallaceMult8x8",
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "40",
    input_delay_constraint = "40",
    output_delay_constraint = "40",
)

# Compare bundled vs Bazel flow outputs
librelane_compare_flows_test(
    name = "WallaceMult8x8_compare_test",
    bundled = ":WallaceMult8x8_bundled",
    bazel_synth = ":WallaceMult8x8_sky130hd_synth",
    bazel_floorplan = ":WallaceMult8x8_sky130hd_floorplan",
    bazel_gpl = ":WallaceMult8x8_sky130hd_gpl",
)

