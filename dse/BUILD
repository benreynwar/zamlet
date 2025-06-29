# FMVPU NetworkNode Design Space Exploration
# Adapted from RegFileStudy: https://github.com/Pinata-Consulting/RegFileStudy

load("@bazel-orfs//:openroad.bzl", "orfs_flow", "orfs_run")
load("@bazel-orfs//:write_binary.bzl", "write_binary")
load("//:chisel.bzl", "chisel_binary")

# NetworkNode channel count study - simplified for testing
STUDY = [{
    "name": "NetworkNode_{}ch_32b_16d".format(ch),
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

PDKS = ["asap7", "sky130hd"]
NAMES = ["{}__{}".format(study["name"], pdk) for study in STUDY for pdk in PDKS]

# Generate individual JSON files for each study configuration
[genrule(
    name = "{}_config".format(study["name"]),
    outs = ["{}.json".format(study["name"])],
    cmd = "cat > $@ <<'EOF'\n{}\nEOF".format(str(study).replace("'", '"')),
) for study in STUDY]

# Create a filegroup containing all JSON configs
filegroup(
    name = "study_configs",
    srcs = [":{}.json".format(study["name"]) for study in STUDY],
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
    $(location :fmvpu_generator) \\
        $$TMPDIR/{}_verilog \\
        NetworkNode \\
        $(location :{}.json)
    # Concatenate all SystemVerilog files and rename the top module
    find $$TMPDIR/{}_verilog -name "*.sv" -type f | sort | xargs cat | sed 's/^module NetworkNode(/module {}(/' > $@
    rm -rf $$TMPDIR
    """.format(study["name"], study["name"], study["name"], study["name"]),
    tools = [":fmvpu_generator"],
) for study in STUDY]

# Create a filegroup containing all concatenated Verilog files
filegroup(
    name = "verilog_files",
    srcs = [":{}.sv".format(study["name"]) for study in STUDY],
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
        # Normal parameters
        "PLACE_DENSITY": "0.40",
        "CORE_UTILIZATION": "20",
    },
    sources = {
        "SDC_FILE": ["config/constraints.sdc"],
    },
    verilog_files = [":{}.sv".format(study_name)],
) for study in STUDY for pdk in PDKS for name, study_name in [("{}__{}".format(study["name"], pdk), study["name"])]]

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
