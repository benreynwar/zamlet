# Amlet Component DSE
# Design space exploration for amlet components

load("//dse:dse_common.bzl", "dse_component_flows", "dse_filegroups")

# Amlet component studies - all use amlet_default.json config
AMLET_STUDIES = [
    {
        "name": "Amlet_default",
        "top_level": "Amlet",
        "config_file": "//configs:amlet_default.json",
    },
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
        "name": "ALULite_default",
        "top_level": "ALULite",
        "config_file": "//configs:amlet_default.json",
    },
    {
        "name": "ALULiteRS_default",
        "top_level": "ALULiteRS",
        "config_file": "//configs:amlet_default.json",
    },
    {
        "name": "LoadStoreRS_default",
        "top_level": "LoadStoreRS",
        "config_file": "//configs:amlet_default.json",
    },
    {
        "name": "DataMemory_default",
        "top_level": "DataMemory",
        "config_file": "//configs:amlet_default.json",
    },
    {
        "name": "SendPacketRS_default",
        "top_level": "SendPacketRS",
        "config_file": "//configs:amlet_default.json",
    },
    {
        "name": "ReceivePacketRS_default",
        "top_level": "ReceivePacketRS",
        "config_file": "//configs:amlet_default.json",
    },
    {
        "name": "SendPacketInterface_default",
        "top_level": "SendPacketInterface",
        "config_file": "//configs:amlet_default.json",
    },
    {
        "name": "ReceivePacketInterface_default",
        "top_level": "ReceivePacketInterface",
        "config_file": "//configs:amlet_default.json",
    },
    {
        "name": "NetworkNode_default",
        "top_level": "NetworkNode",
        "config_file": "//configs:amlet_default.json",
    },
]

# Generate all DSE flows and filegroups
dse_component_flows(AMLET_STUDIES, "amlet")
dse_filegroups(AMLET_STUDIES, "amlet")