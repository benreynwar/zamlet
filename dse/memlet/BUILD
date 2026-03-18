# Jamlet Component DSE

load("//bazel:verilog.bzl", "chisel_verilog", "chisel_dse_module")
load("//bazel/flow:defs.bzl", "librelane_classic_flow", "librelane_synth_config")
load("//bazel/flow:def_template.bzl", "combined_network_node_def")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

pdk(name = "sky130hd")

# Synth config with autoname for readable timing reports
librelane_synth_config(
    name = "synth_autoname",
    synth_autoname = True,
)

ZAMLET_CONFIG = "//configs:zamlet_default.json"
MEMLET_PKG = "//src/main/scala/zamlet/memlet"

# Jamlet top module with custom pin placement
chisel_dse_module(
    name = "Memlet_default",
    top = "Memlet",
    generator = MEMLET_PKG + ":memlet",
    config = ZAMLET_CONFIG,
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "50",
)
