load("//bazel:verilog.bzl", "chisel_dse_module")
load("//bazel/flow:defs.bzl",
    "librelane_classic_bundled_flow",
    "librelane_compare_flows_test",
    "librelane_flow_inputs",
)
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

pdk(name = "sky130hd")


WALLACE_MULT_CONFIGS = [
    "WallaceMult8x8",
    "WallaceMult16x16",
    "WallaceMult32x32",
    "WallaceMult64x64",
]

[chisel_dse_module(
    name = name,
    top = name,
    generator = "//src/main/scala/zamlet/maths:wallace_mult",
    config = "//configs:{}.json".format(name),
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
    clock_port = "clock",
    core_utilization = "40",
    input_delay_constraint = "40",
    output_delay_constraint = "40",
)

# Flow inputs for manual debugging
librelane_flow_inputs(
    name = "WallaceMult8x8_flow_inputs",
    verilog_files = [":WallaceMult8x8.sv"],
    top = "WallaceMult8x8",
    pdk = ":sky130hd",
    clock_period = "10.0",
    clock_port = "clock",
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
