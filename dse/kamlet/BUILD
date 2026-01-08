# Kamlet Component DSE
# Design space exploration for kamlet components

load("@bazel-orfs//:openroad.bzl", "orfs_flow", "orfs_run")
load("//dse:orfs_config.bzl", "get_orfs_arguments")

PDKS = ["asap7", "sky130hd"]

# Generate Synchronizer verilog
genrule(
    name = "Synchronizer_default_verilog",
    srcs = ["//configs:synchronizer_default.json"],
    outs = ["Synchronizer_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/kamlet:synchronizer) $$TMPDIR $(location //configs:synchronizer_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/kamlet:synchronizer"],
)

# OpenROAD flows for Synchronizer
[orfs_flow(
    name = "Synchronizer_default__{}".format(pdk),
    top = "Synchronizer",
    pdk = "@docker_orfs//:{}".format(pdk),
    arguments = get_orfs_arguments("Synchronizer_default", pdk),
    sources = {
        "SDC_FILE": ["//dse:config/constraints_{}.sdc".format(pdk)],
    },
    verilog_files = [":Synchronizer_default.sv"],
) for pdk in PDKS]

# Analysis results
[orfs_run(
    name = "Synchronizer_default__{}_results".format(pdk),
    src = "Synchronizer_default__{}_floorplan".format(pdk),
    outs = [
        "Synchronizer_default__{}_stats".format(pdk),
        "Synchronizer_default__{}_setup_timing.rpt".format(pdk),
        "Synchronizer_default__{}_hold_timing.rpt".format(pdk),
        "Synchronizer_default__{}_critical_paths.rpt".format(pdk),
    ],
    arguments = {
        "OUTPUT": "$(location :Synchronizer_default__{}_stats)".format(pdk),
        "TARGET_NAME": "Synchronizer_default__{}".format(pdk),
    },
    script = "//dse:scripts/analysis.tcl",
) for pdk in PDKS]
