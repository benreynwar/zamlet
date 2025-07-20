# Amlet Component DSE
# Design space exploration for amlet components

load("//dse:dse_common.bzl", "dse_component_flows", "dse_filegroups")

# Amlet component studies - all use amlet_default.json config
AMLET_STUDIES = [
    {
        "name": "ALURS_default",
        "top_level": "ALURS",
        "config_file": "//configs:amlet_default.json",
    },
    {
        "name": "ALU_default",
        "top_level": "ALU",
        "config_file": "//configs:amlet_default.json",
    },
    {
        "name": "ALULiteRS_default",
        "top_level": "ALULiteRS",
        "config_file": "//configs:amlet_default.json",
    },
]

# Generate all DSE flows and filegroups
dse_component_flows(AMLET_STUDIES, "amlet")
dse_filegroups(AMLET_STUDIES, "amlet")