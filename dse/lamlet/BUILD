# Lamlet Component DSE

load("//bazel:verilog.bzl", "chisel_dse_module")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

pdk(name = "sky130hd")

# (ModuleName, bazel_target_name)
LAMLET_MODULES = [
    ("IdentTracker", "ident_tracker"),
    ("IssueUnit", "issue_unit"),
    ("Lamlet", "lamlet"),
    ("LamletTop", "lamlet_top"),
]

[chisel_dse_module(
    name = "{}_default".format(module),
    top = module,
    generator = "//src/main/scala/zamlet/lamlet:{}".format(target),
    config = "//configs:lamlet_default.json",
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "40",
) for module, target in LAMLET_MODULES]
