# Jamlet Component DSE
# Design space exploration for jamlet components

load("//bazel/flow:defs.bzl", "librelane_classic_flow", "librelane_synth_config")
load("//bazel/flow:def_template.bzl", "combined_network_node_def")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

exports_files(["gen_combined_network_node_def.py"])

# PDK target
pdk(name = "sky130hd")

# Synth config with autoname for readable timing reports
librelane_synth_config(
    name = "synth_autoname",
    synth_autoname = True,
)

# (ModuleName, bazel_target_name)
# Jamlet and NetworkNode handled separately due to custom pin placement
JAMLET_SUB_MODULES = [
    ("RfSlice", "rfslice"),
    ("WitemMonitor", "witemmonitor"),
    ("LocalExec", "localexec"),
]

# Generate verilog for Jamlet top module
genrule(
    name = "Jamlet_default_verilog",
    srcs = ["//configs:lamlet_default.json"],
    outs = ["Jamlet_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/jamlet:jamlet) $$TMPDIR $(location //configs:lamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/jamlet:jamlet"],
)

# Jamlet hard macro with custom pin placement
librelane_classic_flow(
    name = "Jamlet_default_sky130hd",
    verilog_files = [":Jamlet_default.sv"],
    top = "Jamlet",
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "35",
    pin_order_cfg = ":jamlet_pin_order.cfg",
)

# NetworkNode verilog
genrule(
    name = "NetworkNode_default_verilog",
    srcs = ["//configs:lamlet_default.json"],
    outs = ["NetworkNode_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/jamlet:networknode) $$TMPDIR $(location //configs:lamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/jamlet:networknode"],
)

# NetworkNode hard macro with custom pin placement
librelane_classic_flow(
    name = "NetworkNode_default_sky130hd",
    verilog_files = [":NetworkNode_default.sv"],
    top = "NetworkNode",
    pdk = ":sky130hd",
    clock_period = "10.0",
    die_area = "0 0 330 770",
    pl_target_density_pct = "50",
    pin_order_cfg = ":networknode_pin_order.cfg",
)

# CombinedNetworkNode verilog
genrule(
    name = "CombinedNetworkNode_default_verilog",
    srcs = ["//configs:lamlet_default.json"],
    outs = ["CombinedNetworkNode_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/jamlet:combinednetworknode) $$TMPDIR $(location //configs:lamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/jamlet:combinednetworknode"],
)

COMBINED_NETWORK_NODE_DIE_AREA = "0 0 500 830"

# CombinedNetworkNode DEF template with precise pin placement
combined_network_node_def(
    name = "CombinedNetworkNode_default_sky130hd_def_template",
    pdk = ":sky130hd",
    config = "//configs:lamlet_default.json",
    die_area = COMBINED_NETWORK_NODE_DIE_AREA,
)

# CombinedNetworkNode hard macro with DEF template for precise pin placement
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

# Generate verilog for sub-modules
[genrule(
    name = "{}_default_verilog".format(module),
    srcs = ["//configs:lamlet_default.json"],
    outs = ["{}_default.sv".format(module)],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/jamlet:{target}) $$TMPDIR $(location //configs:lamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """.format(target = target),
    tools = ["//src/main/scala/zamlet/jamlet:{}".format(target)],
) for module, target in JAMLET_SUB_MODULES]

# Librelane hard macro flows for sub-modules
[librelane_classic_flow(
    name = "{}_default_sky130hd".format(module),
    verilog_files = [":{}_default.sv".format(module)],
    top = module,
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "35",
    synth_config = ":synth_autoname",
) for module, _ in JAMLET_SUB_MODULES]


# PacketArbiter with 2 inputs (as used in Jamlet)
genrule(
    name = "PacketArbiter_default_verilog",
    srcs = ["//configs:lamlet_default.json"],
    outs = ["PacketArbiter_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/jamlet:packetarbiter) $$TMPDIR $(location //configs:lamlet_default.json) 2
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/jamlet:packetarbiter"],
)

librelane_classic_flow(
    name = "PacketArbiter_default_sky130hd",
    verilog_files = [":PacketArbiter_default.sv"],
    top = "PacketArbiter",
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "60",
)
