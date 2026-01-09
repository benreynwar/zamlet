# Lamlet Component DSE
# Design space exploration for lamlet components

load("@bazel-orfs//:openroad.bzl", "orfs_flow", "orfs_run")
load("//dse:orfs_config.bzl", "get_orfs_arguments")

PDKS = ["asap7", "sky130hd"]

# (ModuleName, bazel_target_name)
LAMLET_MODULES = [
    ("IdentTracker", "ident_tracker"),
    ("IssueUnit", "issue_unit"),
    ("Lamlet", "lamlet"),
]

# Generate verilog for each module
[genrule(
    name = "{}_default_verilog".format(module),
    srcs = ["//configs:lamlet_default.json"],
    outs = ["{}_default.sv".format(module)],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/lamlet:{target}) $$TMPDIR $(location //configs:lamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """.format(target = target),
    tools = ["//src/main/scala/zamlet/lamlet:{}".format(target)],
) for module, target in LAMLET_MODULES]

# OpenROAD flows for each module
[orfs_flow(
    name = "{}_default__{}".format(module, pdk),
    top = module,
    pdk = "@docker_orfs//:{}".format(pdk),
    arguments = get_orfs_arguments("{}_default".format(module), pdk),
    sources = {
        "SDC_FILE": ["//dse:config/constraints_{}.sdc".format(pdk)],
    },
    verilog_files = [":{}_default.sv".format(module)],
) for module, _ in LAMLET_MODULES for pdk in PDKS]

# Analysis results for each module
[orfs_run(
    name = "{}_default__{}_results".format(module, pdk),
    src = "{}_default__{}_floorplan".format(module, pdk),
    outs = [
        "{}_default__{}_stats".format(module, pdk),
        "{}_default__{}_setup_timing.rpt".format(module, pdk),
        "{}_default__{}_hold_timing.rpt".format(module, pdk),
        "{}_default__{}_critical_paths.rpt".format(module, pdk),
    ],
    arguments = {
        "OUTPUT": "$(location :{}_default__{}_stats)".format(module, pdk),
        "TARGET_NAME": "{}_default__{}".format(module, pdk),
    },
    script = "//dse:scripts/analysis.tcl",
) for module, _ in LAMLET_MODULES for pdk in PDKS]
