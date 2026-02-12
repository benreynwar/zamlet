# Kamlet Component DSE

load("//bazel:verilog.bzl", "chisel_dse_module")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

pdk(name = "sky130hd")

chisel_dse_module(
    name = "Synchronizer_default",
    top = "Synchronizer",
    generator = "//src/main/scala/zamlet/kamlet:synchronizer",
    config = "//configs:synchronizer_default.json",
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "40",
)

chisel_dse_module(
    name = "Kamlet_default",
    top = "Kamlet",
    generator = "//src/main/scala/zamlet/kamlet:kamlet",
    config = "//configs:zamlet_default.json",
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "40",
)
