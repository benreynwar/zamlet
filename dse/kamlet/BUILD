# Kamlet Component DSE
# Design space exploration for kamlet components

load("//bazel/flow:defs.bzl", "librelane_classic_flow")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

# PDK target
pdk(name = "sky130hd")

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

# Librelane flow for Synchronizer
librelane_classic_flow(
    name = "Synchronizer_default_sky130hd",
    verilog_files = [":Synchronizer_default.sv"],
    top = "Synchronizer",
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "40",
)

# Generate Kamlet verilog
genrule(
    name = "Kamlet_default_verilog",
    srcs = ["//configs:lamlet_default.json"],
    outs = ["Kamlet_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/kamlet:kamlet) $$TMPDIR $(location //configs:lamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/kamlet:kamlet"],
)

# Librelane flow for Kamlet
librelane_classic_flow(
    name = "Kamlet_default_sky130hd",
    verilog_files = [":Kamlet_default.sv"],
    top = "Kamlet",
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "40",
)
