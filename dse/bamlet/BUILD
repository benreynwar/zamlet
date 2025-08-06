# Bamlet Component DSE
# Design space exploration for bamlet components

load("//dse:dse_common.bzl", "dse_component_flows", "dse_filegroups")

# Bamlet component studies - all use bamlet_default.json config
BAMLET_STUDIES = [
    {
        "name": "Control_default",
        "top_level": "Control",
        "config_file": "//configs:bamlet_default.json",
    },
    {
        "name": "Bamlet_default",
        "top_level": "Bamlet",
        "config_file": "//configs:bamlet_default.json",
    },
    {
        "name": "InstructionMemory_default",
        "top_level": "InstructionMemory",
        "config_file": "//configs:bamlet_default.json",
    },
    {
        "name": "DependencyTracker_default",
        "top_level": "DependencyTracker",
        "config_file": "//configs:bamlet_default.json",
    },
]

# Generate all DSE flows and filegroups
dse_component_flows(BAMLET_STUDIES, "bamlet")
dse_filegroups(BAMLET_STUDIES, "bamlet")
