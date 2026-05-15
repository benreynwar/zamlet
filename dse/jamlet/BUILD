# Jamlet Component DSE

load("//bazel:verilog.bzl", "chisel_dse_module")
load("//bazel/flow:defs.bzl", "librelane_synth_config")
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

# (ModuleName, bazel_target_name)
JAMLET_SUB_MODULES = [
    ("RfSlice", "rfslice"),
    ("WitemMonitor", "witemmonitor"),
    ("LocalExec", "localexec"),
    ("CoordsToIndexWithReg", "coordstoindexwithreg"),
    ("IndexToCoordsWithReg", "indextocoordswithreg"),
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
    clock_period = "10.0",
    core_utilization = "35",
    synth_config = ":synth_autoname",
) for module, target in JAMLET_SUB_MODULES
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
