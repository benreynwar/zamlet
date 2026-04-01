# Network Component DSE

load("//bazel:verilog.bzl", "chisel_verilog", "chisel_dse_module")
load("//bazel/flow:defs.bzl", "librelane_classic_flow")
load("//bazel/flow:def_template.bzl", "combined_network_node_def")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

exports_files(["gen_combined_network_node_def.py"])

pdk(name = "sky130hd")

ZAMLET_CONFIG = "//configs:zamlet_default.json"
NETWORK_PKG = "//src/main/scala/zamlet/network"

# NetworkNode with custom pin placement
chisel_dse_module(
    name = "NetworkNode_default",
    top = "NetworkNode",
    generator = NETWORK_PKG + ":networknode",
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
    generator = NETWORK_PKG + ":combinednetworknode",
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

# PacketArbiter with 2 inputs (as used in Jamlet)
chisel_dse_module(
    name = "PacketArbiter_default",
    top = "PacketArbiter",
    generator = NETWORK_PKG + ":packetarbiter",
    config = ZAMLET_CONFIG,
    pdk = ":sky130hd",
    extra_generator_args = ["2"],
    clock_period = "10.0",
    core_utilization = "60",
)
