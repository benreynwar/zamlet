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
        "name": "ALUPredicate_default",
        "top_level": "ALUPredicate",
        "config_file": "//configs:amlet_default.json",
    },
    {
        "name": "ALUPredicateRS_default",
        "top_level": "ALUPredicateRS",
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
    {
        "name": "RegisterFileAndRename_default",
        "top_level": "RegisterFileAndRename",
        "config_file": "//configs:amlet_default.json",
    },
]

# Generate all DSE flows and filegroups
dse_component_flows(AMLET_STUDIES, "amlet")
dse_filegroups(AMLET_STUDIES, "amlet")

# Convenience target to build all sky130hd area results
filegroup(
    name = "all_default__sky130hd_results",
    visibility = ["//dse:__pkg__"],
    srcs = [
        ":Amlet_default__sky130hd_results",
        ":ALURS_default__sky130hd_results", 
        ":ALU_default__sky130hd_results",
        ":ALULite_default__sky130hd_results",
        ":ALULiteRS_default__sky130hd_results",
        ":ALUPredicate_default__sky130hd_results",
        ":ALUPredicateRS_default__sky130hd_results",
        ":LoadStoreRS_default__sky130hd_results",
        ":DataMemory_default__sky130hd_results",
        ":SendPacketRS_default__sky130hd_results",
        ":ReceivePacketRS_default__sky130hd_results",
        ":SendPacketInterface_default__sky130hd_results",
        ":ReceivePacketInterface_default__sky130hd_results",
        ":NetworkNode_default__sky130hd_results",
        ":RegisterFileAndRename_default__sky130hd_results",
    ],
)