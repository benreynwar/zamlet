# FMVPU NetworkNode Design Space Exploration
# Adapted from RegFileStudy: https://github.com/Pinata-Consulting/RegFileStudy

load("@bazel-orfs//:openroad.bzl", "orfs_flow", "orfs_run")
load("@bazel-orfs//:write_binary.bzl", "write_binary")
load("@bazel-orfs//:yosys.bzl", "yosys")
load("//:chisel.bzl", "chisel_binary")
load(":openram.bzl", "openram_sram")

# NetworkNode channel count study - simplified for testing
STUDY = [{
    "name": "NetworkNode_{}ch_32b_16d".format(ch),
    "top_level": "NetworkNode",
    "nChannels": ch,
    "width": 32,
    "networkMemoryDepth": 16,
    "nDRF": 32,
    "ddmBankDepth": 256,
    "ddmNBanks": 4,
    "ddmAddrWidth": 10,
    "depthNetworkConfig": 64,
    "nColumns": 4,
    "nRows": 5,
    "maxPacketLength": 16,
    "maxNetworkControlDelay": 8,
    "nSlowNetworkControlSlots": 4,
    "nFastNetworkControlSlots": 4,
    "networkIdentWidth": 4,
} for ch in [1, 2, 4]]

# ALU study - same width as NetworkNode for comparison
ALU_STUDY = [{
    "name": "LaneALU_32b_32drf",
    "top_level": "LaneALU",
    "width": 32,
    "nDRF": 32,
    "nChannels": 1,
    "networkMemoryDepth": 16,
    "ddmBankDepth": 256,
    "ddmNBanks": 4,
    "ddmAddrWidth": 10,
    "depthNetworkConfig": 64,
    "nColumns": 4,
    "nRows": 5,
    "maxPacketLength": 16,
    "maxNetworkControlDelay": 8,
    "nSlowNetworkControlSlots": 4,
    "nFastNetworkControlSlots": 4,
    "networkIdentWidth": 4,
}]

# Network component studies - same parameters as NetworkNode for direct comparison
NETWORK_COMPONENT_STUDY = [{
    "name": "NetworkCrossbar_{}ch_32b_16d".format(ch),
    "top_level": "NetworkCrossbar",
    "nChannels": ch,
    "width": 32,
    "networkMemoryDepth": 16,
    "nDRF": 32,
    "ddmBankDepth": 256,
    "ddmNBanks": 4,
    "ddmAddrWidth": 10,
    "depthNetworkConfig": 64,
    "nColumns": 4,
    "nRows": 5,
    "maxPacketLength": 16,
    "maxNetworkControlDelay": 8,
    "nSlowNetworkControlSlots": 4,
    "nFastNetworkControlSlots": 4,
    "networkIdentWidth": 4,
} for ch in [1, 2, 4]] + [{
    "name": "NetworkSwitch_{}ch_32b_16d".format(ch),
    "top_level": "NetworkSwitch", 
    "nChannels": ch,
    "width": 32,
    "networkMemoryDepth": 16,
    "nDRF": 32,
    "ddmBankDepth": 256,
    "ddmNBanks": 4,
    "ddmAddrWidth": 10,
    "depthNetworkConfig": 64,
    "nColumns": 4,
    "nRows": 5,
    "maxPacketLength": 16,
    "maxNetworkControlDelay": 8,
    "nSlowNetworkControlSlots": 4,
    "nFastNetworkControlSlots": 4,
    "networkIdentWidth": 4,
} for ch in [1, 2, 4]]

# Fifo study
FIFO_STUDY = [{
    "name": "Fifo_32b_8d",
    "top_level": "Fifo",
    "width": 32,
    "depth": 8,
}]

# RegisterFileAndFriends study - uses lane_default.json config
RFF_STUDY = [{
    "name": "RegisterFileAndFriends_default",
    "top_level": "RegisterFileAndFriends",
    "config_file": "//configs:lane_default.json",
}]

# Lane ALU study - uses lane_default.json config
LANE_ALU_STUDY = [{
    "name": "ALU_default",
    "top_level": "ALU",
    "config_file": "//configs:lane_default.json",
}]

