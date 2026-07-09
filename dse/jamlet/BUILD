# Jamlet Component DSE

load("//bazel:verilog.bzl", "chisel_dse_module", "chisel_verilog_no_config")
load("//bazel/flow:defs.bzl", "librelane_classic_flow", "librelane_synth_config")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

pdk(name = "sky130hd")

# Synth config with autoname for readable timing reports
librelane_synth_config(
    name = "synth_autoname",
    synth_autoname = True,
)

ZAMLET_CONFIG = "//configs:zamlet_default.json"
JAMLET_PKG = "//src/main/scala/zamlet/jamlet"

# Jamlet top module with custom pin placement
chisel_dse_module(
    name = "Jamlet_default",
    top = "Jamlet",
    generator = JAMLET_PKG + ":jamlet",
    config = ZAMLET_CONFIG,
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "35",
    pin_order_cfg = ":jamlet_pin_order.cfg",
)

# (ModuleName, bazel_target_name, extra_generator_args, core_utilization)
JAMLET_SUB_MODULES = [
    ("RfSlice", "rfslice", [], "35"),
    ("Sram", "sram", [], "35"),
    ("Jce", "jce", [], "35"),
    ("LocalExec", "localexec", [], "35"),
    ("CoordsToIndexWithReg", "coordstoindexwithreg", [], "35"),
    ("IndexToCoordsWithReg", "indextocoordswithreg", [], "35"),
    ("Jte", "jte", [], "40"),
    ("JteInitiator", "jteinitiator", [], "30"),
    ("JteInitiatorA", "jteinitiatorstage", ["A"], "5"),
    ("JteInitiatorB", "jteinitiatorstage", ["B"], "5"),
    ("JteInitiatorC", "jteinitiatorstage", ["C"], "35"),
    ("JteInitiatorD", "jteinitiatorstage", ["D"], "35"),
    ("JteInitiatorE", "jteinitiatorstage", ["E"], "35"),
    ("JteInitiatorF", "jteinitiatorstage", ["F"], "35"),
    ("JteInitiatorG", "jteinitiatorstage", ["G"], "35"),
    ("JteInitiatorH", "jteinitiatorstage", ["H"], "35"),
    ("JteInitiatorI", "jteinitiatorstage", ["I"], "35"),
    ("JteHandler", "jtehandler", [], "30"),
    ("JteHandlerA", "jtehandlerstage", ["A"], "5"),
    ("JteHandlerB", "jtehandlerstage", ["B"], "5"),
    ("JteHandlerC", "jtehandlerstage", ["C"], "35"),
    ("JteHandlerD", "jtehandlerstage", ["D"], "35"),
    ("JteHandlerE", "jtehandlerstage", ["E"], "35"),
    ("JteHandlerF", "jtehandlerstage", ["F"], "35"),
    ("JteHandlerG", "jtehandlerstage", ["G"], "35"),
    ("JteHandlerH", "jtehandlerstage", ["H"], "35"),
    ("JteReceiver", "jtereceiver", [], "30"),
    ("JteState", "jtestate", [], "20"),
]

# (config_name_suffix, config_label)
ZAMLET_CONFIGS = [
    ("default",   "//configs:zamlet_default.json"),
    ("1024lanes", "//configs:zamlet_1024lanes.json"),
]

[chisel_dse_module(
    name = "{}_{}".format(module, cfg_name),
    top = module,
    generator = JAMLET_PKG + ":{}".format(target),
    config = cfg_path,
    pdk = ":sky130hd",
    extra_generator_args = extra_args,
    clock_period = "10.0",
    core_utilization = core_util,
    synth_config = ":synth_autoname",
) for module, target, extra_args, core_util in JAMLET_SUB_MODULES
  for cfg_name, cfg_path in ZAMLET_CONFIGS]

# VectorRf - generic vector register file slice
chisel_dse_module(
    name = "VectorRf_3r1w",
    top = "VectorRf",
    generator = JAMLET_PKG + ":vectorrf",
    config = "//configs:vector_rf_3r1w.json",
    pdk = ":sky130hd",
    clock_period = "10.0",
    core_utilization = "40",
)

chisel_verilog_no_config(
    name = "JamletMxu",
    generator = JAMLET_PKG + ":jamletmxu",
)

librelane_classic_flow(
    name = "JamletMxu_sky130hd",
    verilog_files = [":JamletMxu.sv"],
    top = "JamletMxu",
    pdk = ":sky130hd",
    clock_period = "20.0",
    core_utilization = "40",
    synth_config = ":synth_autoname",
)

chisel_verilog_no_config(
    name = "JamletMxu4x4",
    generator = JAMLET_PKG + ":jamletmxu",
    extra_args = ["4"],
)

librelane_classic_flow(
    name = "JamletMxu4x4_sky130hd",
    verilog_files = [":JamletMxu4x4.sv"],
    top = "JamletMxu",
    pdk = ":sky130hd",
    clock_period = "20.0",
    core_utilization = "40",
    synth_config = ":synth_autoname",
)

chisel_verilog_no_config(
    name = "JamletMxuGrid4x4",
    generator = JAMLET_PKG + ":jamletmxugrid",
    extra_args = ["4"],
)

librelane_classic_flow(
    name = "JamletMxuGrid4x4_sky130hd",
    verilog_files = [":JamletMxuGrid4x4.sv"],
    top = "JamletMxuGrid",
    pdk = ":sky130hd",
    clock_period = "20.0",
    core_utilization = "40",
    synth_config = ":synth_autoname",
)

chisel_verilog_no_config(
    name = "JamletMxuCell",
    generator = JAMLET_PKG + ":jamletmxucell",
)

librelane_classic_flow(
    name = "JamletMxuCell_sky130hd",
    verilog_files = [":JamletMxuCell.sv"],
    top = "JamletMxuCell",
    pdk = ":sky130hd",
    clock_period = "20.0",
    core_utilization = "35",
    synth_config = ":synth_autoname",
)
