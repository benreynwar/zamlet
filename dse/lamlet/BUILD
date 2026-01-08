# Lamlet Component DSE
# Design space exploration for lamlet components

load("@bazel-orfs//:openroad.bzl", "orfs_flow", "orfs_run")
load("//dse:orfs_config.bzl", "get_orfs_arguments")

PDKS = ["asap7", "sky130hd"]

# Generate IdentTracker verilog
genrule(
    name = "IdentTracker_default_verilog",
    srcs = ["//configs:lamlet_default.json"],
    outs = ["IdentTracker_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/lamlet:ident_tracker) $$TMPDIR $(location //configs:lamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/lamlet:ident_tracker"],
)

# OpenROAD flows for IdentTracker
[orfs_flow(
    name = "IdentTracker_default__{}".format(pdk),
    top = "IdentTracker",
    pdk = "@docker_orfs//:{}".format(pdk),
    arguments = get_orfs_arguments("IdentTracker_default", pdk),
    sources = {
        "SDC_FILE": ["//dse:config/constraints_{}.sdc".format(pdk)],
    },
    verilog_files = [":IdentTracker_default.sv"],
) for pdk in PDKS]

# Analysis results
[orfs_run(
    name = "IdentTracker_default__{}_results".format(pdk),
    src = "IdentTracker_default__{}_floorplan".format(pdk),
    outs = [
        "IdentTracker_default__{}_stats".format(pdk),
        "IdentTracker_default__{}_setup_timing.rpt".format(pdk),
        "IdentTracker_default__{}_hold_timing.rpt".format(pdk),
        "IdentTracker_default__{}_critical_paths.rpt".format(pdk),
    ],
    arguments = {
        "OUTPUT": "$(location :IdentTracker_default__{}_stats)".format(pdk),
        "TARGET_NAME": "IdentTracker_default__{}".format(pdk),
    },
    script = "//dse:scripts/analysis.tcl",
) for pdk in PDKS]