PDKS = ["asap7", "sky130hd"]
ALL_STUDIES = STUDY + ALU_STUDY + NETWORK_COMPONENT_STUDY + FIFO_STUDY + RFF_STUDY + LANE_ALU_STUDY
NAMES = ["{}__{}".format(study["name"], pdk) for study in ALL_STUDIES for pdk in PDKS]

# Generate individual JSON files for each study configuration
[genrule(
    name = "{}_config".format(study["name"]),
    outs = ["{}.json".format(study["name"])],
    cmd = "cat > $@ <<'EOF'\n{}\nEOF".format(str(study).replace("'", '"')),
) for study in ALL_STUDIES if "config_file" not in study]

# Create a filegroup containing all JSON configs
filegroup(
    name = "study_configs",
    srcs = [":{}.json".format(study["name"]) for study in ALL_STUDIES if "config_file" not in study],
)

chisel_binary(
    name = "fmvpu_generator",
    srcs = ["//src:scala_sources"],
    main_class = "fmvpu.Main",
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

# Generate concatenated Verilog for each study configuration
[genrule(
    name = "{}_verilog".format(study["name"]),
    srcs = [":{}.json".format(study["name"])],
    outs = ["{}.sv".format(study["name"])],
    cmd = """
    TMPDIR=$$(mktemp -d)
    TOP_LEVEL={}
    $(location :fmvpu_generator) \\
        $$TMPDIR/{}_verilog \\
        $$TOP_LEVEL \\
        $(location :{}.json)
    # Concatenate all SystemVerilog files and rename the top module
    find $$TMPDIR/{}_verilog -name "*.sv" -type f | sort | xargs cat | sed 's/^module '$$TOP_LEVEL'(/module {}(/' > $@
    rm -rf $$TMPDIR
    """.format(study["top_level"], study["name"], study["name"], study["name"], study["name"]),
    tools = [":fmvpu_generator"],
) for study in ALL_STUDIES if study["top_level"] not in ["Fifo", "RegisterFileAndFriends", "ALU"]]

# Generate Verilog for RegisterFileAndFriends (uses external config file)
[genrule(
    name = "{}_verilog".format(study["name"]),
    srcs = [study["config_file"]],
    outs = ["{}.sv".format(study["name"])],
    cmd = """
    TMPDIR=$$(mktemp -d)
    TOP_LEVEL={}
    $(location :fmvpu_generator) \\
        $$TMPDIR/{}_verilog \\
        $$TOP_LEVEL \\
        $(location {})
    # Concatenate all SystemVerilog files and rename the top module
    find $$TMPDIR/{}_verilog -name "*.sv" -type f | sort | xargs cat | sed 's/^module '$$TOP_LEVEL'(/module {}(/' > $@
    rm -rf $$TMPDIR
    """.format(study["top_level"], study["name"], study["config_file"], study["name"], study["name"]),
    tools = [":fmvpu_generator"],
) for study in ALL_STUDIES if study["top_level"] in ["RegisterFileAndFriends", "ALU"]]

# Generate Verilog for Fifo studies (no config file needed)
[genrule(
    name = "{}_verilog".format(study["name"]),
    outs = ["{}.sv".format(study["name"])],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location :fmvpu_generator) \\
        $$TMPDIR/{}_verilog \\
        {} \\
        {} {}
    # Concatenate all SystemVerilog files and rename the top module
    find $$TMPDIR/{}_verilog -name "*.sv" -type f | sort | xargs cat | sed 's/^module {}(/module {}(/' > $@
    rm -rf $$TMPDIR
    """.format(study["name"], study["top_level"], study["width"], study["depth"], study["name"], study["top_level"], study["name"]),
    tools = [":fmvpu_generator"],
) for study in ALL_STUDIES if study["top_level"] == "Fifo"]

# Create a filegroup containing all concatenated Verilog files
filegroup(
    name = "verilog_files",
    srcs = [":{}.sv".format(study["name"]) for study in ALL_STUDIES],
)

[orfs_flow(
    name = name,
    top = study_name,
    pdk = "@docker_orfs//:{}".format(pdk),
    arguments = {
        # Speed up the flow by skipping things
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
        # Hierarchical synthesis settings
        "SYNTH_HIERARCHICAL": "1",
        "SYNTH_MINIMUM_KEEP_SIZE": "50",
        # Normal parameters
        "PLACE_DENSITY": "0.40",
        "CORE_UTILIZATION": "20",
    },
    sources = {
        "SDC_FILE": ["config/constraints.sdc"],
    },
    verilog_files = [":{}.sv".format(study_name)],
) for study in ALL_STUDIES for pdk in PDKS for name, study_name in [("{}__{}".format(study["name"], pdk), study["name"])]]

[
    orfs_run(
        name = "{base}_results".format(base = name),
        src = "{name}_floorplan".format(name = name),
        outs = [
            "{name}_stats".format(name = name),
        ],
        arguments = {
            "OUTPUT": "$(location :{name}_stats)".format(name = name),
        },
        script = "scripts/results.tcl",
    )
    for name in NAMES
]

# Extract netlist files from synthesis outputs
[
    genrule(
        name = "{name}_netlist".format(name = name),
        srcs = [":{name}_synth".format(name = name)],
        outs = ["{name}_netlist.v".format(name = name)],
        cmd = """
        # Extract the .v netlist file from synthesis outputs
        NETLIST=$$(echo $(locations :{name}_synth) | tr ' ' '\\n' | grep '\\.v$$' | head -1)
        cp $$NETLIST $@
        """.format(name = name),
    )
    for study in ALL_STUDIES for pdk in PDKS for name, study_name in [("{}__{}".format(study["name"], pdk), study["name"])]
]

# Hierarchical area report targets
[
    yosys(
        name = "{name}_hierarchy_report".format(name = name),
        srcs = [":{name}_netlist".format(name = name), "scripts/netlist_hierarchy_report.tcl"],
        outs = ["{name}_hierarchy.txt".format(name = name)],
        arguments = [
            "-p",
            "read_verilog $(location :{name}_netlist); hierarchy -top {top_module}; tee -o $(location {name}_hierarchy.txt) stat -tech".format(name = name, top_module = study_name),
        ],
    )
    for study in ALL_STUDIES for pdk in PDKS for name, study_name in [("{}__{}".format(study["name"], pdk), study["name"])]
]

filegroup(
    name = "hierarchy_reports",
    srcs = [":{name}_hierarchy_report".format(name = name) for name in NAMES],
    visibility = ["//visibility:public"],
)

filegroup(
    name = "results",
    srcs = [":{name}_results".format(name = name) for name in NAMES],
    visibility = ["//visibility:public"],
)

# Convenience targets for running single PDK
[filegroup(
    name = "results_{}".format(pdk),
    srcs = [":{}_results".format(name) for name in NAMES if name.endswith("__{}".format(pdk))],
    visibility = ["//visibility:public"],
) for pdk in PDKS]

py_binary(
    name = "analyze_results",
    srcs = ["scripts/analyze_results.py"],
)

genrule(
    name = "plot",
    srcs = [
        "study_configs",
        "results",
    ],
    outs = ["networknode_area_study.pdf"],
    cmd = """
    set -euo pipefail
    $(execpath :analyze_results) $(location :networknode_area_study.pdf) $(locations :study_configs) $(locations :results)
    """,
    tools = [
        ":analyze_results",
    ],
)

# PDK-specific plot targets
[genrule(
    name = "plot_{}".format(pdk),
    srcs = [
        "study_configs",
        "results_{}".format(pdk),
    ],
    outs = ["networknode_area_study_{}.pdf".format(pdk)],
    cmd = """
    set -euo pipefail
    $(execpath :analyze_results) $(location :networknode_area_study_{}.pdf) {} $(locations :study_configs) $(locations :results_{})
    """.format(pdk, pdk, pdk),
    tools = [
        ":analyze_results",
    ],
) for pdk in PDKS]

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
