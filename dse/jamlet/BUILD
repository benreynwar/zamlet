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

librelane_synth_config(
    name = "synth_mxu_preserve_cell",
    synth_autoname = True,
    synth_keep_hierarchy_modules = ["JamletMxuCell"],
)

ZAMLET_CONFIG = "//configs:zamlet_default.json"
JAMLET_PKG = "//src/main/scala/zamlet/jamlet"
SYSTOLIC_PKG = "//src/main/scala/zamlet/systolic"

# Jamlet top module with custom pin placement
chisel_dse_module(
    name = "Jamlet_default",
    top = "Jamlet",
    generator = JAMLET_PKG + ":jamlet",
    config = ZAMLET_CONFIG,
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "35",
    io_pin_order_cfg = ":jamlet_pin_order.cfg",
)

chisel_dse_module(
    name = "Jamlet_1024lanes",
    top = "Jamlet",
    generator = JAMLET_PKG + ":jamlet",
    config = "//configs:zamlet_1024lanes.json",
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "35",
    io_pin_order_cfg = ":jamlet_pin_order.cfg",
)

chisel_dse_module(
    name = "Jamlet_1024lanes_hard_macros",
    top = "Jamlet",
    generator = JAMLET_PKG + ":jamlet_hard_macros",
    config = "//configs:zamlet_1024lanes.json",
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "35",
    macros = [
        ":Jce_1024lanes_sky130hd_lef",
        ":LocalExec_1024lanes_sky130hd_lef",
        ":Sram_1024lanes_sky130hd_lef",
    ],
    io_pin_order_cfg = ":jamlet_pin_order.cfg",
    synth_config = ":synth_autoname",
)

# (ModuleName, bazel_target_name, extra_generator_args, fp_core_util)
JAMLET_SUB_MODULES = [
    ("RfSlice", "rfslice", [], "35"),
    ("Sram", "sram", [], "35"),
    ("Jce", "jce", [], "35"),
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
    clock_period = "20.0",
    fp_core_util = core_util,
    synth_config = ":synth_autoname",
) for module, target, extra_args, core_util in JAMLET_SUB_MODULES
  for cfg_name, cfg_path in ZAMLET_CONFIGS]

[chisel_dse_module(
    name = "LocalExec_{}".format(cfg_name),
    top = "LocalExec",
    generator = JAMLET_PKG + ":localexec",
    config = cfg_path,
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "35",
    synth_config = ":synth_autoname",
    sdc_fragments = [":localexec.sdc"],
    run_post_grt_design_repair = True,
    run_post_grt_resizer_timing = True,
) for cfg_name, cfg_path in ZAMLET_CONFIGS]

# VectorRf - generic vector register file slice
chisel_dse_module(
    name = "VectorRf_3r1w",
    top = "VectorRf",
    generator = JAMLET_PKG + ":vectorrf",
    config = "//configs:vector_rf_3r1w.json",
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "40",
)

chisel_verilog_no_config(
    name = "JamletMxu",
    generator = JAMLET_PKG + ":jamletmxu",
    extra_args = ["8", "true", "true", "true", "true"],
)

librelane_classic_flow(
    name = "JamletMxu_sky130hd",
    verilog_files = [":JamletMxu.sv"],
    top = "JamletMxu",
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "40",
    io_pin_order_cfg = ":jamlet_mxu8x8_pin_order.cfg",
    sdc_fragments = [":jamlet_mxu8x8.sdc"],
    synth_config = ":synth_mxu_preserve_cell",
    design_repair_max_wire_length = "150",
)

chisel_verilog_no_config(
    name = "SystolicArray",
    generator = SYSTOLIC_PKG + ":systolicarray",
    extra_args = ["8"],
)

librelane_classic_flow(
    name = "SystolicArray_sky130hd",
    verilog_files = [":SystolicArray.sv"],
    top = "SystolicArray",
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "40",
    synth_config = ":synth_autoname",
    design_repair_max_wire_length = "150",
)

chisel_verilog_no_config(
    name = "JamletMxuHardMacros",
    generator = JAMLET_PKG + ":jamletmxu_hard_macros",
    extra_args = ["8", "true", "true", "true"],
)

librelane_classic_flow(
    name = "JamletMxuHardMacros_sky130hd",
    verilog_files = [":JamletMxuHardMacros.sv"],
    top = "JamletMxu",
    pdk = ":sky130hd",
    clock_period = "20.0",
    die_area = "0 0 1400 1400",
    macros = [":JamletMxuGrid4x4_sky130hd_lef"],
    macro_placement_cfg = ":jamlet_mxu_hard_macros_placement.cfg",
    pdn_macro_connections = [
        "(ne_ne|nw_nw|se_se|sw_sw) VPWR VGND VPWR VGND",
    ],
    synth_config = ":synth_autoname",
    design_repair_max_wire_length = "150",
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
    fp_core_util = "40",
    synth_config = ":synth_mxu_preserve_cell",
)

chisel_verilog_no_config(
    name = "JamletMxuGrid4x4",
    generator = JAMLET_PKG + ":jamletmxugrid",
    extra_args = ["4", "true"],
)

librelane_classic_flow(
    name = "JamletMxuGrid4x4_sky130hd",
    verilog_files = [":JamletMxuGrid4x4.sv"],
    top = "JamletMxuGrid",
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "40",
    io_pin_order_cfg = ":jamlet_mxu_grid4x4_pin_order.cfg",
    synth_config = ":synth_mxu_preserve_cell",
    design_repair_max_wire_length = "150",
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
    fp_core_util = "35",
    synth_config = ":synth_autoname",
)
