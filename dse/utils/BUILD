# Utils Component DSE
# Design space exploration for utility components

load("//dse:dse_common.bzl", "dse_component_flows", "dse_filegroups")

# Utils component studies
UTILS_STUDIES = [
    {
        "name": "RegisterFile_default",
        "top_level": "RegisterFile",
        "config_file": "//configs:register_file_default.json",
    },
    {
        "name": "DroppingFifo_default", 
        "top_level": "DroppingFifo",
        "config_file": "//configs:dropping_fifo_default.json",
    },
]

# Generate all DSE flows and filegroups
dse_component_flows(UTILS_STUDIES, "utils")
dse_filegroups(UTILS_STUDIES, "utils")