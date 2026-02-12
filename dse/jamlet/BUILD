# Jamlet Component DSE

load("//bazel:verilog.bzl", "chisel_verilog", "chisel_dse_module")
load("//bazel/flow:defs.bzl", "librelane_classic_flow", "librelane_synth_config")
load("//bazel/flow:def_template.bzl", "combined_network_node_def")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

exports_files(["gen_combined_network_node_def.py"])

pdk(name = "sky130hd")

# Synth config with autoname for readable timing reports
librelane_synth_config(
    name = "synth_autoname",
    synth_autoname = True,
)

ZAMLET_CONFIG = "//configs:zamlet_default.json"
JAMLET_PKG = "//src/main/scala/zamlet/jamlet"

# Jamlet top module with custom pin placement
chisel_dse_module(
    name = "Jamlet_default",
    top = "Jamlet",
    generator = JAMLET_PKG + ":jamlet",
    config = ZAMLET_CONFIG,
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "35",
    pin_order_cfg = ":jamlet_pin_order.cfg",
)

# NetworkNode with custom pin placement
chisel_dse_module(
    name = "NetworkNode_default",
    top = "NetworkNode",
    generator = JAMLET_PKG + ":networknode",
    config = ZAMLET_CONFIG,
    pdk = ":sky130hd",
    clock_period = "10.0",
    die_area = "0 0 330 770",
    pl_target_density_pct = "50",
    pin_order_cfg = ":networknode_pin_order.cfg",
)

# CombinedNetworkNode needs a DEF template between verilog gen and flow
chisel_verilog(
    name = "CombinedNetworkNode_default",
    generator = JAMLET_PKG + ":combinednetworknode",
    config = ZAMLET_CONFIG,
)

COMBINED_NETWORK_NODE_DIE_AREA = "0 0 500 830"

combined_network_node_def(
    name = "CombinedNetworkNode_default_sky130hd_def_template",
    pdk = ":sky130hd",
    config = ZAMLET_CONFIG,
    die_area = COMBINED_NETWORK_NODE_DIE_AREA,
)

librelane_classic_flow(
    name = "CombinedNetworkNode_default_sky130hd",
    verilog_files = [":CombinedNetworkNode_default.sv"],
    top = "CombinedNetworkNode",
    pdk = ":sky130hd",
    clock_period = "10.0",
    die_area = COMBINED_NETWORK_NODE_DIE_AREA,
    pl_target_density_pct = "60",
    def_template = ":CombinedNetworkNode_default_sky130hd_def_template",
)

# (ModuleName, bazel_target_name)
JAMLET_SUB_MODULES = [
    ("RfSlice", "rfslice"),
    ("WitemMonitor", "witemmonitor"),
    ("LocalExec", "localexec"),
]

[chisel_dse_module(
    name = "{}_default".format(module),
    top = module,
    generator = JAMLET_PKG + ":{}".format(target),
    config = ZAMLET_CONFIG,
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "35",
    synth_config = ":synth_autoname",
) for module, target in JAMLET_SUB_MODULES]

# PacketArbiter with 2 inputs (as used in Jamlet)
chisel_dse_module(
    name = "PacketArbiter_default",
    top = "PacketArbiter",
    generator = JAMLET_PKG + ":packetarbiter",
    config = ZAMLET_CONFIG,
    pdk = ":sky130hd",
    extra_generator_args = ["2"],
    clock_period = "10.0",
    core_utilization = "60",
)

# VectorRf - generic vector register file slice
chisel_dse_module(
    name = "VectorRf_3r1w",
    top = "VectorRf",
    generator = JAMLET_PKG + ":vectorrf",
    config = "//configs:vector_rf_3r1w.json",
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "40",
)
