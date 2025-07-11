# New Lane Component DSE
# Design space exploration for the new lane implementation

load("@bazel-orfs//:openroad.bzl", "orfs_flow", "orfs_run")
load("@bazel-orfs//:yosys.bzl", "yosys")

# New Lane component studies - all use lane_default.json config
NEW_LANE_STUDIES = [
    {
        "name": "RegisterFileAndFriends_default",
        "top_level": "RegisterFileAndFriends",
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "ALU_default", 
        "top_level": "ALU",
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "InstructionMemory_default",
        "top_level": "InstructionMemory", 
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "AluRS_default",
        "top_level": "AluRS",
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "LoadStoreRS_default",
        "top_level": "LoadStoreRS",
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "PacketRS_default",
        "top_level": "PacketRS",
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "LaneDataMemory_default",
        "top_level": "LaneDataMemory",
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "PacketInterface_default",
        "top_level": "PacketInterface",
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "PacketInHandler_default",
        "top_level": "PacketInHandler",
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "PacketOutHandler_default",
        "top_level": "PacketOutHandler",
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "PacketSwitch_default",
        "top_level": "PacketSwitch",
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "LaneNetworkNode_default",
        "top_level": "LaneNetworkNode",
        "config_file": "//configs:lane_default.json",
    },
    {
        "name": "NewLane_default",
        "top_level": "NewLane",
        "config_file": "//configs:lane_default.json",
    },
]

PDKS = ["asap7", "sky130hd"]
NEW_LANE_NAMES = ["{}__{}".format(study["name"], pdk) for study in NEW_LANE_STUDIES for pdk in PDKS]

# Generate Verilog for new lane components
[genrule(
    name = "{}_verilog".format(study["name"]),
    srcs = [study["config_file"]],
    outs = ["{}.sv".format(study["name"])],
    cmd = """
    TMPDIR=$$(mktemp -d)
    TOP_LEVEL={}
    $(location //dse:fmvpu_generator) \\
        $$TMPDIR/{}_verilog \\
        $$TOP_LEVEL \\
        $(location {})
    # Concatenate all SystemVerilog files and rename the top module
    find $$TMPDIR/{}_verilog -name "*.sv" -type f | sort | xargs cat | sed 's/^module '$$TOP_LEVEL'(/module {}(/' > $@
    rm -rf $$TMPDIR
    """.format(study["top_level"], study["name"], study["config_file"], study["name"], study["name"]),
    tools = ["//dse:fmvpu_generator"],
) for study in NEW_LANE_STUDIES]

# OpenROAD flows for each component and PDK
[orfs_flow(
    name = name,
    top = study_name,
    pdk = "@docker_orfs//:{}".format(pdk),
    arguments = {
        "FILL_CELLS": "",
        "TAPCELL_TCL": "",
        "SKIP_REPORT_METRICS": "1",
        "SKIP_CTS_REPAIR_TIMING": "1", 
        "SKIP_INCREMENTAL_REPAIR": "1",
        "GND_NETS_VOLTAGES": "",
        "PWR_NETS_VOLTAGES": "",
        "GPL_ROUTABILITY_DRIVEN": "0",
        "GPL_TIMING_DRIVEN": "0",
        "SETUP_SLACK_MARGIN": "-10000",
        "TNS_END_PERCENT": "0",
        "SYNTH_HIERARCHICAL": "1",
        "SYNTH_MINIMUM_KEEP_SIZE": "50",
        "PLACE_DENSITY": "0.40",
        "CORE_UTILIZATION": "20",
    },
    sources = {
        "SDC_FILE": ["//dse:config/constraints.sdc"],
    },
    verilog_files = [":{}.sv".format(study_name)],
) for study in NEW_LANE_STUDIES for pdk in PDKS for name, study_name in [("{}__{}".format(study["name"], pdk), study["name"])]]

# Results extraction
[orfs_run(
    name = "{base}_results".format(base = name),
    src = "{name}_floorplan".format(name = name),
    outs = ["{name}_stats".format(name = name)],
    arguments = {
        "OUTPUT": "$(location :{name}_stats)".format(name = name),
    },
    script = "//dse:scripts/results.tcl",
) for name in NEW_LANE_NAMES]

# Netlist extraction
[genrule(
    name = "{name}_netlist".format(name = name),
    srcs = [":{name}_synth".format(name = name)],
    outs = ["{name}_netlist.v".format(name = name)],
    cmd = """
    NETLIST=$$(echo $(locations :{name}_synth) | tr ' ' '\\n' | grep '\\.v$$' | head -1)
    cp $$NETLIST $@
    """.format(name = name),
) for study in NEW_LANE_STUDIES for pdk in PDKS for name, study_name in [("{}__{}".format(study["name"], pdk), study["name"])]]

# Hierarchical area reports
[yosys(
    name = "{name}_hierarchy_report".format(name = name),
    srcs = [":{name}_netlist".format(name = name), "//dse:scripts/netlist_hierarchy_report.tcl"],
    outs = ["{name}_hierarchy.txt".format(name = name)],
    arguments = [
        "-p",
        "read_verilog $(location :{name}_netlist); hierarchy -top {top_module}; tee -o $(location {name}_hierarchy.txt) stat -tech".format(name = name, top_module = study_name),
    ],
) for study in NEW_LANE_STUDIES for pdk in PDKS for name, study_name in [("{}__{}".format(study["name"], pdk), study["name"])]]

# Convenience filegroups
filegroup(
    name = "new_lane_results",
    srcs = [":{name}_results".format(name = name) for name in NEW_LANE_NAMES],
    visibility = ["//visibility:public"],
)

filegroup(
    name = "new_lane_hierarchy_reports", 
    srcs = [":{name}_hierarchy_report".format(name = name) for name in NEW_LANE_NAMES],
    visibility = ["//visibility:public"],
)

# PDK-specific results
[filegroup(
    name = "new_lane_results_{}".format(pdk),
    srcs = [":{}_results".format(name) for name in NEW_LANE_NAMES if name.endswith("__{}".format(pdk))],
    visibility = ["//visibility:public"],
) for pdk in PDKS]