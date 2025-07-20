# New Lane Component DSE
# Design space exploration for the new lane implementation

load("//dse:dse_common.bzl", "dse_component_flows", "dse_filegroups")

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

# Generate all DSE flows and filegroups
dse_component_flows(NEW_LANE_STUDIES, "new_lane")
dse_filegroups(NEW_LANE_STUDIES, "new_lane")