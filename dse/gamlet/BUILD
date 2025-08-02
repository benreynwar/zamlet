# Gamlet Component DSE
# Design space exploration for gamlet components

load("//dse:dse_common.bzl", "dse_component_flows", "dse_filegroups")

# Gamlet component studies - all use gamlet_default.json config
GAMLET_STUDIES = [
    {
        "name": "Rename_default",
        "top_level": "Rename",
        "config_file": "//configs:gamlet_default.json",
    },
]

# Generate all DSE flows and filegroups
dse_component_flows(GAMLET_STUDIES, "gamlet")
dse_filegroups(GAMLET_STUDIES, "gamlet")