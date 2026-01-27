# Lamlet Component DSE
# Design space exploration for lamlet components

load("//bazel/flow:defs.bzl", "librelane_classic_flow")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

# PDK target
pdk(name = "sky130hd")

# (ModuleName, bazel_target_name)
LAMLET_MODULES = [
    ("IdentTracker", "ident_tracker"),
    ("IssueUnit", "issue_unit"),
    ("Lamlet", "lamlet"),
    ("LamletTop", "lamlet_top"),
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

# Librelane flows for each module
[librelane_classic_flow(
    name = "{}_default_sky130hd".format(module),
    verilog_files = [":{}_default.sv".format(module)],
    top = module,
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "40",
) for module, _ in LAMLET_MODULES]
