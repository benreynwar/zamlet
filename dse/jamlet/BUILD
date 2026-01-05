# Jamlet Component DSE
# Design space exploration for jamlet components

load("//dse:dse_common.bzl", "dse_component_flows", "dse_filegroups")

# Jamlet component studies
JAMLET_STUDIES = [
    {
        "name": "Jamlet_default",
        "top_level": "Jamlet",
        "config_file": "//configs:jamlet_default.json",
    },
    {
        "name": "WitemMonitor_default",
        "top_level": "WitemMonitor",
        "config_file": "//configs:jamlet_default.json",
    },
]

# Generate all DSE flows and filegroups
dse_component_flows(JAMLET_STUDIES, "jamlet")
dse_filegroups(JAMLET_STUDIES, "jamlet")

# Convenience target to build all sky130hd area results
filegroup(
    name = "all_default__sky130hd_results",
    visibility = ["//dse:__pkg__"],
    srcs = [
        ":Jamlet_default__sky130hd_results",
    ],
)
